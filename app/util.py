# -*- coding: utf-8 -*-
"""通用工具：原子写文件、Key 脱敏、Windows DPAPI 加密、时间工具。"""
import base64
import ctypes
import json
import os
import sys
import tempfile
import time
from ctypes import wintypes
from typing import Any, Optional


# ---------------------------------------------------------------- JSON 读写
def atomic_write_json(path: str, data: Any) -> None:
    """先写 .tmp 再原子替换，防止文件损坏。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def read_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ---------------------------------------------------------------- Key 脱敏
def mask_key(key: Optional[str]) -> str:
    """日志中永不出现明文 Key：sk-****abcd。"""
    if not key:
        return "(空)"
    key = key.strip()
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}-****{key[-4:]}"


# ---------------------------------------------------------------- Windows DPAPI
if sys.platform == "win32":
    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    def _blob_to_bytes(blob) -> bytes:
        return ctypes.string_at(blob.pbData, blob.cbData)

    def _bytes_to_blob(data: bytes):
        buf = ctypes.create_string_buffer(data, len(data))
        blob = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        return blob

    def _dpapi_protect(data: bytes) -> Optional[bytes]:
        try:
            in_blob = _bytes_to_blob(data)
            out_blob = _DataBlob()
            ok = _crypt32.CryptProtectData(
                ctypes.byref(in_blob), None, None, None, None, 0,
                ctypes.byref(out_blob))
            if not ok:
                return None
            result = _blob_to_bytes(out_blob)
            _kernel32.LocalFree(out_blob.pbData)
            return result
        except Exception:
            return None

    def _dpapi_unprotect(data: bytes) -> Optional[bytes]:
        try:
            in_blob = _bytes_to_blob(data)
            out_blob = _DataBlob()
            ok = _crypt32.CryptUnprotectData(
                ctypes.byref(in_blob), None, None, None, None, 0,
                ctypes.byref(out_blob))
            if not ok:
                return None
            result = _blob_to_bytes(out_blob)
            _kernel32.LocalFree(out_blob.pbData)
            return result
        except Exception:
            return None
else:
    def _dpapi_protect(data: bytes) -> Optional[bytes]:
        return None

    def _dpapi_unprotect(data: bytes) -> Optional[bytes]:
        return None


def encrypt_secret(plain: str) -> str:
    """加密 API Key。优先 DPAPI（与本机用户绑定）；失败则退化为 base64 混淆。"""
    if not plain:
        return ""
    raw = plain.encode("utf-8")
    enc = _dpapi_protect(raw)
    if enc is not None:
        return "dpapi:" + base64.b64encode(enc).decode("ascii")
    return "b64:" + base64.b64encode(raw).decode("ascii")


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        if token.startswith("dpapi:"):
            raw = _dpapi_unprotect(base64.b64decode(token[6:]))
            if raw is None:
                return ""
            return raw.decode("utf-8")
        if token.startswith("b64:"):
            return base64.b64decode(token[4:]).decode("utf-8")
        # 兼容历史明文
        return token
    except Exception:
        return ""


# ---------------------------------------------------------------- 时间
def now_ts() -> int:
    return int(time.time())


def parse_hhmm(text: str) -> Optional[tuple]:
    try:
        hh, mm = text.strip().split(":")
        h, m = int(hh), int(mm)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except Exception:
        pass
    return None
