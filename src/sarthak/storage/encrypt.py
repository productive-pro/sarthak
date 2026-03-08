"""
Sarthak AI — AES-GCM encryption/decryption.
Pure functions. Key sourced from ~/.sarthak_ai/master.key.
Each record gets a fresh random 96-bit nonce prepended to ciphertext.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_MASTER_KEY_FILE = Path.home() / ".sarthak_ai" / "master.key"


def get_master_key_b64() -> str:
    """Return base64 master key from ~/.sarthak_ai/master.key."""
    if not _MASTER_KEY_FILE.exists():
        raise ValueError(
            "Master key not found at ~/.sarthak_ai/master.key. "
            "Run the install script to generate it."
        )
    raw = _MASTER_KEY_FILE.read_text().strip()
    if not raw:
        raise ValueError(
            "Master key file is empty at ~/.sarthak_ai/master.key. "
            "Run the install script to regenerate it."
        )
    return raw


def _get_key() -> bytes:
    """Return 32-byte AES key from master.key. Raises if missing."""
    raw = get_master_key_b64()
    key = base64.b64decode(raw)
    if len(key) not in (16, 24, 32):
        raise ValueError(f"Key must be 16/24/32 bytes, got {len(key)}")
    return key


def encrypt(data: str | bytes | dict[str, Any], fmt: str = "bytes") -> str | bytes:
    """Unified encryption entry point. fmt can be 'bytes', 'b64', or 'prefixed'."""
    if isinstance(data, dict):
        plaintext = json.dumps(data, default=str).encode()
    elif isinstance(data, str):
        plaintext = data.encode()
    else:
        plaintext = data

    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)
    blob = nonce + ciphertext

    if fmt == "b64":
        return base64.b64encode(blob).decode()
    if fmt == "prefixed":
        return "ENC:" + base64.b64encode(blob).decode()
    return blob


def decrypt(data: str | bytes, fmt: str = "bytes") -> str | bytes | dict[str, Any]:
    """Unified decryption entry point. Handles 'ENC:' prefix automatically."""
    if isinstance(data, str):
        if data.startswith("ENC:"):
            data = data[4:]
        blob = base64.b64decode(data)
    else:
        blob = data

    key = _get_key()
    aesgcm = AESGCM(key)
    nonce, ciphertext = blob[:12], blob[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)

    if fmt == "json":
        return json.loads(plaintext)
    if fmt == "str":
        return plaintext.decode()
    return plaintext


# Compatibility aliases for existing DB/Config code
def encrypt_payload(d: str | bytes | dict) -> bytes:
    return encrypt(d, "bytes")  # type: ignore[return-value]

def decrypt_payload(b: str | bytes) -> dict:
    return decrypt(b, "json")  # type: ignore[return-value]

def encrypt_b64(d: str | bytes | dict) -> str:
    return encrypt(d, "b64")  # type: ignore[return-value]

def decrypt_b64(s: str | bytes) -> dict:
    return decrypt(s, "json")  # type: ignore[return-value]

def encrypt_string(s: str) -> str:
    return encrypt(s, "prefixed")  # type: ignore[return-value]

def decrypt_string(s: str) -> str:
    return decrypt(s, "str")  # type: ignore[return-value]
