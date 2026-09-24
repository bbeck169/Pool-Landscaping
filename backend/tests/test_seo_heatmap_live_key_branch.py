"""Task J · Commit 5 · Feb-2026 — SEO Rank Heatmap live-key branch
regression guard.

The grep report for Task J confirmed the live-vs-mock branching in
``_generate_heatmap`` (routers/seo_agentic.py :856-872) is already
key-absence-driven — no code changes were needed. This suite locks
that contract in place so a future refactor can't silently drop
either branch.

Coverage:

  1. ``get_credentials_or_none()`` returns a 2-tuple when both env
     vars are present. Value content is never asserted (never dump
     secrets); only truthiness + type.
  2. Missing / empty ``DATAFORSEO_LOGIN`` → None (parametrised).
  3. Missing / empty ``DATAFORSEO_PASSWORD`` → None (parametrised).
  4. Both env vars missing → None (parametrised end-state).
  5. ``start_heatmap`` optimistic ``mocked`` flag matches credential
     presence at insert time — creds present → ``mocked=False`` +
     ``mocked_reason=None``; creds absent → ``mocked=True`` +
     ``mocked_reason="dataforseo_not_configured"``.
  6. ``_generate_heatmap`` branch selection · creds present → calls
     ``_dfs.serp_google_organic_live`` (live path).
  7. ``_generate_heatmap`` branch selection · creds absent → calls
     ``_write_mocked_heatmap`` with
     ``reason="dataforseo_not_configured"`` (mock path).
  8. Fallback preservation — grep-based static assertion that the
     ``_write_mocked_heatmap(...reason="dataforseo_not_configured"...)``
     call is still in the router source. Locks the "do NOT delete
     the synthesized fallback silently" contract from the brief.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient


# ── Path bootstrap so ``routers.seo_agentic`` imports ─────────────
_BACKEND = Path(__file__).resolve().parents[1]
import sys
if str(_BACKEND) not in sys.path:                                      # pragma: no cover
    sys.path.insert(0, str(_BACKEND))


from services.dataforseo_client import get_credentials_or_none        # noqa: E402


_BE = dotenv_values(_BACKEND / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(autouse=True)
def _cleanup(dbc):
    """Wipe any test rows the direct-coroutine tests inserted."""
    yield
    dbc.seo_rank_heatmaps.delete_many(
        {"tenant_id": {"$regex": r"^TEST_task_j_c5_"}},
    )


# ══ (1-4) get_credentials_or_none env matrix ══════════════════════
def test_creds_present_returns_tuple(monkeypatch):
    """Both env vars set → non-None 2-tuple. No secret contents
    asserted; only shape + truthiness."""
    monkeypatch.setenv("DATAFORSEO_LOGIN", "test_login_dontcare")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "test_pw_dontcare")
    got = get_credentials_or_none()
    assert got is not None
    assert isinstance(got, tuple) and len(got) == 2
    assert bool(got[0]) and bool(got[1])


@pytest.mark.parametrize("missing", ["DATAFORSEO_LOGIN",
                                       "DATAFORSEO_PASSWORD"])
def test_creds_one_missing_returns_none(monkeypatch, missing):
    monkeypatch.setenv("DATAFORSEO_LOGIN", "x")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "y")
    monkeypatch.delenv(missing, raising=False)
    assert get_credentials_or_none() is None


@pytest.mark.parametrize("empty_var", ["DATAFORSEO_LOGIN",
                                          "DATAFORSEO_PASSWORD"])
def test_creds_one_empty_returns_none(monkeypatch, empty_var):
    """Empty string is falsy per ``_creds()`` — not just missing."""
    monkeypatch.setenv("DATAFORSEO_LOGIN", "x")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "y")
    monkeypatch.setenv(empty_var, "")
    assert get_credentials_or_none() is None


def test_creds_both_missing_returns_none(monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    assert get_credentials_or_none() is None


# ══ (5) start_heatmap optimistic mocked flag ═════════════════════
def _run(coro):
    """Codebase convention — reuse the module-level event loop
    (test_phase47_direct_stripe_payment_link.py :60/115/170/etc.).
    ``asyncio.run(...)`` creates a fresh loop per call which
    detaches Motor's ``config.db`` client (bound at import time to
    the loop that was current then). ``get_event_loop()`` grabs the
    already-attached loop so all coroutines share one."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _fake_user() -> Dict[str, Any]:
    return {"id": "TEST_task_j_c5_user", "role": "admin"}


def _fake_tenant() -> Dict[str, Any]:
    return {"id": f"TEST_task_j_c5_tenant_{uuid.uuid4().hex[:8]}"}


def _build_body():
    from routers.seo_agentic import RankHeatmapIn
    return RankHeatmapIn(
        keyword="branch selector probe",
        center_lat=33.6, center_lng=-112.2,
        grid_size=3, radius_miles=3.0,
    )


def test_start_heatmap_mocked_flag_creds_present(monkeypatch, dbc):
    """When creds are present at insert time, the optimistic
    ``mocked`` flag is False and ``mocked_reason`` is None."""
    from fastapi import BackgroundTasks
    from routers import seo_agentic

    monkeypatch.setattr(
        seo_agentic._dfs, "get_credentials_or_none",
        lambda: ("login_placeholder", "pw_placeholder"),
    )
    body = _build_body()
    bg = BackgroundTasks()
    tenant = _fake_tenant()
    result = _run(seo_agentic.start_heatmap(
        body, bg, False, _fake_user(), tenant,
    ))

    assert result["mocked"] is False
    assert result["reason"] is None
    row = dbc.seo_rank_heatmaps.find_one(
        {"id": result["heatmap_id"]}, {"_id": 0},
    )
    assert row is not None
    assert row["mocked"] is False
    assert row["mocked_reason"] is None


def test_start_heatmap_mocked_flag_creds_absent(monkeypatch, dbc):
    """When creds are absent at insert time, the optimistic
    ``mocked`` flag is True and ``mocked_reason`` is
    ``dataforseo_not_configured``. Message hint is also present in
    the response body."""
    from fastapi import BackgroundTasks
    from routers import seo_agentic

    monkeypatch.setattr(
        seo_agentic._dfs, "get_credentials_or_none", lambda: None,
    )
    body = _build_body()
    bg = BackgroundTasks()
    tenant = _fake_tenant()
    result = _run(seo_agentic.start_heatmap(
        body, bg, False, _fake_user(), tenant,
    ))

    assert result["mocked"] is True
    assert isinstance(result["reason"], str) and result["reason"]
    row = dbc.seo_rank_heatmaps.find_one(
        {"id": result["heatmap_id"]}, {"_id": 0},
    )
    assert row is not None
    assert row["mocked"] is True
    assert row["mocked_reason"] == "dataforseo_not_configured"


# ══ (6-7) _generate_heatmap branch selection ═════════════════════
async def _seed_heatmap_row(dbc_async, tenant_id: str) -> str:
    """Insert a queued heatmap row and return its id — mimics what
    ``start_heatmap`` would create before the background task
    fires."""
    from routers.seo_agentic import now_iso
    hid = str(uuid.uuid4())
    await dbc_async.seo_rank_heatmaps.insert_one({
        "id":                hid,
        "tenant_id":         tenant_id,
        "initiated_by":      "TEST_task_j_c5_user",
        "keyword":           "branch selector probe",
        "center":            {"lat": 33.6, "lng": -112.2},
        "grid_size":         3,
        "radius_miles":      3.0,
        "status":            "queued",
        "started_at":        None,
        "finished_at":       None,
        "points":            [],
        "avg_rank":          None,
        "top_position_count": 0,
        "mocked":            False,
        "mocked_reason":     None,
        "created_at":        now_iso(),
    })
    return hid


def test_generate_heatmap_selects_live_path_when_creds_present(monkeypatch):
    """Creds present → ``_dfs.serp_google_organic_live`` is called
    (at least once) and ``_write_mocked_heatmap`` is NOT called."""
    from routers import seo_agentic

    tenant_id = f"TEST_task_j_c5_tenant_{uuid.uuid4().hex[:8]}"
    dfs_calls: list[dict] = []
    mock_writer_calls: list[dict] = []

    monkeypatch.setattr(
        seo_agentic._dfs, "get_credentials_or_none",
        lambda: ("login_placeholder", "pw_placeholder"),
    )

    async def _fake_dfs_call(keyword, lat, lng, **kw):
        # Record + return an empty-envelope DFS response so the
        # downstream rank-parser gets a valid shape.
        dfs_calls.append({"keyword": keyword, "lat": lat, "lng": lng})
        return 200, {"tasks": [{"result": [{"items": []}]}]}, None
    monkeypatch.setattr(
        seo_agentic._dfs, "serp_google_organic_live", _fake_dfs_call,
    )

    async def _fake_mock_writer(*a, **kw):
        mock_writer_calls.append({"args": a, "kw": kw})
    monkeypatch.setattr(
        seo_agentic, "_write_mocked_heatmap", _fake_mock_writer,
    )

    # Stub the tenant lookup so ``_generate_heatmap`` doesn't need a
    # real tenant row (it does ``db.tenants.find_one`` to resolve
    # the target domain — the empty-envelope response above means
    # ranks are all None which is fine for branch-selection).
    async def _run_it():
        from config import db as _live_db
        hid = await _seed_heatmap_row(_live_db, tenant_id)
        await seo_agentic._generate_heatmap(
            heatmap_id=hid, tenant_id=tenant_id,
            keyword="branch selector probe",
            center_lat=33.6, center_lng=-112.2,
            grid_size=3, radius_miles=3.0,
            bypass_cache=True,
        )

    _run(_run_it())

    # Live path fired at least once (grid_size=3 → 9 points → 9 calls).
    assert len(dfs_calls) >= 1, dfs_calls
    # Mock writer NEVER fired.
    assert mock_writer_calls == [], mock_writer_calls


def test_generate_heatmap_selects_mock_path_when_creds_absent(monkeypatch):
    """Creds absent → ``_write_mocked_heatmap`` is called with
    ``reason="dataforseo_not_configured"`` and
    ``_dfs.serp_google_organic_live`` is NOT called."""
    from routers import seo_agentic

    tenant_id = f"TEST_task_j_c5_tenant_{uuid.uuid4().hex[:8]}"
    dfs_calls: list[dict] = []
    mock_writer_calls: list[dict] = []

    monkeypatch.setattr(
        seo_agentic._dfs, "get_credentials_or_none", lambda: None,
    )

    async def _fake_dfs_call(*a, **kw):                                # pragma: no cover
        dfs_calls.append(a)
        return 200, None, None
    monkeypatch.setattr(
        seo_agentic._dfs, "serp_google_organic_live", _fake_dfs_call,
    )

    async def _fake_mock_writer(hid, tid, kw, pts, *, reason):
        mock_writer_calls.append({
            "hid": hid, "tid": tid, "kw": kw,
            "pts_len": len(pts), "reason": reason,
        })
    monkeypatch.setattr(
        seo_agentic, "_write_mocked_heatmap", _fake_mock_writer,
    )

    async def _run_it():
        from config import db as _live_db
        hid = await _seed_heatmap_row(_live_db, tenant_id)
        await seo_agentic._generate_heatmap(
            heatmap_id=hid, tenant_id=tenant_id,
            keyword="branch selector probe",
            center_lat=33.6, center_lng=-112.2,
            grid_size=3, radius_miles=3.0,
            bypass_cache=True,
        )

    _run(_run_it())

    # Mock writer fired exactly once with the expected reason.
    assert len(mock_writer_calls) == 1, mock_writer_calls
    assert mock_writer_calls[0]["reason"] == "dataforseo_not_configured"
    # Live path NEVER fired.
    assert dfs_calls == [], dfs_calls


# ══ (8) Fallback preservation — grep-based static assertion ═════
def test_synthesized_fallback_still_present_in_source():
    """The brief mandates: 'Do NOT delete the "Synthesized" fallback
    silently.' Guard against a future PR removing the mock branch
    by grep-asserting the call site + reason string are still
    present in the router source."""
    src = (_BACKEND / "routers" / "seo_agentic.py").read_text()
    # 1) The credential probe is still there.
    assert "_dfs.get_credentials_or_none()" in src
    # 2) The mocked-writer branch is still there with the exact
    #    reason string the frontend banner keys on.
    assert '_write_mocked_heatmap(' in src
    assert 'reason="dataforseo_not_configured"' in src
