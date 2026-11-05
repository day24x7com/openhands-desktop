"""Runtime configuration for the sidecar.

Everything is driven by environment variables so the Electron shell can spawn the
process with an isolated data directory and a one-time session token.
"""

from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    """Per-user data directory, matching the locations in the product spec."""
    override = os.environ.get("OHD_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "OpenHandsDesktop"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenHandsDesktop"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "openhands-desktop"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)
    # When no token is supplied (dev / UI-only mode) auth is disabled.
    session_token: str | None = field(default_factory=lambda: os.environ.get("OHD_SESSION_TOKEN") or None)
    host: str = "127.0.0.1"
    port: int = 0
    #: Allow non-loopback binds. Loopback-only is a security requirement (spec §11.9).
    allow_remote_bind: bool = field(default_factory=lambda: _env_bool("OHD_ALLOW_REMOTE_BIND", False))
    #: Directory holding the Docker sandbox runtime image reference.
    sandbox_image: str = field(default_factory=lambda: os.environ.get("OHD_SANDBOX_IMAGE", "python:3.12-slim"))
    #: Hard ceiling for a single agent run, protects against runaway loops.
    max_agent_steps: int = field(default_factory=lambda: int(os.environ.get("OHD_MAX_AGENT_STEPS", "40")))
    #: Delay between approval polling ticks.
    approval_poll_seconds: float = 0.2

    @property
    def db_path(self) -> Path:
        return self.data_dir / "openhands-desktop.db"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.logs_dir, self.attachments_dir):
            path.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)
