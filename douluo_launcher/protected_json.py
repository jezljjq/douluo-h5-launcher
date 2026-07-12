from __future__ import annotations

import base64
import ctypes
import json
import os
import tempfile
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol


PROTECTED_SCHEMA_VERSION = 2
PROTECTION_NAME = "windows-dpapi"


class DataProtector(Protocol):
    def protect(self, data: bytes) -> bytes: ...

    def unprotect(self, data: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsDpapiProtector:
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("DPAPI 仅支持 Windows")

    def protect(self, data: bytes) -> bytes:
        return self._crypt(data, decrypt=False)

    def unprotect(self, data: bytes) -> bytes:
        return self._crypt(data, decrypt=True)

    def _crypt(self, data: bytes, *, decrypt: bool) -> bytes:
        source_buffer = ctypes.create_string_buffer(bytes(data))
        source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
        output = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if decrypt:
            ok = crypt32.CryptUnprotectData(
                ctypes.byref(source),
                None,
                None,
                None,
                None,
                self._CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output),
            )
        else:
            ok = crypt32.CryptProtectData(
                ctypes.byref(source),
                "DouluoH5Launcher",
                None,
                None,
                None,
                self._CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(output),
            )
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)


class ProtectedJsonFile:
    def __init__(
        self,
        path: str | Path,
        *,
        protector: DataProtector | None = None,
        backups_dir: str | Path | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.path = Path(path)
        self.protector = protector or WindowsDpapiProtector()
        self.backups_dir = Path(backups_dir) if backups_dir is not None else self.path.parent / "backups"
        self.log = log or (lambda _message: None)

    def read(self) -> object:
        raw_text = self.path.read_text(encoding="utf-8-sig")
        outer = json.loads(raw_text)
        if self._is_protected_envelope(outer):
            return self._decrypt_envelope(outer)
        self._migrate_plaintext(outer)
        return outer

    def write(self, payload: object) -> Path:
        envelope = self._encrypt_payload(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(self.path, json.dumps(envelope, ensure_ascii=True, indent=2))
        return self.path

    def _migrate_plaintext(self, payload: object) -> None:
        try:
            envelope = self._encrypt_payload(payload)
            self.backups_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
            backup = self.backups_dir / f"{self.path.name}.pre_migration_{stamp}.enc.json"
            serialized = json.dumps(envelope, ensure_ascii=True, indent=2)
            _atomic_write_text(backup, serialized)
            _atomic_write_text(self.path, serialized)
            self.log(f"[数据保护] 已迁移 {self.path.name}，备份={backup.name}")
        except Exception as exc:
            self.log(f"[数据保护] {self.path.name} 迁移失败，保留原文件: {type(exc).__name__}")

    def _encrypt_payload(self, payload: object) -> dict[str, object]:
        plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        protected = self.protector.protect(plain)
        return {
            "schema_version": PROTECTED_SCHEMA_VERSION,
            "protection": PROTECTION_NAME,
            "payload": base64.b64encode(protected).decode("ascii"),
        }

    def _decrypt_envelope(self, envelope: dict[str, object]) -> object:
        encoded = str(envelope.get("payload") or "")
        if not encoded:
            raise ValueError("受保护数据缺少 payload")
        protected = base64.b64decode(encoded, validate=True)
        plain = self.protector.unprotect(protected)
        return json.loads(plain.decode("utf-8"))

    @staticmethod
    def _is_protected_envelope(payload: object) -> bool:
        return (
            isinstance(payload, dict)
            and payload.get("schema_version") == PROTECTED_SCHEMA_VERSION
            and payload.get("protection") == PROTECTION_NAME
            and isinstance(payload.get("payload"), str)
        )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as file:
        temp_path = Path(file.name)
        file.write(text)
        file.write("\n")
    try:
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
