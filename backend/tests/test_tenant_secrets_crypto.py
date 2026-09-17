"""Sep-2026 · Per-tenant DFS secrets · Fernet crypto helper.

Roundtrip works, tamper detected, missing key degrades gracefully.
"""
from __future__ import annotations

import os
from unittest.mock import patch


def test_encrypt_then_decrypt_roundtrip():
    from services.tenant_secrets_crypto import (
        encrypt_tenant_secret, decrypt_tenant_secret, is_available,
    )
    assert is_available()
    ct = encrypt_tenant_secret("brian@plofv.com")
    assert ct.startswith("gAAAAA"), ct
    assert decrypt_tenant_secret(ct) == "brian@plofv.com"


def test_decrypt_tampered_ciphertext_returns_none():
    from services.tenant_secrets_crypto import (
        encrypt_tenant_secret, decrypt_tenant_secret,
    )
    ct = encrypt_tenant_secret("secret-password")
    # Flip a middle character to invalidate the HMAC.
    mid = len(ct) // 2
    tampered = ct[:mid] + ("X" if ct[mid] != "X" else "Y") + ct[mid + 1:]
    assert decrypt_tenant_secret(tampered) is None


def test_missing_key_disables_write_path():
    from services import tenant_secrets_crypto as tsc
    with patch.dict(os.environ, {"TENANT_SECRETS_ENC_KEY": ""}, clear=False):
        assert not tsc.is_available()
        try:
            tsc.encrypt_tenant_secret("x")
            assert False, "encrypt MUST raise when key missing"
        except RuntimeError as exc:
            assert "TENANT_SECRETS_ENC_KEY" in str(exc)


def test_missing_key_decrypt_returns_none_not_crash():
    from services import tenant_secrets_crypto as tsc
    with patch.dict(os.environ, {"TENANT_SECRETS_ENC_KEY": ""}, clear=False):
        # Even a well-formed Fernet token can't be decrypted without
        # the key — must return None, never raise.
        assert tsc.decrypt_tenant_secret("gAAAAAAAAAAAAAAAAAAAAAAAAAAA") is None


def test_invalid_key_format_disables_gracefully():
    from services import tenant_secrets_crypto as tsc
    with patch.dict(os.environ,
                       {"TENANT_SECRETS_ENC_KEY": "not-a-valid-fernet-key"},
                       clear=False):
        assert not tsc.is_available()
        assert tsc.decrypt_tenant_secret("gAAAAAAAAAAAAAAAAAAAAAAAAAAA") is None


def test_empty_ciphertext_returns_none_without_calling_fernet():
    from services.tenant_secrets_crypto import decrypt_tenant_secret
    assert decrypt_tenant_secret("") is None
    assert decrypt_tenant_secret(None) is None
