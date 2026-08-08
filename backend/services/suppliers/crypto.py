"""Phase 54a · Feb-2026 — Fernet crypto helpers for supplier credentials.

Distinct key namespace from the MCP OAuth Fernet key so a leak in one
domain doesn't compromise the other. Follows the same env-first /
file-fallback / generate-and-persist strategy as
``services/mcp_oauth_client.py`` — mature pattern, well-tested.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from config import logger

_KEY_FILE = Path("/app/memory/supplier_credentials.key")
_ENV_VAR = "SUPPLIER_CREDENTIAL_ENCRYPTION_KEY"
_FERNET: Optional[Fernet] = None


def _load_or_create_key() -> bytes:
    env_key = os.environ.get(_ENV_VAR, "").strip()
    if env_key:
        return env_key.encode()
    if _KEY_FILE.is_file():
        return _KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    try:
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_bytes(key)
        logger.warning(
            "[suppliers] %s not set — generated a new Fernet key and "
            "persisted to %s. Set the env var in production.",
            _ENV_VAR, _KEY_FILE)
    except Exception as e:  # pragma: no cover — filesystem edge case
        logger.error("[suppliers] could not persist Fernet key: %s", e)
    return key


def _fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(_load_or_create_key())
    return _FERNET


def encrypt(text: Optional[str]) -> Optional[str]:
    if text is None or text == "":
        return None
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(cipher: Optional[str]) -> Optional[str]:
    if cipher is None or cipher == "":
        return None
    try:
        return _fernet().decrypt(cipher.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.warning("[suppliers] failed to decrypt credential — key mismatch?")
        return None
