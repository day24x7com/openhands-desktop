#!/usr/bin/env python
"""Run the sidecar with the project's virtualenv interpreter.

`npm run dev:sidecar` uses this so a fresh clone works without activating the
venv first: it prefers `.venv` (created by scripts/setup_dev.py) and falls back
to the interpreter that is running this script.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = REPO_ROOT / ".venv"


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def main() -> int:
    python = venv_python()
    if not python.exists():
        print(
            "[run_sidecar] no .venv found - run `python scripts/setup_dev.py` first, "
            "falling back to the current interpreter",
            file=sys.stderr,
        )
        python = Path(sys.executable)
    cmd = [
        str(python),
        "-m",
        "uvicorn",
        "app.main:app",
        "--port",
        "18080",
        "--reload",
        "--app-dir",
        str(REPO_ROOT / "sidecar"),
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
