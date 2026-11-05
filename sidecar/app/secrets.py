"""Encrypted-at-rest secret storage for LLM API keys (spec §15.9).

On Windows the cipher key is additionally protected with DPAPI via ``ctypes`` so the
key material is bound to the current user account. On other platforms the key lives in
a ``0600`` file inside the app data directory.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

_PREFIX = "vault:"
_KEY_FILE = "vault.key"


class SecretVault:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / _KEY_FILE
        self._key = self._load_key()

    # ------------------------------------------------------------- public
    def put(self, name: str, value: str) -> str:
        """Store a secret and return an opaque reference string."""
        token = self._encrypt(value)
        self._write(name, token)
        return f"{_PREFIX}{name}"

    def get(self, ref_or_name: str | None) -> str | None:
        if not ref_or_name:
            return None
        name = ref_or_name.removeprefix(_PREFIX)
        token = self._read(name)
        if token is None:
            return None
        try:
            return self._decrypt(token)
        except Exception:
            return None

    def delete(self, ref_or_name: str | None) -> None:
        if not ref_or_name:
            return
        name = ref_or_name.removeprefix(_PREFIX)
        path = self._secret_path(name)
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------ helpers
    def _secret_path(self, name: str) -> Path:
        safe = hashlib.sha256(name.encode()).hexdigest()[:32]
        return self._path.parent / "secrets" / f"{safe}.json"

    def _read(self, name: str) -> str | None:
        path = self._secret_path(name)
        if not path.exists():
            return None
        data = json.loads(path.read_text("utf-8"))
        return data.get("token")

    def _write(self, name: str, token: str) -> None:
        path = self._secret_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": name, "token": token}), "utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _load_key(self) -> bytes:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            raw = base64.b64decode(self._path.read_text("utf-8").strip())
            if sys.platform == "win32":
                try:
                    return dpapi_unprotect(raw)
                except Exception:
                    return raw
            return raw
        key = secrets.token_bytes(32)
        stored = dpapi_protect(key) if sys.platform == "win32" else key
        self._path.write_text(base64.b64encode(stored).decode(), "utf-8")
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass
        return key

    def _keystream(self, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            out.extend(hashlib.sha256(self._key + nonce + counter.to_bytes(8, "big")).digest())
            counter += 1
        return bytes(out[:length])

    def _encrypt(self, value: str) -> str:
        nonce = secrets.token_bytes(16)
        plain = value.encode("utf-8")
        ct = bytes(a ^ b for a, b in zip(plain, self._keystream(nonce, len(plain)), strict=True))
        tag = hashlib.sha256(self._key + nonce + ct).hexdigest()[:16]
        return base64.b64encode(nonce + ct).decode() + "." + tag

    def _decrypt(self, token: str) -> str:
        payload_b64, tag = token.split(".")
        blob = base64.b64decode(payload_b64)
        nonce, ct = blob[:16], blob[16:]
        expected = hashlib.sha256(self._key + nonce + ct).hexdigest()[:16]
        if not secrets.compare_digest(expected, tag):
            raise ValueError("secret integrity check failed")
        plain = bytes(a ^ b for a, b in zip(ct, self._keystream(nonce, len(ct)), strict=True))
        return plain.decode("utf-8")


# --------------------------------------------------------------- DPAPI (Win)
if sys.platform == "win32":

    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
        buf = ctypes.create_string_buffer(data, len(data))
        return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def dpapi_protect(data: bytes) -> bytes:
        blob_in, _ = _blob(data)
        blob_out = _DataBlob()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            raise OSError("CryptProtectData failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    def dpapi_unprotect(data: bytes) -> bytes:
        blob_in, _ = _blob(data)
        blob_out = _DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            raise OSError("CryptUnprotectData failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

else:

    def dpapi_protect(data: bytes) -> bytes:  # pragma: no cover - non-Windows
        return data

    def dpapi_unprotect(data: bytes) -> bytes:  # pragma: no cover - non-Windows
        return data
