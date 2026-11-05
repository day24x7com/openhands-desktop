"""Safety layer: command classification, approval policy and workspace path guarding.

The spec makes this mandatory for the default "Local Workspace" mode (spec §5.5, §16):
the agent edits the user's own files, so destructive commands must be confirmed and
path traversal outside the workspace must be impossible.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"\brmdir\s+/s\b", "recursive directory delete"),
    (r"\bdel\s+/[sfq]\b", "forced/recursive file delete"),
    (r"\bRemove-Item\b.*(-Recurse|-Force)", "recursive/forced PowerShell delete"),
    (r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(/|\*|~)", "recursive or root file delete"),
    (r"\bformat\s+[a-zA-Z]:", "disk format"),
    (r"\bmkfs(\.\w+)?\b", "filesystem creation"),
    (r"\bdd\s+.*of=/dev/", "raw disk write"),
    (r"\bshutdown\b|\breboot\b", "system power state change"),
    (r"(^|[;&|])\s*(curl|wget|iwr|Invoke-WebRequest)\b[^|]*\|\s*(ba|z|pw|po)?sh\b", "pipe-to-shell download"),
    (r"\bgit\s+push\b.*(--force|-f)\b", "force push"),
    (r"\bgit\s+reset\s+--hard\b", "destructive git reset"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*[fd]", "destructive git clean"),
    (r"\bchmod\s+-R\s+777\b", "world-writable permissions"),
    (r"\b(crontab|schtasks)\b", "scheduled task modification"),
    (r"\breg\s+(add|delete)\b|\bSet-ItemProperty\s+HKLM", "registry modification"),
    (r"\bnet\s+user\b|\bnet\s+localgroup\b", "user/group modification"),
    (r"\btaskkill\s+/f\b", "force kill process"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "fork bomb"),
    (r"\b(sudo|runas)\b", "privilege escalation"),
    (r">\s*/dev/(sd|nvme)", "raw device write"),
]

SENSITIVE_PATH_PATTERNS = [
    "**/AppData/Roaming/Microsoft/**",
    "**/.ssh/**",
    "**/.aws/**",
    "**/.gnupg/**",
    "**/System32/**",
    "**/Program Files/**",
    "**/.git/config",
]


@dataclass(frozen=True)
class RiskVerdict:
    risky: bool
    reason: str
    rule: str | None = None


def classify_command(command: str) -> RiskVerdict:
    """Return whether a shell command needs explicit user approval."""
    if not command or not command.strip():
        return RiskVerdict(False, "empty command")
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return RiskVerdict(True, f"Command matches risky pattern: {reason}", pattern)
    if re.search(r"\b(cd|cd\.\.)\b.*&&.*\brm\b", command, flags=re.IGNORECASE):
        return RiskVerdict(True, "Command chains a directory change with a delete")
    return RiskVerdict(False, "looks safe")


def is_sensitive_path(path: str | Path, workspace: Path) -> bool:
    """Guard against touching credential stores or OS directories via the file tools."""
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(workspace.resolve())
    except ValueError:
        return True
    normalised = resolved.as_posix().lower()
    return any(
        fnmatch.fnmatch(normalised, pat.lower().replace("**/", "*")) for pat in SENSITIVE_PATH_PATTERNS
    )


class PathGuardError(ValueError):
    """Raised when a tool tries to escape the workspace root."""


def resolve_in_workspace(workspace: Path, relative: str) -> Path:
    """Resolve ``relative`` inside ``workspace``; raise if it escapes.

    Rejects absolute inputs, drive-relative paths (``C:foo``), UNC paths and ``..``
    traversal, including Windows short names and mixed separators.
    """
    if not relative or relative in {".", "./"}:
        return workspace.resolve()
    candidate = Path(relative.replace("\\", "/"))
    if candidate.is_absolute() or (len(relative) > 1 and relative[1] == ":"):
        raise PathGuardError(f"absolute paths are not allowed: {relative!r}")
    root = workspace.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PathGuardError(f"path escapes workspace: {relative!r}") from exc
    return resolved
