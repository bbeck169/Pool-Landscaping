"""Feb-2026 · Soshie · Brand-brain website ingest tests.

The crawler is exercised via the pure ``parse_page`` +
``distill_bullets`` + ``_merge_into_brand_brain`` helpers.  We
DO NOT hit the network in tests — the HTTP fetch is covered
by ``services.seo_scanner.fetch_page`` (its own test suite).

Test surface:
    1. ``parse_page`` extracts title/h1/h2s and CTA texts.
    2. ``distill_bullets`` produces bullet list with expected shape.
    3. ``_merge_into_brand_brain`` is APPEND-ONLY and dedup-safe.
    4. Second ingest run with same content adds nothing new.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync = _shared_client()
_db = _shared_db()
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


_HOME_HTML = b"""<!doctype html>
<html><head><title>Vistancia Pool &amp; Landscaping</title></head>
<body>
  <nav>
    <ul>
      <li><a href="/pool-service">Pool Service</a></li>
      <li><a href="/landscape-design">Landscape Design</a></li>
      <li><a href="/pool-repair">Pool Repair</a></li>
      <li><a href="/about">About</a></li>
    </ul>
  </nav>
  <h1>Family-Owned Pool + Landscape Care</h1>
  <h2>Weekly Pool Service</h2>
  <p>We service more than 400 pools every week across Vistancia,
     Peoria, and Sun City West. Our techs are all EPA-certified.</p>
  <h2>Why Homeowners Choose Us</h2>
  <p>About us: A family-owned business serving the Northwest
     Valley since 2019.</p>
  <a href="/contact" class="btn">Get a quote</a>
  <button>Book Now</button>
</body></html>
"""


def test_parse_page_extracts_title_h1_h2s_and_ctas():
    from services.soshie.brand_ingest import parse_page
    parsed = parse_page(_HOME_HTML, "https://example.com/")
    assert "Vistancia Pool" in parsed["title"]
    assert parsed["h1"].startswith("Family-Owned")
    assert "Weekly Pool Service" in parsed["h2s"]
    assert "Why Homeowners Choose Us" in parsed["h2s"]
    assert "Get a quote" in parsed["cta_texts"]
    assert "Book Now" in parsed["cta_texts"]
    # Service hints from nav.
    assert "Pool Service" in parsed["service_hints"]
    assert "Landscape Design" in parsed["service_hints"]


def test_distill_bullets_produces_expected_shape():
    from services.soshie.brand_ingest import parse_page, distill_bullets
    parsed = parse_page(_HOME_HTML, "https://example.com/")
    bullets = distill_bullets([parsed])
    # Expect at least: service bullet + about bullet + CTA bullet.
    assert any(b.startswith("We offer:") for b in bullets)
    assert any(b.startswith("About:") for b in bullets)
    assert any(b.startswith("CTA style:") for b in bullets)


def test_merge_into_brand_brain_is_append_only_dedup_safe():
    from services.soshie.brand_ingest import _merge_into_brand_brain
    tid = f"TEST-ingest-{uuid.uuid4().hex[:6]}"
    try:
        # Seed existing talking_points on the tenant.
        _db.brand_brain.insert_one({
            "tenant_id": tid,
            "talking_points": ["Existing bullet 1", "EPA certified"],
        })
        r1 = _run(_merge_into_brand_brain(
            tid, ["New bullet A", "existing bullet 1", "EPA certified",
                     "New bullet B"]))
        assert r1["added"] == 2, r1  # dedup collapsed the 2 duplicates
        row = _db.brand_brain.find_one({"tenant_id": tid})
        # Existing preserved AND new appended (append-only).
        assert "Existing bullet 1" in row["talking_points"]
        assert "New bullet A" in row["talking_points"]
        assert "New bullet B" in row["talking_points"]
        # Second run with the SAME set adds nothing.
        r2 = _run(_merge_into_brand_brain(
            tid, ["New bullet A", "New bullet B"]))
        assert r2["added"] == 0
    finally:
        _db.brand_brain.delete_many({"tenant_id": tid})


def test_merge_creates_row_when_brand_brain_missing():
    from services.soshie.brand_ingest import _merge_into_brand_brain
    tid = f"TEST-ingest-{uuid.uuid4().hex[:6]}"
    try:
        r = _run(_merge_into_brand_brain(tid, ["seeded bullet"]))
        assert r["added"] == 1
        row = _db.brand_brain.find_one({"tenant_id": tid})
        assert row is not None
        assert "seeded bullet" in row["talking_points"]
    finally:
        _db.brand_brain.delete_many({"tenant_id": tid})
