from __future__ import annotations

from dataclasses import dataclass
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import subprocess
from typing import Any

from .models import VOICE_LIBRARY_URL, now_iso

CRYPTPROTECT_UI_FORBIDDEN = 0x01
KEYCHAIN_SERVICE = "Compositor"
KEYCHAIN_LABELS = {
    "elevenlabs_api_key": "Compositor ElevenLabs API Key",
}


class SecureStoreError(RuntimeError):
    pass


@dataclass
class ProviderSecret:
    storage_mode: str
    ciphertext_b64: str


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _platform_name() -> str:
    return platform.system().lower()


def _available_storage_backend() -> str:
    name = _platform_name()
    if name == "windows":
        return "windows_dpapi"
    if name == "darwin":
        return "macos_keychain"
    return "unsupported"


def _app_state_dir() -> Path:
    name = _platform_name()
    if name == "windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Compositor"
    if name == "darwin":
        return Path.home() / "Library" / "Application Support" / "Compositor"
    return Path.home() / ".compositor"


def _blob_from_bytes(raw: bytes) -> tuple[DATA_BLOB, ctypes.Array[ctypes.c_char] | None]:
    if not raw:
        return DATA_BLOB(0, ctypes.cast(ctypes.c_void_p(), ctypes.POINTER(ctypes.c_char))), None
    buffer = ctypes.create_string_buffer(raw)
    return DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _bytes_from_blob(blob: DATA_BLOB) -> bytes:
    if not blob.cbData:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def _crypt_protect(raw: bytes, description: str) -> bytes:
    if _platform_name() != "windows":
        raise SecureStoreError("Windows DPAPI is only available on Windows.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, in_buffer = _blob_from_bytes(raw)
    out_blob = DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        ctypes.c_wchar_p(description),
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    ):
        raise SecureStoreError(f"CryptProtectData failed: {ctypes.GetLastError()}")
    try:
        return _bytes_from_blob(out_blob)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def _crypt_unprotect(raw: bytes) -> bytes:
    if _platform_name() != "windows":
        raise SecureStoreError("Windows DPAPI is only available on Windows.")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, in_buffer = _blob_from_bytes(raw)
    out_blob = DATA_BLOB()
    description = wintypes.LPWSTR()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        ctypes.byref(description),
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    ):
        raise SecureStoreError(f"CryptUnprotectData failed: {ctypes.GetLastError()}")
    try:
        return _bytes_from_blob(out_blob)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)
        if description:
            kernel32.LocalFree(description)


def _keychain_run(args: list[str], *, allow_missing: bool = False) -> subprocess.CompletedProcess[str]:
    if _platform_name() != "darwin":
        raise SecureStoreError("macOS Keychain is only available on macOS.")
    try:
        proc = subprocess.run(
            ["security", *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise SecureStoreError("The macOS 'security' tool was not found.") from exc
    if proc.returncode == 0:
        return proc
    stderr = (proc.stderr or "").strip()
    if allow_missing and "could not be found" in stderr.lower():
        return proc
    raise SecureStoreError(stderr or f"security {' '.join(args)} failed with exit code {proc.returncode}")


def _keychain_set_secret(key: str, value: str) -> None:
    _keychain_run(
        [
            "add-generic-password",
            "-U",
            "-a",
            key,
            "-s",
            KEYCHAIN_SERVICE,
            "-l",
            KEYCHAIN_LABELS.get(key, key),
            "-w",
            value,
        ]
    )


def _keychain_get_secret(key: str) -> str | None:
    proc = _keychain_run(
        ["find-generic-password", "-a", key, "-s", KEYCHAIN_SERVICE, "-w"],
        allow_missing=True,
    )
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").rstrip("\r\n")


def _keychain_delete_secret(key: str) -> None:
    _keychain_run(
        ["delete-generic-password", "-a", key, "-s", KEYCHAIN_SERVICE],
        allow_missing=True,
    )


class AppSettingsStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else _app_state_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.base_dir / "settings.json"
        self.secrets_path = self.base_dir / "secrets.json"

    def public_settings(self) -> dict[str, Any]:
        settings = self._load_settings()
        provider = dict(settings.get("providers", {}).get("elevenlabs", {}))
        configured = self._has_secret("elevenlabs_api_key")
        provider.setdefault("voice_library_url", VOICE_LIBRARY_URL)
        provider["configured"] = configured
        provider["storage_backend"] = self._storage_backend()
        provider["storage_mode"] = self._secret_storage_mode("elevenlabs_api_key")
        provider.setdefault("cached_voices", [])
        provider.setdefault("cached_voice_count", len(provider.get("cached_voices") or []))
        return {"providers": {"elevenlabs": provider}}

    def set_elevenlabs_api_key(self, api_key: str) -> dict[str, Any]:
        storage_mode = self._set_secret("elevenlabs_api_key", api_key)
        settings = self._load_settings()
        provider = settings.setdefault("providers", {}).setdefault("elevenlabs", {})
        provider["configured_at"] = now_iso()
        provider["storage_backend"] = self._storage_backend()
        provider["storage_mode"] = storage_mode
        provider.pop("last_error", None)
        self._write_json(self.settings_path, settings)
        return self.public_settings()

    def clear_elevenlabs_api_key(self) -> dict[str, Any]:
        self._clear_secret("elevenlabs_api_key")
        settings = self._load_settings()
        provider = settings.setdefault("providers", {}).setdefault("elevenlabs", {})
        provider["storage_backend"] = self._storage_backend()
        provider["storage_mode"] = "unset"
        provider["cached_voices"] = []
        provider["cached_voice_count"] = 0
        provider.pop("account", None)
        provider.pop("last_validated_at", None)
        provider.pop("last_error", None)
        self._write_json(self.settings_path, settings)
        return self.public_settings()

    def get_elevenlabs_api_key(self) -> str | None:
        return self._get_secret("elevenlabs_api_key")

    def update_elevenlabs_cache(
        self,
        *,
        account: dict[str, Any] | None = None,
        cached_voices: list[dict[str, Any]] | None = None,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        settings = self._load_settings()
        provider = settings.setdefault("providers", {}).setdefault("elevenlabs", {})
        provider["storage_backend"] = self._storage_backend()
        provider["storage_mode"] = self._secret_storage_mode("elevenlabs_api_key")
        if account is not None:
            provider["account"] = account
        if cached_voices is not None:
            provider["cached_voices"] = cached_voices
            provider["cached_voice_count"] = len(cached_voices)
        if last_error:
            provider["last_error"] = last_error
        else:
            provider.pop("last_error", None)
            if account is not None or cached_voices is not None:
                provider["last_validated_at"] = now_iso()
        self._write_json(self.settings_path, settings)
        return self.public_settings()

    def _storage_backend(self) -> str:
        return _available_storage_backend()

    def _secret_storage_mode(self, key: str) -> str:
        return self._storage_backend() if self._has_secret(key) else "unset"

    def _set_secret(self, key: str, value: str) -> str:
        backend = self._storage_backend()
        if backend == "windows_dpapi":
            secret = ProviderSecret(
                storage_mode=backend,
                ciphertext_b64=base64.b64encode(
                    _crypt_protect(value.encode("utf-8"), KEYCHAIN_LABELS.get(key, key))
                ).decode("ascii"),
            )
            secrets = self._load_secrets()
            secrets[key] = {"storage_mode": secret.storage_mode, "ciphertext_b64": secret.ciphertext_b64}
            self._write_json(self.secrets_path, secrets)
            return backend
        if backend == "macos_keychain":
            _keychain_set_secret(key, value)
            return backend
        raise SecureStoreError("No supported secure secret backend is available on this platform.")

    def _get_secret(self, key: str) -> str | None:
        backend = self._storage_backend()
        if backend == "windows_dpapi":
            payload = self._load_secrets().get(key)
            if not payload:
                return None
            ciphertext_b64 = str(payload.get("ciphertext_b64") or "")
            if not ciphertext_b64:
                return None
            decrypted = _crypt_unprotect(base64.b64decode(ciphertext_b64.encode("ascii")))
            return decrypted.decode("utf-8")
        if backend == "macos_keychain":
            return _keychain_get_secret(key)
        return None

    def _clear_secret(self, key: str) -> None:
        backend = self._storage_backend()
        if backend == "windows_dpapi":
            secrets = self._load_secrets()
            secrets.pop(key, None)
            self._write_json(self.secrets_path, secrets)
            return
        if backend == "macos_keychain":
            _keychain_delete_secret(key)
            return

    def _has_secret(self, key: str) -> bool:
        backend = self._storage_backend()
        if backend == "windows_dpapi":
            payload = self._load_secrets().get(key)
            return bool(payload and payload.get("ciphertext_b64"))
        if backend == "macos_keychain":
            return _keychain_get_secret(key) is not None
        return False

    def _load_settings(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return {
                "providers": {
                    "elevenlabs": {
                        "voice_library_url": VOICE_LIBRARY_URL,
                        "cached_voices": [],
                        "storage_backend": self._storage_backend(),
                    }
                }
            }
        return self._read_json(self.settings_path)

    def _load_secrets(self) -> dict[str, Any]:
        if not self.secrets_path.exists():
            return {}
        return self._read_json(self.secrets_path)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
