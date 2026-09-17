"""Sep-2026 · Per-tenant DFS creds · Priority resolution.

Order: **tenant → global → None**. Verifies:
  • Tenant creds present + valid → source="tenant".
  • Tenant creds missing, global set → source="global".
  • Both missing → None.
  • Tenant ciphertext tampered → falls through to global.
"""
from __future__ import annotations

import os
from unittest.mock import patch


def _tenant_with_dfs(login_ct: str, password_ct: str) -> dict:
    return {
        "id": "t-priority",
        "settings": {
            "integrations": {
                "dataforseo": {
                    "login_encrypted":    login_ct,
                    "password_encrypted": password_ct,
                }
            }
        },
    }


def test_tenant_creds_win_over_global():
    from services.dataforseo_client import (
        get_effective_credentials, get_credentials_for_tenant,
    )
    from services.tenant_secrets_crypto import encrypt_tenant_secret

    tenant = _tenant_with_dfs(
        encrypt_tenant_secret("byo@example.com"),
        encrypt_tenant_secret("byo-secret-pw"),
    )
    with patch.dict(os.environ, {
        "DATAFORSEO_LOGIN":    "global@platform.com",
        "DATAFORSEO_PASSWORD": "global-secret",
    }):
        creds = get_credentials_for_tenant(tenant)
        assert creds == ("byo@example.com", "byo-secret-pw")
        eff = get_effective_credentials(tenant)
        assert eff == ("byo@example.com", "byo-secret-pw", "tenant"), eff


def test_missing_tenant_creds_falls_to_global():
    from services.dataforseo_client import get_effective_credentials

    tenant = {"id": "t-no-byo", "settings": {}}
    with patch.dict(os.environ, {
        "DATAFORSEO_LOGIN":    "global@platform.com",
        "DATAFORSEO_PASSWORD": "global-secret",
    }):
        eff = get_effective_credentials(tenant)
        assert eff == ("global@platform.com", "global-secret", "global"), eff


def test_both_missing_returns_none():
    from services.dataforseo_client import get_effective_credentials

    tenant = {"id": "t-empty", "settings": {}}
    with patch.dict(os.environ, {"DATAFORSEO_LOGIN": "",
                                    "DATAFORSEO_PASSWORD": ""}):
        assert get_effective_credentials(tenant) is None


def test_tampered_tenant_ciphertext_falls_to_global():
    from services.dataforseo_client import get_effective_credentials

    tenant = _tenant_with_dfs(
        "gAAAAA_TAMPERED_" + "x" * 40,
        "gAAAAA_TAMPERED_" + "x" * 40,
    )
    with patch.dict(os.environ, {
        "DATAFORSEO_LOGIN":    "global@platform.com",
        "DATAFORSEO_PASSWORD": "global-secret",
    }):
        eff = get_effective_credentials(tenant)
        assert eff is not None
        assert eff[2] == "global", (
            "Tampered tenant ciphertext must fall through to global, "
            "not return the corrupted plaintext."
        )


def test_missing_tenant_ct_and_no_global_returns_none():
    from services.dataforseo_client import get_effective_credentials

    tenant = {"id": "t-nothing", "settings": {"integrations": {}}}
    with patch.dict(os.environ, {"DATAFORSEO_LOGIN": "",
                                    "DATAFORSEO_PASSWORD": ""}):
        assert get_effective_credentials(tenant) is None


def test_partial_tenant_creds_falls_to_global():
    """Login stored but password missing → tenant path returns None
    → falls to global. Corrupt-half state can't accidentally leak."""
    from services.dataforseo_client import get_effective_credentials
    from services.tenant_secrets_crypto import encrypt_tenant_secret

    tenant = {
        "id": "t-half",
        "settings": {
            "integrations": {
                "dataforseo": {
                    "login_encrypted": encrypt_tenant_secret("only-login@x.com"),
                    # ``password_encrypted`` intentionally missing.
                }
            }
        },
    }
    with patch.dict(os.environ, {
        "DATAFORSEO_LOGIN":    "global@platform.com",
        "DATAFORSEO_PASSWORD": "global-secret",
    }):
        eff = get_effective_credentials(tenant)
        assert eff is not None and eff[2] == "global"
