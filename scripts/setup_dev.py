#!/usr/bin/env python
"""One-shot developer setup: create a venv, install sidecar deps, install npm deps.

    python scripts/setup_dev.py

Then run the app with:

    npm run dev:sidecar     # terminal 1 - Python backend on :18080
    npm run dev:ui          # terminal 2 - Vite dev server on :5173
    npm run dev:shell       # terminal 3 - Electron pointing at Vite
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = REPO_ROOT / ".venv"


def run(cmd: list[str], **kwargs: object) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kwargs)  # type: ignore[arg-type]


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def main() -> int:
    if sys.version_info < (3, 11):
        print(f"Python 3.11+ is required, found {sys.version.split()[0]}")
        return 1

    if not venv_python().exists():
        print(f"[setup] creating virtualenv at {VENV_DIR}")
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)
    python = venv_python()

    run([str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    run([str(python), "-m", "pip", "install", "--quiet", "-e", str(REPO_ROOT / "sidecar")])
    run([str(python), "-m", "pip", "install", "--quiet", "pytest", "httpx", "ruff"])

    npm = shutil.which("npm")
    if npm:
        run([npm, "install", "--silent"], cwd=REPO_ROOT)
    else:
        print("[setup] npm not found - install Node.js 20+ to build the desktop UI")

    print("\n[setup] running sidecar tests")
    run([str(python), "-m", "pytest", str(REPO_ROOT / "sidecar" / "tests"), "-q"])
    print("\n[setup] ready. Start with: npm run dev:sidecar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
