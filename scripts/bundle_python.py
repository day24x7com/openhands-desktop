#!/usr/bin/env python
"""Bundle a self-contained CPython runtime for the Windows installer.

The desktop app must work on a machine with no Python installed, so the build
downloads the official *embeddable* CPython distribution, unpacks it into
``build/python-runtime`` and installs the sidecar requirements into it using
plain ``pip --target`` (the embeddable build ships no pip).

Usage:
    python scripts/bundle_python.py --arch x64
    python scripts/bundle_python.py --arch x64 --python-version 3.12.8
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SIDECAR_DIR = REPO_ROOT / "sidecar"
BUILD_DIR = REPO_ROOT / "build"
RUNTIME_DIR = BUILD_DIR / "python-runtime"

# Packages the embeddable distribution omits but FastAPI/uvicorn/pydantic need.
EXTRA_PACKAGES = ["pip", "setuptools", "wheel"]

# `_pth` file entries required so the embedded interpreter can import the
# standard library *and* site-packages (the embeddable distro disables `site`
# by default, which breaks pip installs into the same directory).
PTH_TEMPLATE = """python{tag}.zip
.
Lib
Lib/site-packages
import site
"""


def download(version: str, arch: str, dest: Path) -> Path:
    url = (
        f"https://www.python.org/ftp/python/{version}/"
        f"python-{version}-embed-{arch}.zip"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"[bundle] reusing cached {dest.name}")
        return dest
    print(f"[bundle] downloading {url}")
    urllib.request.urlretrieve(url, dest)
    return dest


def unpack(archive: Path) -> None:
    if RUNTIME_DIR.exists():
        shutil.rmtree(RUNTIME_DIR)
    RUNTIME_DIR.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(RUNTIME_DIR)
    print(f"[bundle] unpacked runtime into {RUNTIME_DIR}")


def patch_pth(version: str) -> None:
    tag = version.replace(".", "")
    major_minor = "".join(version.split(".")[:2])
    candidates = list(RUNTIME_DIR.glob("python*._pth"))
    if not candidates:
        raise SystemExit("No ._pth file found in the embedded distribution")
    pth = candidates[0]
    pth.write_text(PTH_TEMPLATE.format(tag=major_minor), encoding="utf-8")
    print(f"[bundle] patched {pth.name} for python{tag}")


def install_requirements(python_exe: Path) -> None:
    target = RUNTIME_DIR / "Lib" / "site-packages"
    target.mkdir(parents=True, exist_ok=True)
    for package in EXTRA_PACKAGES:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade",
             "--target", str(target), package],
            check=True,
        )
    # Install the sidecar itself (installs its runtime deps from pyproject.toml).
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(target),
         "--no-warn-script-location", str(SIDECAR_DIR)],
        check=True,
    )
    # pip leaves build artefacts in the target that bloat the installer.
    for junk in ("bin", "Scripts"):
        shutil.rmtree(target.parent / junk, ignore_errors=True)
    for pattern in ("*.dist-info/RECORD", "*.dist-info/INSTALLER"):
        for path in target.glob(pattern):
            path.unlink(missing_ok=True)
    print(f"[bundle] installed sidecar requirements into {target}")


def smoke_test(python_exe: Path) -> None:
    probe = (
        "import fastapi, uvicorn, pydantic, httpx, sys; "
        "print('runtime ok', sys.version.split()[0])"
    )
    result = subprocess.run(
        [str(python_exe), "-c", probe], capture_output=True, text=True, cwd=str(RUNTIME_DIR)
    )
    if result.returncode != 0:
        raise SystemExit(f"Bundled runtime failed to import dependencies:\n{result.stderr}")
    print(f"[bundle] {result.stdout.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", default="amd64", choices=["amd64", "win32", "arm64"])
    parser.add_argument("--python-version", default="3.12.8")
    args = parser.parse_args()

    archive = BUILD_DIR / f"python-{args.python_version}-embed-{args.arch}.zip"
    download(args.python_version, args.arch, archive)
    unpack(archive)
    patch_pth(args.python_version)
    install_requirements(RUNTIME_DIR / "python.exe")
    smoke_test(RUNTIME_DIR / "python.exe")
    size_mb = sum(p.stat().st_size for p in RUNTIME_DIR.rglob("*") if p.is_file()) / 1e6
    print(f"[bundle] done: {RUNTIME_DIR} ({size_mb:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
