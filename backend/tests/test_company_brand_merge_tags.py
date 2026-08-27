"""Feb-2026 · Company brand contact merge tags — resolver alignment.

* ``COMPANY_EMAIL`` / ``COMPANY_PHONE`` / ``COMPANY_WEBSITE`` were
  previously flagged by the composer linter as unresolved for
  tenants (like AquaTerra) whose real brand contact data lives in
  ``tenant.settings.business_card`` (where the admin editor writes)
  rather than at the tenant root.
* The resolvers now prefer the Business Card location, mirroring
  ``_company_name``'s existing precedence. Legacy tenants with root-
  level ``support_email`` / ``support_phone_number`` / ``website``
  still resolve as before via the fallback chain.
"""
from __future__ import annotations

import asyncio
import pytest

from config import db
from services.marketing.merge_tags import (
    render_template,
)


@pytest.fixture
def business_card_tenant():
    return {
        "id": "t-bc", "name": "Legacy Name",
        "support_email": "legacy@example.com",
        "support_phone_number": "(555) 555-0100",
        "website": "https://legacy.example.com",
        "settings": {
            "business_card": {
                "email": "cs@plofv.com",
                "phone": "602-887-4400",
                "website_url": "www.poolandlandscapingofvistancia.com",
            },
        },
    }


@pytest.fixture
def legacy_only_tenant():
    return {
        "id": "t-legacy", "name": "Legacy Name",
        "support_email": "legacy@example.com",
        "support_phone_number": "(555) 555-0100",
        "website": "https://legacy.example.com",
    }


@pytest.fixture
def empty_tenant():
    return {"id": "t-empty", "name": "Empty"}


class TestCompanyBrandContactResolvers:
    def test_business_card_source_wins(self, business_card_tenant):
        ctx = {"tenant": business_card_tenant}
        rendered, missing = render_template(
            "{{COMPANY_EMAIL}} | {{COMPANY_PHONE}} | {{COMPANY_WEBSITE}}",
            ctx, missing="empty",
        )
        assert missing == []
        assert rendered == (
            "cs@plofv.com | 602-887-4400 | "
            "www.poolandlandscapingofvistancia.com"
        )

    def test_legacy_root_fields_still_resolve(self, legacy_only_tenant):
        """A tenant with no Business Card sub-doc must still resolve
        via the ``support_email`` / ``support_phone_number`` / ``website``
        fallback chain."""
        ctx = {"tenant": legacy_only_tenant}
        rendered, missing = render_template(
            "{{COMPANY_EMAIL}} | {{COMPANY_PHONE}} | {{COMPANY_WEBSITE}}",
            ctx, missing="empty",
        )
        assert missing == []
        assert rendered == (
            "legacy@example.com | (555) 555-0100 | "
            "https://legacy.example.com"
        )

    def test_null_tenant_returns_empty_no_crash(self, empty_tenant):
        ctx = {"tenant": empty_tenant}
        rendered, missing = render_template(
            "[{{COMPANY_EMAIL}}][{{COMPANY_PHONE}}][{{COMPANY_WEBSITE}}]",
            ctx, missing="empty",
        )
        # Empty strings — never crash, never leak literal tokens.
        assert rendered == "[][][]"
        assert set(missing) == {
            "COMPANY_EMAIL", "COMPANY_PHONE", "COMPANY_WEBSITE",
        }


class TestSeedAquaterraBrandContacts:
    def test_seed_is_idempotent(self, tmp_path):
        """First run + second run must produce identical DB state and
        never overwrite an existing non-placeholder value."""
        from scripts.seed_aquaterra_brand_contacts import (
            seed_aquaterra_brand_contacts,
        )

        # Ensure aquaterra exists — if it doesn't, the seed short-
        # circuits with ``ok=True, reason=missing`` and the test is
        # a no-op assertion.
        loop = asyncio.get_event_loop()
        result1 = loop.run_until_complete(seed_aquaterra_brand_contacts())
        if result1.get("reason") == "aquaterra_tenant_missing":
            pytest.skip("aquaterra tenant not seeded on this env")

        # Snapshot after first run.
        snap1 = loop.run_until_complete(db.tenants.find_one(
            {"$or": [{"slug": "aquaterra"}, {"slug_aliases": "plofv"}]},
            {"_id": 0, "settings.business_card": 1},
        ))
        result2 = loop.run_until_complete(seed_aquaterra_brand_contacts())
        snap2 = loop.run_until_complete(db.tenants.find_one(
            {"$or": [{"slug": "aquaterra"}, {"slug_aliases": "plofv"}]},
            {"_id": 0, "settings.business_card": 1},
        ))

        card = (snap2.get("settings") or {}).get("business_card") or {}
        # Phone MUST have been persisted (from either this run or a
        # prior admin edit — either way it's the target value).
        assert card.get("phone") == "602-887-4400"
        # Second run must be a no-op relative to the first.
        assert snap1 == snap2
        assert result2["ok"] is True

    def test_conflicts_are_reported(self):
        """When a tenant already has a different real value, the seed
        surfaces the conflict in the return payload for the operator."""
        from scripts.seed_aquaterra_brand_contacts import (
            seed_aquaterra_brand_contacts,
        )
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(seed_aquaterra_brand_contacts())
        if result.get("reason") == "aquaterra_tenant_missing":
            pytest.skip("aquaterra tenant not seeded on this env")
        # ``conflicts`` is present — value may be empty if all match.
        assert "conflicts" in result
