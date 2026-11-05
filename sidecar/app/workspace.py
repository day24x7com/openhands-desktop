"""Workspace implementations: local folder (default) and Docker sandbox (optional).

Both expose the same interface so the agent loop and the file/diff API do not care
where files actually live. Docker mode mounts the user's project directory and runs
shell commands inside a container; file operations still go through the host so the
editor and diff views work identically.
"""

from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import FileDiff, FileNode
from .safety import PathGuardError, resolve_in_workspace
from .shell import ShellResult, run_command

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".pytest_cache",
    ".mypy_cache",
    "target",
    ".idea",
    ".vscode",
}

LANGUAGE_BY_EXT = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".css": "css",
    ".html": "html",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".sh": "shell",
    ".ps1": "powershell",
    ".sql": "sql",
    ".c": "c",
    ".cpp": "cpp",
}

MAX_FILE_BYTES = 1_000_000


class WorkspaceError(RuntimeError):
    pass


@dataclass
class WorkspaceRef:
    id: str
    path: Path
    kind: str
    name: str


class BaseWorkspace:
    def __init__(self, ref: WorkspaceRef) -> None:
        self.ref = ref
        self.root = ref.path

    # ---------------------------------------------------------- filesystem
    def resolve(self, relative: str) -> Path:
        return resolve_in_workspace(self.root, relative)

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def read_text(self, relative: str) -> tuple[str, str]:
        path = self.resolve(relative)
        if not path.is_file():
            raise WorkspaceError(f"file not found: {relative}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError(f"file too large to open: {relative}")
        raw = path.read_bytes()
        eol = "crlf" if b"\r\n" in raw else "lf"
        text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
        return text, eol

    def write_text(self, relative: str, content: str, eol: str = "lf") -> Path:
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.replace("\r\n", "\n")
        if eol == "crlf":
            data = data.replace("\n", "\r\n")
        path.write_text(data, encoding="utf-8", newline="")
        return path

    def delete(self, relative: str) -> None:
        path = self.resolve(relative)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    def tree(self, relative: str = ".", depth: int = 2) -> list[FileNode]:
        base = self.resolve(relative)
        if not base.is_dir():
            raise WorkspaceError(f"not a directory: {relative}")
        nodes: list[FileNode] = []
        git = self.git_status_map()
        base_depth = len(base.resolve().parts)

        def walk(current: Path) -> None:
            for entry in sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                if entry.name in SKIP_DIRS or entry.name.startswith(".DS_Store"):
                    continue
                rel_path = self.rel(entry)
                level = len(entry.resolve().parts) - base_depth
                if entry.is_dir():
                    nodes.append(FileNode(name=entry.name, path=rel_path, type="dir"))
                    if level < depth:
                        walk(entry)
                else:
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        size = None
                    nodes.append(
                        FileNode(
                            name=entry.name,
                            path=rel_path,
                            type="file",
                            size=size,
                            git_status=git.get(rel_path),
                        )
                    )

        walk(base)
        return nodes

    # ------------------------------------------------------------ git bits
    def _git(self, *args: str) -> str:
        """Run git without a shell so output (leading spaces, NULs) is byte-exact."""
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=60,
                errors="replace",
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return proc.stdout if proc.returncode == 0 else ""

    def _git_checked(self, *args: str) -> tuple[bool, str]:
        """Run git and return (ok, stdout+stderr) so callers can surface errors."""
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=120,
                errors="replace",
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"could not run git: {exc}"
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, output.strip()

    def is_git_repo(self) -> bool:
        return (self.root / ".git").exists()

    def git_init(self) -> tuple[bool, str]:
        """Initialise a repository in the workspace root (FR-9.1)."""
        if self.is_git_repo():
            return True, "Already a git repository."
        return self._git_checked("init")

    def git_commit(self, message: str, paths: list[str] | None = None) -> tuple[bool, str]:
        """Stage and commit. ``paths`` restricts the commit to specific files.

        Staging is explicit (``-A`` by default) so the commit only ever contains
        files inside the workspace root that git itself can see.
        """
        message = (message or "").strip()
        if not message:
            return False, "A commit message is required."
        # `--` must come *after* the flag, otherwise git treats "-A" as a pathspec.
        args = ["add", "-A"] if not paths else ["add", "--", *paths]
        ok, output = self._git_checked(*args)
        if not ok:
            return False, output or "git add failed"
        name = self._git("config", "user.name").strip()
        email = self._git("config", "user.email").strip()
        identity = []
        if not name:
            identity += ["-c", "user.name=OpenHands Desktop"]
        if not email:
            identity += ["-c", "user.email=openhands@localhost"]
        return self._git_checked(*identity, "commit", "-m", message)

    def git_branches(self) -> dict[str, Any]:
        current = self._git("rev-parse", "--abbrev-ref", "HEAD").strip() or None
        listing = self._git("branch", "--format=%(refname:short)")
        names = [line.strip() for line in listing.splitlines() if line.strip()]
        return {"current": current, "branches": names}

    def git_checkout(self, branch: str, create: bool = False) -> tuple[bool, str]:
        branch = (branch or "").strip()
        if not branch:
            return False, "A branch name is required."
        args = ["checkout", "-b", branch] if create else ["checkout", branch]
        return self._git_checked(*args)

    def git_status_map(self) -> dict[str, str]:
        if not self.is_git_repo():
            return {}
        out = self._git("status", "--porcelain=v1", "-z")
        mapping: dict[str, str] = {}
        entries = [entry for entry in out.split("\0") if entry]
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if len(entry) < 4:
                continue
            if "\x00" not in out and entry[:2].strip() and entry[2:3] == " ":
                # tolerate `git status --porcelain` without NULs: " M path"
                code, path = entry[:2].strip(), entry[2:].strip().replace("\\", "/")
            else:
                code, path = entry[:2].strip(), entry[3:].replace("\\", "/")
            if "R" in entry[:2] and index < len(entries):
                # renames carry the original path as the next NUL-separated field
                index += 1
            letter = code[0] if code else "M"
            mapping[path] = {
                "M": "M",
                "A": "A",
                "D": "D",
                "R": "M",
                "U": "M",
            }.get(letter, "?")
        return mapping

    def git_status(self) -> dict[str, Any]:
        if not self.is_git_repo():
            return {"branch": None, "entries": [], "ahead": 0, "behind": 0}
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD").strip() or None
        entries = [
            {"path": path, "status": status}
            for path, status in sorted(self.git_status_map().items())
        ]
        ahead = behind = 0
        counts = self._git("rev-list", "--left-right", "--count", "@{u}...HEAD")
        if counts and len(counts.split()) == 2:
            behind, ahead = (int(x) for x in counts.split())
        return {"branch": branch, "entries": entries, "ahead": ahead, "behind": behind}

    def git_diff(self, relative: str | None = None) -> list[FileDiff]:
        if not self.is_git_repo():
            return []
        target = self._git("diff", "HEAD", "--", relative) if relative else self._git("diff", "HEAD")
        diffs = parse_unified_diff(target)
        if relative and not diffs:
            # Untracked files do not show up in `git diff HEAD`; synthesise an added diff.
            path = self.resolve(relative)
            if path.is_file():
                text, _ = self.read_text(relative)
                diffs = [_whole_file_diff(relative, text, added=True)]
        return diffs

    def changed_files(self) -> list[str]:
        return sorted(self.git_status_map().keys())

    # --------------------------------------------------------------- shell
    def run(self, command: str, shell: str | None = None, timeout: int = 180) -> ShellResult:
        return run_command(command, cwd=self.root, shell=shell, timeout=timeout)

    def shell_cwd(self) -> str:
        """Working directory handed to the sandbox (differs for Docker)."""
        return str(self.root)

    def cleanup(self) -> None:  # pragma: no cover - overridden by docker
        return None


class LocalWorkspace(BaseWorkspace):
    pass


class DockerWorkspace(BaseWorkspace):
    """Runs shell commands inside a container with the project directory mounted."""

    def __init__(self, ref: WorkspaceRef, image: str = "python:3.12-slim") -> None:
        super().__init__(ref)
        self.image = image
        self.container_name = f"ohd-{ref.id[:12]}"

    @staticmethod
    def docker_available() -> tuple[bool, str]:
        if shutil.which("docker") is None:
            return False, "docker CLI not found on PATH"
        try:
            proc = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"docker daemon unreachable: {exc}"
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout).strip() or "docker daemon unreachable"
        return True, proc.stdout.strip()

    def ensure_container(self) -> str:
        available, message = self.docker_available()
        if not available:
            raise WorkspaceError(f"Docker is not available: {message}")
        existing = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", self.container_name],
            capture_output=True,
            text=True,
        )
        if existing.returncode == 0 and existing.stdout.strip() == "true":
            return self.container_name
        subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True)
        host_path = str(self.root)
        created = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self.container_name,
                "-w",
                "/workspace",
                "-v",
                f"{host_path}:/workspace",
                "--add-host",
                "host.docker.internal:host-gateway",
                self.image,
                "sleep",
                "infinity",
            ],
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:
            raise WorkspaceError(f"failed to start sandbox: {created.stderr.strip()}")
        return self.container_name

    def run(self, command: str, shell: str | None = None, timeout: int = 180) -> ShellResult:
        self.ensure_container()
        started = time.monotonic()
        proc = subprocess.run(
            ["docker", "exec", "-w", "/workspace", self.container_name, "bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=timeout + 10,
        )
        output = (proc.stdout + proc.stderr).strip()
        return ShellResult(
            ok=proc.returncode == 0,
            output=output[:200_000],
            exit_code=proc.returncode,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def shell_cwd(self) -> str:
        return "/workspace"

    def cleanup(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True)


def build_workspace(kind: str, workspace_id: str, path: Path, name: str, image: str) -> BaseWorkspace:
    ref = WorkspaceRef(id=workspace_id, path=Path(path), kind=kind, name=name)
    if kind == "docker":
        return DockerWorkspace(ref, image=image)
    return LocalWorkspace(ref)


# ---------------------------------------------------------------- diffs


def parse_unified_diff(text: str) -> list[FileDiff]:
    """Parse `git diff` output into per-file hunks for the UI."""
    diffs: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith("diff --git"):
            if current:
                diffs.append(current)
            current = FileDiff(path="", status="modified", hunks=[], additions=0, deletions=0)
            hunk = None
        elif current is None:
            continue
        elif line.startswith("new file mode"):
            current.status = "added"
        elif line.startswith("deleted file mode"):
            current.status = "deleted"
        elif line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            current.path = line[6:].removeprefix("b/")
        elif line.startswith("--- ") and not line.startswith("--- /dev/null") and not current.path:
            current.path = line[6:].removeprefix("a/")
        elif line.startswith("@@"):
            if hunk:
                current.hunks.append(hunk)
            header = line.split("@@")[1].strip()
            old_part, new_part = header.split(" ")
            old_start, old_lines = _parse_range(old_part)
            new_start, new_lines = _parse_range(new_part)
            hunk = {
                "old_start": old_start,
                "old_lines": old_lines,
                "new_start": new_start,
                "new_lines": new_lines,
                "lines": [],
            }
        elif hunk is not None and (line.startswith(("+", "-", " ")) or line == ""):
            hunk["lines"].append(line)
            if line.startswith("+") and not line.startswith("+++"):
                current.additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                current.deletions += 1
    if hunk and current:
        current.hunks.append(hunk)
    if current:
        diffs.append(current)
    return [d for d in diffs if d.path]


def _parse_range(part: str) -> tuple[int, int]:
    part = part.lstrip("+-")
    if "," in part:
        start, count = part.split(",", 1)
        return int(start), int(count)
    return int(part), 1


def diff_text(path: str, before: str, after: str) -> FileDiff:
    """Build a FileDiff between two strings (used for agent edits)."""
    hunks = []
    additions = deletions = 0
    old_lines = _split_keepends(before)
    new_lines = _split_keepends(after)
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    for group in matcher.get_grouped_opcodes(3):
        lines: list[str] = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                lines.extend(" " + line for line in old_lines[i1:i2])
                continue
            lines.extend("-" + line for line in old_lines[i1:i2])
            deletions += i2 - i1
            lines.extend("+" + line for line in new_lines[j1:j2])
            additions += j2 - j1
        if lines:
            hunks.append(
                {
                    "old_start": group[0][1] + 1,
                    "old_lines": group[-1][2] - group[0][1],
                    "new_start": group[0][3] + 1,
                    "new_lines": group[-1][4] - group[0][3],
                    "lines": lines,
                }
            )
    status = "added" if not before else ("deleted" if not after else "modified")
    return FileDiff(path=path, status=status, hunks=hunks, additions=additions, deletions=deletions)


def _split_keepends(text: str) -> list[str]:
    """Split on newlines without inventing an extra empty line for trailing newlines."""
    if not text:
        return []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _whole_file_diff(path: str, text: str, added: bool) -> FileDiff:
    lines = ["+" + line for line in text.splitlines()] if added else ["-" + line for line in text.splitlines()]
    return FileDiff(
        path=path,
        status="added" if added else "deleted",
        hunks=[
            {
                "old_start": 0,
                "old_lines": 0 if added else len(text.splitlines()),
                "new_start": 1,
                "new_lines": len(text.splitlines()) if added else 0,
                "lines": lines,
            }
        ],
        additions=len(lines) if added else 0,
        deletions=0 if added else len(lines),
    )


def guess_language(path: str) -> str:
    return LANGUAGE_BY_EXT.get(Path(path).suffix.lower(), "plaintext")


def normalise_user_path(raw: str) -> Path:
    """Expand `~`, environment variables and normalise separators (spec §11.1)."""
    expanded = os.path.expandvars(os.path.expanduser(raw.strip().strip('"')))
    if len(expanded) > 1 and expanded[1] == ":":
        # Windows drive path: normalise separators but keep the drive root.
        return Path(Path(expanded).as_posix())
    return Path(expanded).resolve()


def to_container_path(path: str, root: Path) -> str:
    """Translate a host path to the sandbox mount path (spec §5.5 / FR-5.4)."""
    try:
        rel = Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path
    return f"/workspace/{rel}" if rel != "." else "/workspace"


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


__all__ = [
    "BaseWorkspace",
    "DockerWorkspace",
    "LocalWorkspace",
    "PathGuardError",
    "WorkspaceError",
    "WorkspaceRef",
    "build_workspace",
    "diff_text",
    "guess_language",
    "normalise_user_path",
    "parse_unified_diff",
    "to_container_path",
]
