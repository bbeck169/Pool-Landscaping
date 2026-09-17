"""Sep-2026 · Per-tenant DFS credentials · Fernet-based secret crypto.

Fernet symmetric encryption with a project-wide key at
``TENANT_SECRETS_ENC_KEY`` (base64 URL-safe, 32 bytes = 44 chars).

Design contract:
  • Every plaintext write goes through :func:`encrypt_tenant_secret`.
  • Every read goes through :func:`decrypt_tenant_secret` — which
    returns ``None`` on any failure (missing key, tampered
    ciphertext, decode error). Callers MUST fall through to the
    global env or a mocked state rather than crashing.
  • Missing ``TENANT_SECRETS_ENC_KEY`` disables the feature: any
    ``encrypt_tenant_secret`` call raises ``RuntimeError`` (write
    path fails loudly), and every decrypt returns ``None``
    (read path degrades). Startup logs a single WARNING telling
    ops what to set.

Never log ciphertext or plaintext. Never emit either through an
API response — masked-view only.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("tenant_secrets_crypto")

_ENV_VAR = "TENANT_SECRETS_ENC_KEY"

# Module-level flag so callers can short-circuit without triggering
# a warning log every single call.
_KEY_MISSING_LOGGED = False


def _get_fernet():
    """Lazy-import cryptography so environments without the package
    (dev pods that never touch this code) don't force the dep."""
    from cryptography.fernet import Fernet, InvalidToken  # noqa: F401
    raw = os.environ.get(_ENV_VAR, "").strip()
    if not raw:
        return None
    try:
        return Fernet(raw.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[tenant_secrets_crypto] %s is set but invalid "
            "(expect a 44-char base64 Fernet key): %s",
            _ENV_VAR, exc,
        )
        return None


def is_available() -> bool:
    """Public predicate: True when the encryption key is set and
    valid. Called at startup + before write-path endpoints."""
    return _get_fernet() is not None


def encrypt_tenant_secret(plaintext: str) -> str:
    """Return Fernet ciphertext (base64 URL-safe string).

    Raises ``RuntimeError`` if the encryption key isn't configured —
    the caller should catch this and return an HTTP 503 telling ops
    to set ``TENANT_SECRETS_ENC_KEY``. Never silently store
    plaintext.
    """
    f = _get_fernet()
    if f is None:
        raise RuntimeError(
            f"{_ENV_VAR} is not configured — per-tenant secret storage "
            "is disabled. Set the env var to a 44-char Fernet key "
            "(python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())')."
        )
    if not isinstance(plaintext, str) or not plaintext:
        raise ValueError("encrypt_tenant_secret requires a non-empty string")
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_tenant_secret(ciphertext: Optional[str]) -> Optional[str]:
    """Return the decrypted plaintext, or ``None`` on any failure.

    Graceful degradation is the point — a tampered / corrupted /
    key-missing state falls through to the global env fallback in
    higher-order helpers rather than crashing the request.
    """
    global _KEY_MISSING_LOGGED
    if not ciphertext:
        return None
    f = _get_fernet()
    if f is None:
        if not _KEY_MISSING_LOGGED:
            logger.warning(
                "[tenant_secrets_crypto] %s not configured — tenant "
                "credentials cannot be decrypted; falling through to "
                "global env fallback. Set the env var to enable "
                "per-tenant secret decryption.", _ENV_VAR,
            )
            _KEY_MISSING_LOGGED = True
        return None
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        # Do NOT log the ciphertext or a hint of its shape — attacker
        # could learn from log noise. Log only the failure class.
        logger.warning(
            "[tenant_secrets_crypto] decrypt failed (%s) — treating as "
            "tampered/invalid, returning None.", type(exc).__name__,
        )
        return None


def log_startup_state() -> None:
    """Emit exactly one INFO/WARNING at server boot so ops see the
    feature-availability state without spamming later."""
    if is_available():
        logger.info(
            "[tenant_secrets_crypto] %s configured — per-tenant DFS "
            "secret storage ENABLED.", _ENV_VAR,
        )
    else:
        logger.warning(
            "[tenant_secrets_crypto] %s not configured — per-tenant "
            "DFS credential storage is DISABLED. Global env fallback "
            "still works. Set the env var to enable BYO DFS accounts.",
            _ENV_VAR,
        )
