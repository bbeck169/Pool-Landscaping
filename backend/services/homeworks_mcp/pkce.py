"""Feb-2026 · PKCE (RFC 7636) helpers for the Homeworks OAuth flow.

Homeworks' authorization server advertises ``code_challenge_methods_supported:
["S256"]`` and ``token_endpoint_auth_methods_supported: ["none"]`` — i.e.
public client + PKCE required. This module owns the tiny amount of code
needed to (1) generate a compliant verifier, (2) derive the S256
challenge, (3) constant-time compare on callback.

Keep this file dependency-free (stdlib only) — it is imported both by
the FastAPI request path and by the one-shot DCR script and must be
safe to unit-test in isolation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# RFC 7636 §4.1: code_verifier is 43-128 chars from the unreserved set.
# 64 chars → 384 bits of entropy → comfortably above any published guidance.
_VERIFIER_LEN = 64


def generate_verifier(length: int = _VERIFIER_LEN) -> str:
    """Return a URL-safe verifier of ``length`` chars.

    The verifier MUST be from the unreserved character set
    ``[A-Z] / [a-z] / [0-9] / "-" / "." / "_" / "~"`` per RFC 7636 §4.1.
    ``secrets.token_urlsafe`` produces ``[A-Z] / [a-z] / [0-9] / "-" / "_"``
    which is a strict subset — safe.
    """
    if not 43 <= length <= 128:
        raise ValueError("PKCE verifier must be 43-128 chars")
    # `token_urlsafe(n)` returns ceil(n * 4 / 3) chars — request enough
    # raw bytes then slice down to the exact requested length so callers
    # get a deterministic-length string.
    raw_bytes = length  # 1 byte ≈ 1.33 urlsafe char; over-request is fine.
    return secrets.token_urlsafe(raw_bytes)[:length]


def challenge_from_verifier(verifier: str) -> str:
    """Return ``BASE64URL(SHA256(verifier))`` with no ``=`` padding.

    This is the S256 method from RFC 7636 §4.2. The trailing ``=`` pad
    MUST be stripped per §4.2 last paragraph.
    """
    if not isinstance(verifier, str) or not verifier:
        raise ValueError("verifier must be a non-empty string")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def constant_time_equals(a: str, b: str) -> bool:
    """Constant-time string compare — for ``state`` nonce checks on
    the OAuth callback. Wrapper around :func:`hmac.compare_digest`
    kept in this module so callers don't sprinkle ``hmac`` imports."""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
