"""Phase P45 · Feb-2026 — De-dupe Visit Summary Emails + Absolute Photo URLs.

Locks the four contracts introduced by P45:

  A. Atomic single-writer gate (``services.service_report_submit_gate``)
     stamps ``submitted_at`` + ``email_pending_at`` + ``sms_pending_at``
     in one write; the ``sent_at`` markers migrate on background-task
     success.  Prevents double email/SMS enqueue across concurrent
     ``service_reports.submit`` / ``jobs.py PUT status=completed``.

  B. Auto ``schedule_auto_send_door_hanger`` was removed from both
     writer paths.  The manual endpoint
     (``POST /api/jobs/{jid}/email-door-hanger``) still uses it and
     now emits a WARN log line for audit.

  C. Every ``<img src="…">`` and portal link in the visit-summary
     email HTML routes through ``_absolute_url`` so Gmail/Outlook
     can resolve them.  Env precedence:
     ``PUBLIC_FRONTEND_ORIGIN`` > ``APP_PUBLIC_URL`` > hardcoded
     ``https://app.plofv.com`` (one WARN on first hardcode fallback).

  D. SMS body never contains any HTML tag, ``<img``, or asset URL.
     SMS is plain text only — logo/branding lives EXCLUSIVELY in
     the email path.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "P45_"


# ─── Sync fixture — pymongo for seeding + cleanup ────────────────────

@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    seeded_report_ids: List[str] = []
    seeded_job_ids: List[str] = []
    seeded_tenant_ids: List[str] = []
    yield seeded_report_ids, seeded_job_ids, seeded_tenant_ids
    if seeded_report_ids:
        dbc.service_reports.delete_many({"id": {"$in": seeded_report_ids}})
    if seeded_job_ids:
        dbc.service_reports.delete_many({"job_id": {"$in": seeded_job_ids}})
        dbc.jobs.delete_many({"id": {"$in": seeded_job_ids}})
    if seeded_tenant_ids:
        dbc.service_reports.delete_many(
            {"tenant_id": {"$in": seeded_tenant_ids}},
        )


# ─── Async loop helper ──────────────────────────────────────────────

def _loop_and_db():
    """Fresh asyncio loop + Motor client bound to it; patches
    ``services.service_report_submit_gate.db`` and ``config.db``
    for the SUT call."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    from services import service_report_submit_gate as _sr
    _sr._orig_db_for_test = getattr(_sr, "_orig_db_for_test", _sr.db)
    _sr.db = adb
    return loop, client, adb


def _restore_db(client=None, loop=None):
    from services import service_report_submit_gate as _sr
    if hasattr(_sr, "_orig_db_for_test"):
        _sr.db = _sr._orig_db_for_test
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    if loop is not None:
        try:
            loop.close()
        except Exception:
            pass


def _run(coro_factory):
    """Run an async closure inside a fresh loop + patched Motor db.
    ``coro_factory`` is a 0-arg callable that returns a coroutine."""
    loop, client, _adb = _loop_and_db()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        _restore_db(client, loop)


# ─── Seed helpers ────────────────────────────────────────────────────

def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_report(dbc, *, tenant_id, job_id=None, tech_id=None,
                  submitted_at=None) -> str:
    rid = _fresh("SR")
    doc = {
        "id": rid, "tenant_id": tenant_id,
        "job_id": job_id or _fresh("JOB"),
        "tech_id": tech_id or _fresh("TECH"),
        "created_at": "2026-02-01T00:00:00Z",
    }
    if submitted_at is not None:
        doc["submitted_at"] = submitted_at
    dbc.service_reports.insert_one(doc)
    return rid


# ═══════════════════════════════════════════════════════════════════
# A) Atomic single-writer gate
# ═══════════════════════════════════════════════════════════════════

def test_atomic_gate_sets_all_three_stamps_together(dbc, cleanup):
    """A winning ``claim_submit_or_none`` writes ``submitted_at``,
    ``email_pending_at`` and ``sms_pending_at`` — all to the same
    iso ts, in a single findOneAndUpdate."""
    reps, _, _ = cleanup
    t = _fresh("T")
    rid = _seed_report(dbc, tenant_id=t)
    reps.append(rid)

    async def _c():
        from services.service_report_submit_gate import claim_submit_or_none
        return await claim_submit_or_none(tenant_id=t, report_id=rid,
                                            now_iso="2026-02-01T12:00:00+00:00")

    claim = _run(_c)
    assert claim is not None
    row = dbc.service_reports.find_one({"id": rid})
    assert row["submitted_at"] == "2026-02-01T12:00:00+00:00"
    assert row["email_pending_at"] == "2026-02-01T12:00:00+00:00"
    assert row["sms_pending_at"] == "2026-02-01T12:00:00+00:00"


def test_atomic_gate_returns_none_on_second_call(dbc, cleanup):
    """Second call after a successful claim MUST return None so the
    caller skips enqueue."""
    reps, _, _ = cleanup
    t = _fresh("T")
    rid = _seed_report(dbc, tenant_id=t)
    reps.append(rid)

    async def _c():
        from services.service_report_submit_gate import claim_submit_or_none
        first = await claim_submit_or_none(tenant_id=t, report_id=rid)
        second = await claim_submit_or_none(tenant_id=t, report_id=rid)
        return first, second

    first, second = _run(_c)
    assert first is not None
    assert second is None


def test_atomic_gate_prevents_double_claim_under_concurrency(
    dbc, cleanup,
):
    """Fire 3 concurrent ``claim_submit_or_none`` calls — exactly ONE
    must succeed.  Guards the race the gate exists to prevent."""
    reps, _, _ = cleanup
    t = _fresh("T")
    rid = _seed_report(dbc, tenant_id=t)
    reps.append(rid)

    async def _c():
        from services.service_report_submit_gate import claim_submit_or_none
        results = await asyncio.gather(
            claim_submit_or_none(tenant_id=t, report_id=rid),
            claim_submit_or_none(tenant_id=t, report_id=rid),
            claim_submit_or_none(tenant_id=t, report_id=rid),
        )
        return results

    results = _run(_c)
    wins = sum(1 for r in results if r is not None)
    assert wins == 1, f"expected exactly 1 winner, got {wins}"


def test_atomic_gate_matches_legacy_empty_string_submitted_at(
    dbc, cleanup,
):
    """Some legacy rows have ``submitted_at: ""`` (empty string
    instead of null).  The gate's ``$in: [None, ""]`` filter MUST
    claim these too."""
    reps, _, _ = cleanup
    t = _fresh("T")
    rid = _seed_report(dbc, tenant_id=t, submitted_at="")
    reps.append(rid)

    async def _c():
        from services.service_report_submit_gate import claim_submit_or_none
        return await claim_submit_or_none(tenant_id=t, report_id=rid)

    claim = _run(_c)
    assert claim is not None


def test_email_sent_stamp_migrates_pending_marker(dbc, cleanup):
    """``stamp_email_sent`` moves ``email_pending_at`` →
    ``email_sent_at``."""
    reps, _, _ = cleanup
    t = _fresh("T")
    rid = _seed_report(dbc, tenant_id=t)
    reps.append(rid)

    async def _c():
        from services.service_report_submit_gate import (
            claim_submit_or_none, stamp_email_sent,
        )
        await claim_submit_or_none(tenant_id=t, report_id=rid)
        await stamp_email_sent(tenant_id=t, report_id=rid)

    _run(_c)
    row = dbc.service_reports.find_one({"id": rid})
    assert "email_pending_at" not in row
    assert row.get("email_sent_at")
    # sms_pending_at should still be present — only email migrated.
    assert row.get("sms_pending_at")


def test_sms_sent_stamp_migrates_pending_marker(dbc, cleanup):
    """Sibling of the email-stamp test — verifies SMS migration."""
    reps, _, _ = cleanup
    t = _fresh("T")
    rid = _seed_report(dbc, tenant_id=t)
    reps.append(rid)

    async def _c():
        from services.service_report_submit_gate import (
            claim_submit_or_none, stamp_sms_sent,
        )
        await claim_submit_or_none(tenant_id=t, report_id=rid)
        await stamp_sms_sent(tenant_id=t, report_id=rid)

    _run(_c)
    row = dbc.service_reports.find_one({"id": rid})
    assert "sms_pending_at" not in row
    assert row.get("sms_sent_at")


# ═══════════════════════════════════════════════════════════════════
# B) Manual door-hanger endpoint audit
# ═══════════════════════════════════════════════════════════════════

def test_manual_door_hanger_endpoint_emits_p45_warn_log():
    """The manual ``email_door_hanger`` endpoint must emit a WARN
    line starting with ``[p45] door-hanger sent via manual
    trigger`` — grep-based check on the source, matching the
    ``phase30-3-portal-sign-out`` pattern."""
    src = Path(__file__).resolve().parents[1] / "routers/workstream_service_log.py"
    text = src.read_text()
    # The warn line must appear inside the ``email_door_hanger``
    # handler AFTER the ``_require_admin_or_403(user)`` line.
    handler = re.search(
        r"async def email_door_hanger\([\s\S]*?_require_admin_or_403\(user\)([\s\S]*)",
        text,
    )
    assert handler, "email_door_hanger handler not found"
    # Take the first 40 lines after the admin gate — that's the
    # handler body window where the WARN line should sit.
    body_after_gate = "\n".join(handler.group(1).splitlines()[:40])
    assert "[p45] door-hanger sent via manual trigger" in body_after_gate
    assert "user.get(\"id\")" in body_after_gate
    assert "tenant.get(\"id\")" in body_after_gate


def test_auto_writer_paths_no_longer_call_schedule_auto_send_door_hanger():
    """P45 removed ``schedule_auto_send_door_hanger`` from both auto
    call sites: ``service_reports.py`` submit + ``jobs.py`` PUT
    status=completed.  Zero call-site references should remain in
    those two files."""
    base = Path(__file__).resolve().parents[1] / "routers"
    for name in ("service_reports.py", "jobs.py"):
        text = (base / name).read_text()
        # ``import`` mentions are fine (function name in a comment
        # or import is OK, but there must be ZERO actual call
        # syntax ``schedule_auto_send_door_hanger(``).
        calls = re.findall(r"schedule_auto_send_door_hanger\s*\(", text)
        assert calls == [], (
            f"{name} still calls schedule_auto_send_door_hanger — "
            "P45 removed all auto call sites"
        )


def test_schedule_auto_send_door_hanger_still_defined():
    """The function itself is kept — manual endpoint still uses it."""
    src = Path(__file__).resolve().parents[1] / "routers/workstream_service_log.py"
    text = src.read_text()
    assert "def schedule_auto_send_door_hanger" in text


# ═══════════════════════════════════════════════════════════════════
# C) Absolute photo URLs in email HTML
# ═══════════════════════════════════════════════════════════════════

def test_absolute_url_prepends_public_frontend_origin_when_set(
    monkeypatch,
):
    """PUBLIC_FRONTEND_ORIGIN wins over APP_PUBLIC_URL and
    hardcoded fallback."""
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "https://pfo.example.com")
    monkeypatch.setenv("APP_PUBLIC_URL", "https://apu.example.com")
    from services.auto_visit_email import _absolute_url
    assert _absolute_url("/api/public/photo/xyz.jpg") == (
        "https://pfo.example.com/api/public/photo/xyz.jpg"
    )


def test_absolute_url_falls_back_to_app_public_url_when_pfo_absent(
    monkeypatch,
):
    """When PUBLIC_FRONTEND_ORIGIN is absent, APP_PUBLIC_URL wins."""
    monkeypatch.delenv("PUBLIC_FRONTEND_ORIGIN", raising=False)
    monkeypatch.setenv("APP_PUBLIC_URL", "https://apu.example.com")
    from services.auto_visit_email import _absolute_url
    assert _absolute_url("/api/public/photo/xyz.jpg") == (
        "https://apu.example.com/api/public/photo/xyz.jpg"
    )


def test_absolute_url_falls_back_to_hardcoded_when_both_env_absent(
    monkeypatch, caplog,
):
    """Both env vars absent → hardcoded ``https://app.plofv.com``
    + one WARN on first fallback."""
    monkeypatch.delenv("PUBLIC_FRONTEND_ORIGIN", raising=False)
    monkeypatch.delenv("APP_PUBLIC_URL", raising=False)
    import services.auto_visit_email as ave
    # Reset the module-level guard so the WARN fires this test run.
    ave._P45_WARNED_HARDCODE = False
    with caplog.at_level("WARNING", logger="pool_crm"):
        result = ave._absolute_url("/api/public/photo/xyz.jpg")
    assert result == "https://app.plofv.com/api/public/photo/xyz.jpg"
    warns = [r.getMessage() for r in caplog.records
             if r.levelname == "WARNING"]
    assert any("_absolute_url falling back to hardcoded" in w
                for w in warns), (
        f"expected P45 hardcode-fallback WARN, got {warns}"
    )


def test_absolute_url_passthrough_for_already_absolute(monkeypatch):
    """Already-absolute URLs (https://, data:, cid:) pass through
    byte-identical."""
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "https://pfo.example.com")
    from services.auto_visit_email import _absolute_url
    for url in (
        "https://cdn.example.com/foo.jpg",
        "http://legacy.example.com/bar.png",
        "data:image/jpeg;base64,AAAA",
        "cid:inline-photo-1",
    ):
        assert _absolute_url(url) == url, (
            f"{url} should have passed through unchanged"
        )


def test_email_html_wraps_photo_urls_and_logo_through_helper():
    """Grep-based structural test: the email-HTML builders MUST
    reference ``_absolute_url`` around every ``<img src=``."""
    src = Path(__file__).resolve().parents[1] / "services/auto_visit_email.py"
    text = src.read_text()
    # Every ``<img src="{ ... }"`` MUST use a variable produced by
    # ``_absolute_url(...)`` — grep for both markers and assert
    # they're near each other.
    photo_img = re.search(
        r"grid_cells\.append\(([\s\S]{0,600})<img src=\"\{([^}]+)\}\"",
        text,
    )
    assert photo_img is not None, (
        "grid_cells append + img src pattern not found"
    )
    photo_var = photo_img.group(2).strip()
    assert "abs" in photo_var.lower(), (
        f"photo <img src> uses raw ``{photo_var}`` — expected abs_url variant"
    )
    logo_img = re.search(
        r"if logo:([\s\S]{0,400})<img src=\"\{([^}]+)\}\"",
        text,
    )
    assert logo_img is not None, "logo <img> pattern not found"
    logo_var = logo_img.group(2).strip()
    assert "abs" in logo_var.lower(), (
        f"logo <img src> uses raw ``{logo_var}`` — expected abs_logo variant"
    )
    # And _absolute_url must actually be called in the file.
    assert "_absolute_url(" in text


# ═══════════════════════════════════════════════════════════════════
# D) SMS-body plain-text guard
# ═══════════════════════════════════════════════════════════════════

def test_sms_body_contains_no_html_or_image_references(dbc):
    """SMS body must be plain text — no HTML tags, no image refs,
    no logo strings.  Exercises the real template builder used by
    ``_bg_send_completion_sms``."""
    from services.completion_sms_template import build_completion_sms_body

    tenant = {
        "id": "t-p45",
        "name": "Pool Landscaping of Vistancia",
        "business_settings": {"business_name": "Pool Landscaping of Vistancia"},
    }
    job = {"id": "j-p45", "customer_id": "c-p45",
            "service_type": "Full Service", "title": "Weekly service"}
    customer = {"id": "c-p45", "name": "Jane Test",
                 "first_name": "Jane", "phone": "+15555550100"}
    body = build_completion_sms_body(
        tenant=tenant, job=job, customer=customer,
        portal_link="https://app.plofv.com/portal/service-reports",
    )
    # No HTML tags of any kind.
    assert "<img" not in body.lower()
    assert "<html" not in body.lower()
    assert "<a " not in body.lower()
    assert "<br" not in body.lower()
    assert "<div" not in body.lower()
    # No asset URLs / logo references.
    for token in (".jpg", ".png", ".svg", ".webp", "logo"):
        assert token not in body.lower(), (
            f"SMS body contains disallowed token ``{token}``: {body!r}"
        )
    # Positive assertions — the portal link IS present (that's the
    # legitimate URL in the SMS body).
    assert "https://" in body
    assert "portal" in body.lower()


def test_sms_defensive_contract_comment_present_in_bg_task():
    """The ``_bg_send_completion_sms`` closure must carry the P45
    plain-text-only defensive contract comment so future edits
    can't silently reintroduce logo/image content."""
    src = Path(__file__).resolve().parents[1] / "routers/service_reports.py"
    text = src.read_text()
    m = re.search(
        r"async def _bg_send_completion_sms\([\s\S]{0,120}\)"
        r"([\s\S]{0,1500})",
        text,
    )
    assert m is not None, "_bg_send_completion_sms closure not found"
    head = m.group(1)
    assert "SMS-body defensive contract" in head
    assert "plain text only" in head
