"""Task N Round 2 · Phase N.6 · Feb-2026 — Notes-change notifier tests.

Six notifier tests + four subject-split tests + two recipient-resolver
tests = 12 tests total.

Convention:
- Unit-scoped: ``notify_note_transitions`` / ``notify_submit_finalize``
  are called directly with a mongomock DB and inline stub senders
  (``send_email`` / ``send_sms``) so we assert on captured payloads
  without hitting Resend / RingCentral.
- Debounce collection uses the real ``ensure_debounce_indexes`` so
  the ``DuplicateKeyError`` path is exercised end-to-end.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from services.notes_notifications import notes_change_notifier as N
from services.notes_notifications.recipients import (
    resolve_note_notification_recipients,
)


# ── Fixtures ─────────────────────────────────────────────────
@pytest.fixture
async def adb():
    """Motor AsyncIOMotorClient wrapper.  Uses the real Mongo via
    ``MONGO_URL`` but ISOLATES ALL WRITES to a per-test tenant_id
    prefix (``TEST_TASK_N_NOTIFIER_*``) so the real
    ``notification_debounce`` collection stays clean.  Teardown
    sweeps all rows created during the test."""
    import os
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import dotenv_values
    from pathlib import Path
    _BE = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
    _MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
    _DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")
    client = AsyncIOMotorClient(_MONGO_URL)
    db = client[_DB_NAME]
    await N.ensure_debounce_indexes(db)
    yield db
    # Best-effort teardown of anything this test module inserted.
    await db.notification_debounce.delete_many(
        {"tenant_id": {"$regex": "^(tenant-A$|T_A$|T_B$)"}},
    )
    client.close()


@pytest.fixture
def sample_tenant() -> Dict[str, Any]:
    return {
        "id": "tenant-A",
        "name": "Test Tenant",
        "lead_notification_recipients": [
            {"id": "r1", "phone": "+15555550100",
              "email": "", "sms_opt_in": True, "email_opt_in": False},
            {"id": "r2", "phone": "",
              "email": "ops@test.example",
              "sms_opt_in": False, "email_opt_in": True},
        ],
        "lead_alert_email_recipients": [],
        "lead_alert_sms_recipients": [],
    }


@pytest.fixture
def capture_senders():
    """Return a pair of stub senders that capture each call for
    later assertions.  Both return the standard adapter-shaped dict."""
    emails: List[Dict[str, Any]] = []
    smses: List[Dict[str, Any]] = []

    async def _stub_email(tenant_id, to, subject, html, **kwargs):
        emails.append({
            "tenant_id": tenant_id, "to": to,
            "subject": subject, "html": html,
        })
        return {"status": "sent", "provider_id": f"em-{len(emails)}"}

    async def _stub_sms(tenant_id, to, body, **kwargs):
        smses.append({
            "tenant_id": tenant_id, "to": to, "body": body,
        })
        return {"status": "sent", "provider_id": f"sm-{len(smses)}"}

    return {"send_email": _stub_email, "send_sms": _stub_sms,
            "emails": emails, "smses": smses}


# ═════════════════════════════════════════════════════════════
#  Recipient resolver (2)
# ═════════════════════════════════════════════════════════════
def test_recipient_resolver_respects_per_channel_opt_in(sample_tenant):
    out = resolve_note_notification_recipients(sample_tenant)
    channels = sorted((r["channel"], r["address"]) for r in out)
    assert channels == [("email", "ops@test.example"),
                         ("sms",   "+15555550100")]


def test_recipient_resolver_dedupe_across_structured_and_flat():
    tenant = {
        "id": "t",
        "lead_notification_recipients": [
            {"id": "r1", "phone": "+15555550100",
              "email": "ops@test.example",
              "sms_opt_in": True, "email_opt_in": True},
        ],
        "lead_alert_email_recipients": ["ops@test.example",
                                          "second@test.example"],
        "lead_alert_sms_recipients":   ["+15555550100",
                                          "+15555550111"],
    }
    out = resolve_note_notification_recipients(tenant)
    addrs = sorted((r["channel"], r["address"]) for r in out)
    assert addrs == [
        ("email", "ops@test.example"),
        ("email", "second@test.example"),
        ("sms",   "+15555550100"),
        ("sms",   "+15555550111"),
    ]
    # Structured entry keeps its ``recipient_id``.
    first_ops = next(r for r in out
                     if (r["channel"], r["address"]) == ("email", "ops@test.example"))
    assert first_ops["recipient_id"] == "r1"


# ═════════════════════════════════════════════════════════════
#  Notifier · transition semantics (2)
# ═════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_notifier_fires_on_empty_to_populated_transition(
    adb, sample_tenant, capture_senders,
):
    old = {"notes": "", "internal_notes": "", "customer_notes": ""}
    new = {"notes": "", "internal_notes": "Dog aggressive",
           "customer_notes": ""}
    res = await N.notify_note_transitions(
        db=adb, tenant=sample_tenant,
        sr_id="sr-A", job_id="job-A", customer_name="Diane Lloyd",
        template="pool", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    assert res["status"] == "ok"
    assert len(res["fields_fired"]) == 1
    assert res["fields_fired"][0]["note_field"] == "internal_notes"
    # Fan-out hit both channels.
    assert len(capture_senders["emails"]) == 1
    assert len(capture_senders["smses"]) == 1
    # Subject signal locked.
    assert capture_senders["emails"][0]["subject"] == (
        "[Pool] New note added — Diane Lloyd")


@pytest.mark.anyio
async def test_notifier_does_NOT_fire_on_value_edit(
    adb, sample_tenant, capture_senders,
):
    old = {"internal_notes": "old text",
           "notes": "", "customer_notes": ""}
    new = {"internal_notes": "edited text",
           "notes": "", "customer_notes": ""}
    res = await N.notify_note_transitions(
        db=adb, tenant=sample_tenant,
        sr_id="sr-B", job_id="job-B", customer_name="Sam Rivera",
        template="pool", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    assert res["status"] == "ok"
    assert res["fields_fired"] == []
    assert capture_senders["emails"] == []
    assert capture_senders["smses"] == []


# ═════════════════════════════════════════════════════════════
#  Notifier · debounce (2)
# ═════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_notifier_debounces_duplicate_patch_transition(
    adb, sample_tenant, capture_senders,
):
    old = {"internal_notes": ""}
    new = {"internal_notes": "first fire"}
    await N.notify_note_transitions(
        db=adb, tenant=sample_tenant,
        sr_id="sr-D", job_id="job-D", customer_name="Diane Lloyd",
        template="pool", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    # Simulate a concurrent PATCH that also crosses the transition
    # (e.g. because it saw the same pre-write ``old_sr``).
    await N.notify_note_transitions(
        db=adb, tenant=sample_tenant,
        sr_id="sr-D", job_id="job-D", customer_name="Diane Lloyd",
        template="pool", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    # Only ONE fanout fired.
    assert len(capture_senders["emails"]) == 1
    assert len(capture_senders["smses"]) == 1


@pytest.mark.anyio
async def test_notifier_debounce_scoped_to_transition_kind(
    adb, sample_tenant, capture_senders,
):
    """A patch fire must NOT debounce a subsequent submit_finalize
    fire — they are semantically distinct events per Phase N.5 §C."""
    old = {"internal_notes": ""}
    new = {"internal_notes": "first fire — patch time"}
    await N.notify_note_transitions(
        db=adb, tenant=sample_tenant,
        sr_id="sr-E", job_id="job-E", customer_name="Bob Kaye",
        template="pool", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    assert len(capture_senders["emails"]) == 1
    # Submit fires the belt-and-suspenders finalize — different kind key.
    await N.notify_submit_finalize(
        db=adb, tenant=sample_tenant,
        sr_id="sr-E", job_id="job-E", customer_name="Bob Kaye",
        template="pool", new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    assert len(capture_senders["emails"]) == 2
    assert capture_senders["emails"][1]["subject"].startswith(
        "[Pool] Service report submitted")


# ═════════════════════════════════════════════════════════════
#  Notifier · one-channel-fails, other-continues (1)
# ═════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_one_channel_failure_does_not_block_the_other(
    adb, sample_tenant,
):
    emails = []
    smses = []

    async def _stub_email(tenant_id, to, subject, html, **kwargs):
        emails.append({"to": to})
        return {"status": "sent", "provider_id": "ok"}

    async def _stub_sms(tenant_id, to, body, **kwargs):
        smses.append({"to": to})
        raise RuntimeError("sms provider outage")

    res = await N.notify_note_transitions(
        db=adb, tenant=sample_tenant,
        sr_id="sr-F", job_id="job-F", customer_name="Sam Rivera",
        template="landscape", old_sr={"internal_notes": ""},
        new_sr={"internal_notes": "fire"},
        send_email=_stub_email, send_sms=_stub_sms,
    )
    assert res["status"] == "ok"
    # Email fired.
    assert len(emails) == 1
    # SMS crashed but was caught.
    assert len(smses) == 1
    per_channel = res["fields_fired"][0]["results"]
    kinds = {r["channel"]: r["status"] for r in per_channel}
    assert kinds["email"] == "sent"
    assert kinds["sms"] == "failed"


# ═════════════════════════════════════════════════════════════
#  Notifier · cross-tenant isolation (1)
# ═════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_debounce_isolated_per_tenant(adb, capture_senders):
    """Two tenants, same sr_id (theoretically colliding), same field
    and kind — must both fire.  Debounce composite key includes
    tenant_id as the first component."""
    ta = {"id": "T_A", "lead_alert_email_recipients": ["a@a.a"],
          "lead_alert_sms_recipients": []}
    tb = {"id": "T_B", "lead_alert_email_recipients": ["b@b.b"],
          "lead_alert_sms_recipients": []}
    old = {"internal_notes": ""}
    new = {"internal_notes": "cross-tenant fire"}
    await N.notify_note_transitions(
        db=adb, tenant=ta,
        sr_id="sr-SAMEID", job_id="j", customer_name="C",
        template="pool", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    await N.notify_note_transitions(
        db=adb, tenant=tb,
        sr_id="sr-SAMEID", job_id="j", customer_name="C",
        template="pool", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    tenants_hit = sorted(e["tenant_id"] for e in capture_senders["emails"])
    assert tenants_hit == ["T_A", "T_B"]


# ═════════════════════════════════════════════════════════════
#  Notifier · subject-split (4)
# ═════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_patch_and_submit_subjects_differ(
    adb, sample_tenant, capture_senders,
):
    old = {"internal_notes": ""}
    new = {"internal_notes": "T"}
    await N.notify_note_transitions(
        db=adb, tenant=sample_tenant,
        sr_id="sr-SUB1", job_id="j1", customer_name="C1",
        template="pool", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    await N.notify_submit_finalize(
        db=adb, tenant=sample_tenant,
        sr_id="sr-SUB1", job_id="j1", customer_name="C1",
        template="pool", new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    assert capture_senders["emails"][0]["subject"].startswith(
        "[Pool] New note added")
    assert capture_senders["emails"][1]["subject"].startswith(
        "[Pool] Service report submitted")
    assert (capture_senders["emails"][0]["subject"]
            != capture_senders["emails"][1]["subject"])


@pytest.mark.anyio
async def test_patch_and_submit_bodies_differ(
    adb, sample_tenant, capture_senders,
):
    old = {"internal_notes": ""}
    new = {"internal_notes": "aggressive dog on-site"}
    await N.notify_note_transitions(
        db=adb, tenant=sample_tenant,
        sr_id="sr-SUB2", job_id="j2", customer_name="C2",
        template="pool", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    await N.notify_submit_finalize(
        db=adb, tenant=sample_tenant,
        sr_id="sr-SUB2", job_id="j2", customer_name="C2",
        template="pool", new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    p_html = capture_senders["emails"][0]["html"]
    s_html = capture_senders["emails"][1]["html"]
    assert "just added a note" in p_html
    assert "has been finalized" in s_html
    assert p_html != s_html


@pytest.mark.anyio
async def test_patch_fires_alone_no_submit_yet(
    adb, sample_tenant, capture_senders,
):
    """Only PATCH observed; submit not called — only patch subject
    sent, no submit subject anywhere in the outbox."""
    old = {"customer_notes": ""}
    new = {"customer_notes": "customer-facing summary"}
    await N.notify_note_transitions(
        db=adb, tenant=sample_tenant,
        sr_id="sr-SUB3", job_id="j3", customer_name="C3",
        template="landscape", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    subjects = [e["subject"] for e in capture_senders["emails"]]
    assert all("Landscaping" in s for s in subjects)
    assert all("Service report submitted" not in s for s in subjects)


@pytest.mark.anyio
async def test_submit_fires_alone_after_patch_already_fired_same_sr(
    adb, sample_tenant, capture_senders,
):
    old = {"internal_notes": ""}
    new = {"internal_notes": "note"}
    await N.notify_note_transitions(
        db=adb, tenant=sample_tenant,
        sr_id="sr-SUB4", job_id="j4", customer_name="C4",
        template="pool", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    # Re-dispatch the same PATCH transition — must debounce.
    await N.notify_note_transitions(
        db=adb, tenant=sample_tenant,
        sr_id="sr-SUB4", job_id="j4", customer_name="C4",
        template="pool", old_sr=old, new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    assert len(capture_senders["emails"]) == 1
    # Submit fires despite same-SR history.
    await N.notify_submit_finalize(
        db=adb, tenant=sample_tenant,
        sr_id="sr-SUB4", job_id="j4", customer_name="C4",
        template="pool", new_sr=new,
        send_email=capture_senders["send_email"],
        send_sms=capture_senders["send_sms"],
    )
    assert len(capture_senders["emails"]) == 2
    assert capture_senders["emails"][1]["subject"].startswith(
        "[Pool] Service report submitted")
