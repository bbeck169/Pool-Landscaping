"""QuoteIQ Q3-follow-up · Q2 real-LLM hardening tests.

Exercises the retry + catalog-fallback logic in ``services/ai_estimator.py``.
Uses the ``prime_test_mocks(...)`` helper so we can force $0 responses
deterministically without burning real-LLM quota.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
from dotenv import load_dotenv
load_dotenv(BACKEND_ROOT / ".env")
os.environ["TEST_LLM_MOCK"] = "1"

from services.ai_estimator import (
    generate_estimate, prime_test_mocks, clear_test_mocks,
)


BAD_LINEAR = {
    "line_items": [
        {"sku": None, "service_slug": None,
          "description": "TEST_ bad zero-qty line",
          "qty": 0, "unit": "each", "unit_price_cents": 5000,
          "source": "ai_inferred", "confidence": 0.8},
    ],
    "notes": "This response is bad on purpose.",
}
GOOD_LINEAR = {
    "line_items": [
        {"sku": "SVC-WKLY", "service_slug": "weekly_service",
          "description": "TEST_ good line",
          "qty": 4, "unit": "visit", "unit_price_cents": 12500,
          "source": "catalog", "confidence": 0.95},
    ],
    "notes": "Retry succeeded.",
}


@pytest.fixture(autouse=True)
def _clean():
    clear_test_mocks()
    yield
    clear_test_mocks()


@pytest.fixture
def tenant_id():
    """Pick any real tenant from the seeded DB. This test suite talks
    to the DB directly (via the service function) rather than the HTTP
    layer, so we need a real tenant_id for the catalog lookup."""
    from config import db as _db
    from motor.motor_asyncio import AsyncIOMotorClient  # noqa: F401
    async def _pick():
        row = await _db.tenants.find_one({}, {"id": 1})
        return row["id"] if row else "seed"
    return asyncio.get_event_loop().run_until_complete(_pick())


class TestZeroTotalRetry:
    def test_retry_fires_when_first_response_has_zero(self, tenant_id):
        # Queue: 1st bad, 2nd good.
        prime_test_mocks(BAD_LINEAR, GOOD_LINEAR)
        result = asyncio.get_event_loop().run_until_complete(
            generate_estimate(
                tenant_id=tenant_id, photo_urls=[],
                job_description="TEST_ hardening retry linear",
                options_mode=False,
            )
        )
        assert result.get("_meta", {}).get("retries") == 1
        assert result["_meta"]["path"] == "mock_retry_ok"
        # All line items positive.
        for li in result["line_items"]:
            assert li["qty"] > 0
            assert li["unit_price_cents"] > 0
            assert li["subtotal_cents"] > 0

    def test_catalog_fallback_when_retry_also_zero(self, tenant_id):
        # Force TWO consecutive $0 responses → fallback path fires.
        # We arrange the first bad response to contain ONE catalog line
        # (so the fallback has something to keep) and one $0 line.
        bad_with_catalog = {
            "line_items": [
                {"sku": "SVC-WKLY", "service_slug": "weekly_service",
                  "description": "TEST_ good catalog line",
                  "qty": 2, "unit": "visit", "unit_price_cents": 12500,
                  "source": "catalog", "confidence": 0.95},
                {"sku": None, "service_slug": None,
                  "description": "TEST_ bad zero-total line",
                  "qty": 0, "unit": "each", "unit_price_cents": 5000,
                  "source": "ai_inferred", "confidence": 0.8},
            ],
            "notes": "Mix of catalog + zero.",
        }
        prime_test_mocks(bad_with_catalog, BAD_LINEAR)
        result = asyncio.get_event_loop().run_until_complete(
            generate_estimate(
                tenant_id=tenant_id, photo_urls=[],
                job_description="TEST_ hardening catalog fallback",
                options_mode=False,
            )
        )
        assert result["_meta"]["path"] == "catalog_fallback"
        # No $0 line should have survived.
        for li in result["line_items"]:
            assert li["qty"] > 0
            assert li["unit_price_cents"] > 0
            assert li["subtotal_cents"] > 0
            # Only catalog lines survive fallback.
            assert li["source"] == "catalog"
