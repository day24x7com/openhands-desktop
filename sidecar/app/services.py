"""Service helpers shared by the HTTP layer and the agent runtime."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from .db import Database
from .llm import LLMClient, MockLLM, build_client
from .models import EnvCheck, LlmProfile, utcnow
from .workspace import BaseWorkspace, DockerWorkspace, build_workspace

ENV_HINTS = {
    "python": ("python --version", "https://www.python.org/downloads/"),
    "git": ("git --version", "https://git-scm.com/download/win"),
    "node": ("node --version", "https://nodejs.org/"),
    "docker": ("docker --version", "https://docs.docker.com/desktop/install/windows-install/"),
    "wsl": ("wsl --status", "https://learn.microsoft.com/windows/wsl/install"),
}


def profile_to_public(row: dict[str, Any]) -> LlmProfile:
    return LlmProfile(
        id=row["id"],
        name=row["name"],
        provider=row["provider"],
        model=row["model"],
        base_url=row.get("base_url"),
        api_key_ref=row.get("api_key_ref"),
        has_api_key=bool(row.get("api_key_ref")),
        temperature=float(row.get("temperature") or 0.0),
        max_tokens=int(row.get("max_tokens") or 4096),
        timeout_seconds=int(row.get("timeout_seconds") or 300),
        retries=int(row.get("retries") or 2),
        extra_headers=row.get("extra_headers") or {},
        is_default=bool(row.get("is_default")),
        created_at=row.get("created_at") or utcnow(),
    )


def build_llm(client_config: dict[str, Any], api_key: str | None) -> LLMClient:
    return build_client(
        provider=client_config["provider"],
        model=client_config["model"],
        api_key=api_key,
        base_url=client_config.get("base_url"),
        temperature=float(client_config.get("temperature") or 0.0),
        max_tokens=int(client_config.get("max_tokens") or 4096),
        timeout_seconds=int(client_config.get("timeout_seconds") or 300),
        retries=int(client_config.get("retries") or 2),
        extra_headers=client_config.get("extra_headers") or {},
    )


def build_llm_for_conversation(db: Database, conversation: dict[str, Any]) -> LLMClient:
    profile_id = conversation.get("llm_profile_id") or db.get_setting("settings", {}).get("last_llm_profile_id")
    profile: dict[str, Any] | None = db.get_llm_profile(profile_id) if profile_id else None
    if profile is None:
        profiles = db.list_llm_profiles()
        profile = next((p for p in profiles if p.get("is_default")), profiles[0] if profiles else None)
    if profile is None:
        raise RuntimeError(
            "No LLM profile configured. Finish the setup wizard (Providers & models) before chatting."
        )
    if profile["provider"] == "mock":
        return MockLLM()
    vault = db.vault
    api_key = vault.get(profile.get("api_key_ref"))
    return build_llm(profile, api_key)


def workspace_from_row(row: dict[str, Any], mode: str, sandbox_image: str = "python:3.12-slim") -> BaseWorkspace:
    return build_workspace(
        kind=mode,
        workspace_id=row["id"],
        path=row["path"],
        name=row.get("name") or row["path"],
        image=sandbox_image,
    )


def public_workspace(row: dict[str, Any], sandbox_image: str = "python:3.12-slim") -> dict[str, Any]:
    return {
        "id": row["id"],
        "path": row["path"],
        "kind": row.get("kind") or "local",
        "name": row.get("name") or row["path"],
        "git_remote": row.get("git_remote"),
        "last_opened": row.get("last_opened"),
        "container_id": f"ohd-{row['id'][:12]}" if row.get("kind") == "docker" else None,
    }


def detect_environment() -> list[EnvCheck]:
    checks: list[EnvCheck] = []
    for name, (_command, hint) in ENV_HINTS.items():
        exe = shutil.which(name if name != "python" else "python")
        version = None
        available = False
        if exe:
            try:
                proc = subprocess.run(
                    [exe, "--version"], capture_output=True, text=True, timeout=8
                )
                version = (proc.stdout or proc.stderr).strip().splitlines()[0] if proc.stdout or proc.stderr else None
                available = proc.returncode == 0
            except (OSError, subprocess.SubprocessError):
                available = False
        checks.append(EnvCheck(name=name, available=available, version=version, hint=None if available else hint))
    wsl_ok, wsl_version = _wsl_status()
    checks.append(
        EnvCheck(name="wsl2", available=wsl_ok, version=wsl_version, hint=None if wsl_ok else ENV_HINTS["wsl"][1])
    )
    return checks


def _wsl_status() -> tuple[bool, str | None]:
    if shutil.which("wsl") is None and shutil.which("wsl.exe") is None:
        return False, None
    try:
        proc = subprocess.run(["wsl", "--status"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False, None
    text = (proc.stdout or proc.stderr).strip()
    return proc.returncode == 0, text.splitlines()[0][:120] if text else None


def docker_status(sandbox_image: str) -> dict[str, Any]:
    available, message = DockerWorkspace.docker_available()
    images: list[str] = []
    if available:
        proc = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], capture_output=True, text=True
        )
        if proc.returncode == 0:
            images = [line for line in proc.stdout.splitlines() if line][:50]
    return {"available": available, "engine": message, "images": images, "message": message}
