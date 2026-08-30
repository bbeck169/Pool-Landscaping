"""Feb-2026 · Soshie · SEO-context grounding tests.

Covers ``services.soshie.seo_context.build_seo_context`` — the
compact <2 KB blob Soshie's dispatch prepends to system prompts.

Test surface:
    1. Empty tenant → returns {}.
    2. Seeded scan → surfaces url/score/aeo_score.
    3. AEO gaps sort newest-first + cap at 5.
    4. Rank movers computed as (oldest - newest) rank delta.
    5. Prompt formatter safely renders empty context.
    6. Budget fitter keeps payload under 2 KB.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@pytest.fixture
def tenant_id():
    tid = f"TEST-seo-ctx-{uuid.uuid4().hex[:6]}"
    yield tid
    _db.seo_scans.delete_many({"tenant_id": tid})
    _db.aeo_fixes.delete_many({"tenant_id": tid})
    _db.rank_snapshots.delete_many({"tenant_id": tid})
    _db.brand_mentions.delete_many({"tenant_id": tid})
    _db.keyword_lookups.delete_many({"tenant_id": tid})


def test_empty_tenant_returns_empty_dict(tenant_id):
    from services.soshie.seo_context import build_seo_context
    ctx = _run(build_seo_context(tenant_id))
    assert ctx == {}


def test_latest_scan_summary_present(tenant_id):
    from utils import new_id, now_iso
    from services.soshie.seo_context import build_seo_context
    _db.seo_scans.insert_one({
        "id": new_id(), "tenant_id": tenant_id,
        "target_url": "https://example.com",
        "status": "complete",
        "finished_at": now_iso(),
        "results": {
            "score": 78, "issue_count": {"critical": 1, "minor": 4},
            "aeo_signals": {"overall_aeo_score": 62},
        },
    })
    ctx = _run(build_seo_context(tenant_id))
    assert ctx["latest_scan"]["url"] == "https://example.com"
    assert ctx["latest_scan"]["score"] == 78
    assert ctx["latest_scan"]["aeo_score"] == 62


def test_aeo_gaps_sorted_newest_first_and_capped(tenant_id):
    from utils import new_id
    from datetime import datetime, timedelta, timezone
    from services.soshie.seo_context import build_seo_context
    base = datetime.now(timezone.utc)
    # Seed 7 gaps — expect top 5 newest.
    for i in range(7):
        _db.aeo_fixes.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "kind": "schema" if i % 2 == 0 else "faq",
            "title": f"gap {i}",
            "priority": "high",
            "status": "open",
            "created_at": (base - timedelta(hours=i)).isoformat(),
        })
    ctx = _run(build_seo_context(tenant_id))
    assert len(ctx["aeo_gaps"]) == 5
    # Newest (i=0) first.
    assert ctx["aeo_gaps"][0]["title"] == "gap 0"


def test_rank_movers_compute_delta_and_pick_biggest(tenant_id):
    from utils import new_id
    from datetime import datetime, timedelta, timezone
    from services.soshie.seo_context import build_seo_context
    base = datetime.now(timezone.utc)
    # kw A: rank 3 (today) → 15 (2 days ago).  Newest = 3,
    # oldest = 15.  delta = oldest - latest = +12 (improved).
    for i, r in enumerate([3, 10, 15]):
        _db.rank_snapshots.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "keyword": "kw-a", "rank": r,
            "checked_at": (base - timedelta(days=i)).isoformat(),
        })
    # kw B: rank 8 (today) → 4 (2 days ago).  Newest = 8,
    # oldest = 4.  delta = 4 - 8 = -4 (worsened).
    for i, r in enumerate([8, 6, 4]):
        _db.rank_snapshots.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "keyword": "kw-b", "rank": r,
            "checked_at": (base - timedelta(days=i)).isoformat(),
        })
    ctx = _run(build_seo_context(tenant_id))
    movers = ctx["rank_movers"]
    # Biggest-mag first — kw-a has |delta|=12, kw-b has |delta|=4.
    assert movers[0]["keyword"] == "kw-a"
    assert movers[0]["delta"] == 12
    assert movers[0]["current"] == 3
    # kw-b second, negative delta (worsened).
    assert movers[1]["keyword"] == "kw-b"
    assert movers[1]["delta"] == -4


def test_prompt_formatter_handles_empty_context():
    from services.soshie.seo_context import format_seo_context_for_prompt
    assert format_seo_context_for_prompt({}) == ""
    assert format_seo_context_for_prompt(None) == ""


def test_prompt_formatter_renders_populated_context():
    from services.soshie.seo_context import format_seo_context_for_prompt
    text = format_seo_context_for_prompt({
        "latest_scan": {"url": "https://x.com", "score": 90,
                          "aeo_score": 70},
        "aeo_gaps": [{"kind": "schema", "title": "add LocalBusiness"}],
        "rank_movers": [{"keyword": "pool cleaning phoenix",
                           "current": 4, "delta": 3}],
        "top_mentions": [{"domain": "yelp.com", "count": 2}],
        "recent_keywords": ["pool ph", "pool salt"],
    })
    assert "https://x.com" in text
    assert "90/100" in text
    assert "add LocalBusiness" in text
    assert "pool cleaning phoenix" in text
    assert "yelp.com" in text


def test_budget_fitter_never_exceeds_2kb(tenant_id):
    """Seed a huge amount of data and confirm the return blob
    still fits under 2 KB when JSON-encoded."""
    import json
    from utils import new_id
    from datetime import datetime, timedelta, timezone
    from services.soshie.seo_context import build_seo_context
    base = datetime.now(timezone.utc)
    for i in range(50):
        _db.aeo_fixes.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "kind": "schema", "title": "x" * 100,
            "priority": "high", "status": "open",
            "created_at": (base - timedelta(minutes=i)).isoformat(),
        })
    for i in range(50):
        _db.rank_snapshots.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "keyword": f"kw-{i}", "rank": i + 1,
            "checked_at": (base - timedelta(hours=i)).isoformat(),
        })
    ctx = _run(build_seo_context(tenant_id))
    assert len(json.dumps(ctx)) <= 2000
