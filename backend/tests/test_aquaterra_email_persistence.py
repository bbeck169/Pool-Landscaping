"""Feb-2026 · P1 regression guard — AquaTerra brand-email persistence.

Before the fix, ``transfer_integrations_to_brian.py`` was overwriting
``settings.business_card.email`` back to ``brian@plofv.com`` on every
boot, undoing the ``rebrand_aquaterra_to_plofv.py`` migration's
``cs@plofv.com`` seed. This suite is a source-inspection guard that
locks in:

* ``BUSINESS_CARD["email"]`` in the rebrand migration = the customer-
  service alias.
* ``transfer_integrations_to_brian.py`` no longer mutates
  ``business_card.email`` under any code path.
* ``_BUSINESS_CARD_DEFAULTS["aquaterra"]["email"]`` matches.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def rebrand_src() -> str:
    return (BACKEND / "migrations" /
             "rebrand_aquaterra_to_plofv.py").read_text()


@pytest.fixture
def brian_src() -> str:
    return (BACKEND / "migrations" /
             "transfer_integrations_to_brian.py").read_text()


@pytest.fixture
def tenants_router_src() -> str:
    return (BACKEND / "routers" / "tenants.py").read_text()


class TestBrandEmailPersistence:
    def test_rebrand_migration_seeds_customer_service_alias(self, rebrand_src):
        """The rebrand migration's ``BUSINESS_CARD`` constant must
        carry the customer-service alias — this is what fresh
        preview DBs get on first boot."""
        # Import the module so we're checking the ACTUAL runtime
        # value, not a regex that has to navigate ``{{...}}`` merge-
        # tag placeholders inside comments.
        from migrations import rebrand_aquaterra_to_plofv as _r
        assert _r.BUSINESS_CARD.get("email") == "cs@plofv.com", (
            f"BUSINESS_CARD.email={_r.BUSINESS_CARD.get('email')!r}; "
            "expected cs@plofv.com"
        )

    def test_rebrand_migration_upgrades_legacy_email_on_boot(self, rebrand_src):
        """The rebrand migration must detect + upgrade the exact
        legacy string on every boot so preview DBs that were seeded
        with the old value get flipped without a manual op."""
        assert re.search(
            r'if\s+card\.get\(\s*"email"\s*\)\s*==\s*"brian@plofv\.com"',
            rebrand_src,
        ), "legacy-email upgrade branch missing"
        assert 'settings.business_card.email' in rebrand_src

    def test_transfer_integrations_migration_no_longer_touches_brand_email(
        self, brian_src,
    ):
        """The integrations-owner migration must NEVER write
        ``settings.business_card.email``. Prior versions did — that
        caused the boot revert loop.
        """
        # No live assignment to business_card.email in the source.
        assert re.search(
            r'card\[\s*["\']email["\']\s*\]\s*=', brian_src,
        ) is None, "business_card.email write path still present"
        assert re.search(
            r'diff\[\s*["\']business_card\.email["\']\s*\]\s*=', brian_src,
        ) is None, "business_card.email diff write still present"
        # The write to ``updates["settings.business_card"] = card`` is
        # ALSO gone (the whole card mutation block was removed).
        assert re.search(
            r'updates\[\s*["\']settings\.business_card["\']\s*\]\s*=',
            brian_src,
        ) is None, "settings.business_card write still present"

    def test_business_card_defaults_source_matches(self, tenants_router_src):
        """``_BUSINESS_CARD_DEFAULTS["aquaterra"]["email"]`` in
        ``routers/tenants.py`` must also carry ``cs@plofv.com`` so
        the ``GET /api/tenants/business-card`` fallback path returns
        the correct alias for tenants whose DB card is empty."""
        from routers.tenants import _BUSINESS_CARD_DEFAULTS
        aqua = _BUSINESS_CARD_DEFAULTS.get("aquaterra") or {}
        assert aqua.get("email") == "cs@plofv.com", (
            f"_BUSINESS_CARD_DEFAULTS[aquaterra].email={aqua.get('email')!r}"
        )
        assert aqua.get("phone") == "602-887-4400"
        assert aqua.get("website_url") == (
            "https://www.poolandlandscapingofvistancia.com/"
        )
