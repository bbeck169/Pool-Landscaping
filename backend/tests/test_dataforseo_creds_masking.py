"""Sep-2026 · Per-tenant DFS creds · masking helper coverage.

Direct-unit tests on :func:`_mask_login` for edge cases.
"""
from __future__ import annotations


def test_mask_typical_email():
    from routers.tenant_dataforseo_integration import _mask_login
    assert _mask_login("brian@plofv.com") == "bri***@plofv.com"


def test_mask_short_local_part_masks_entirely():
    from routers.tenant_dataforseo_integration import _mask_login
    assert _mask_login("bo@x.com") == "***@x.com"
    assert _mask_login("a@example.com") == "***@example.com"


def test_mask_exact_3_chars_local_part():
    from routers.tenant_dataforseo_integration import _mask_login
    # Exactly 3 chars — the guard is <= 3 so this masks entirely.
    assert _mask_login("bob@example.com") == "***@example.com"


def test_mask_no_at_returns_wildcard():
    from routers.tenant_dataforseo_integration import _mask_login
    assert _mask_login("not-an-email") == "***"


def test_mask_empty_returns_wildcard():
    from routers.tenant_dataforseo_integration import _mask_login
    assert _mask_login("") == "***"
    assert _mask_login(None) == "***"


def test_mask_long_local_part():
    from routers.tenant_dataforseo_integration import _mask_login
    assert _mask_login("very-long-local-part@example.com") == \
        "ver***@example.com"


def test_mask_preserves_domain_verbatim():
    from routers.tenant_dataforseo_integration import _mask_login
    assert _mask_login("user@sub.corp-domain.co.uk") == \
        "use***@sub.corp-domain.co.uk"
