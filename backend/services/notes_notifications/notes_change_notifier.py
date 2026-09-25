"""Task N Round 2 · Phase N.6 · Feb-2026 — Notes-change notifier.

Detects empty→populated transitions on the three SR note fields
(``notes``, ``internal_notes``, ``customer_notes``) between a
pre-write ``old_sr`` and a post-write ``new_sr`` document, fans
out notifications to the tenant's notification recipients via
the standard email + SMS adapters, and locks each fire against
duplicate-dispatch via a mongo ``notification_debounce``
collection (unique key + TTL).

Two transition kinds, tracked independently in the debounce
collection so they don't cancel each other:

  - ``patch_transition``  — an empty→populated flip observed
    inside ``patch_service_report``.  Subject reads "New note added".

  - ``submit_finalize``   — belt-and-suspenders safety net fired
    from ``submit_service_report``: if ANY note field is populated
    at submit time, send a "Service report submitted — notes
    attached" summary.  Fires REGARDLESS of whether
    ``patch_transition`` already fired for the same field earlier;
    the debounce key differs so no dedupe collision.

Framework-agnostic.  The router injects the real ``db`` handle;
tests inject a mongomock DB or a stub sender.  Send failures are
WARN-logged and swallowed — a notifier failure NEVER fails the
originating PATCH / submit request.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from services.notes_notifications.recipients import (
    resolve_note_notification_recipients,
)


logger = logging.getLogger("notifications.notes_change")


NOTE_FIELDS = ("notes", "internal_notes", "customer_notes")
NOTE_LABELS = {
    "notes": "Notes",
    "internal_notes": "Internal Note",
    "customer_notes": "Customer Note",
}
TRANSITION_KIND_PATCH = "patch_transition"
TRANSITION_KIND_SUBMIT = "submit_finalize"
DEBOUNCE_TTL_HOURS = 24
SMS_BODY_MAX = 140  # preview cap on note text inside sms bodies
SUBMIT_SMS_MAX = 160

_TEMPLATE_INDUSTRY_MAP = {
    "pool": "Pool",
    "landscape": "Landscaping",
    "generic": "Service",
}


def industry_label(template: Optional[str]) -> str:
    return _TEMPLATE_INDUSTRY_MAP.get(
        (template or "").strip().lower(), "Service",
    )


def is_empty_to_populated(old: Optional[str], new: Optional[str]) -> bool:
    """Transition semantics locked by Phase N.5 §C.

    True iff ``new`` is non-empty (after ``strip()``) AND ``old`` is
    empty / None / whitespace.  Value edits (both non-empty) do NOT
    fire.  A future re-flip from empty→populated fires again because
    each event is a distinct debounce key at insertion time.
    """
    return bool(new and new.strip()) and not bool(old and old.strip())


def _resolve_frontend_base_url() -> str:
    """Match the existing convention (see
    ``services.tenants.business_settings.resolve_public_base_url``).
    Precedence: PUBLIC_APP_BASE_URL → FRONTEND_BASE_URL → APP_BASE_URL
    → hard-coded prod fallback.  Never invent a new env.
    """
    for k in ("PUBLIC_APP_BASE_URL", "FRONTEND_BASE_URL", "APP_BASE_URL"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return v.rstrip("/")
    return "https://app.plofv.com"


def build_job_admin_link(job_id: str) -> str:
    return f"{_resolve_frontend_base_url()}/admin/jobs/{job_id}"


# ═════════════════════════════════════════════════════════════════
#  Body templates
# ═════════════════════════════════════════════════════════════════

def _short(text: str, max_len: int) -> str:
    text = (text or "").strip().replace("\r", " ").replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"


def build_patch_email(*, industry: str, customer_name: str,
                       note_field: str, new_text: str,
                       job_link: str) -> Dict[str, str]:
    label = NOTE_LABELS.get(note_field, "Note")
    subject = f"[{industry}] New note added — {customer_name}"
    preview = _short(new_text, 280)
    html = (
        f"<p>A tech just added a note to <strong>{customer_name}</strong>'s "
        f"{industry} job.</p>"
        f"<p><strong>{label}:</strong><br/>{preview}</p>"
        f'<p><a href="{job_link}">View job</a></p>'
    )
    return {"subject": subject, "html": html}


def build_patch_sms(*, industry: str, customer_name: str,
                     new_text: str, job_link: str) -> str:
    preview = _short(new_text, SMS_BODY_MAX)
    return f"[{industry}] New note — {customer_name}: {preview} {job_link}"


def build_submit_email(*, industry: str, customer_name: str,
                        new_sr: Dict[str, Any], job_link: str) -> Dict[str, str]:
    subject = (f"[{industry}] Service report submitted — "
                f"notes attached — {customer_name}")
    parts = []
    for f in NOTE_FIELDS:
        text = (new_sr.get(f) or "").strip()
        if text:
            parts.append(
                f"<p><strong>{NOTE_LABELS[f]}:</strong><br/>{_short(text, 480)}</p>"
            )
    body_notes = "".join(parts) or "<p>(no notes attached)</p>"
    html = (
        f"<p>The service report for <strong>{customer_name}</strong>'s "
        f"{industry} job has been finalized. Includes the following notes:</p>"
        f"{body_notes}"
        f'<p><a href="{job_link}">View job</a></p>'
    )
    return {"subject": subject, "html": html}


def build_submit_sms(*, industry: str, customer_name: str,
                      new_sr: Dict[str, Any], job_link: str) -> str:
    n = sum(1 for f in NOTE_FIELDS
            if (new_sr.get(f) or "").strip())
    plural = "s" if n != 1 else ""
    body = (f"[{industry}] Report submitted for {customer_name} — "
             f"{n} note{plural} attached. {job_link}")
    return body[:SUBMIT_SMS_MAX + 60]  # url pushes total; adapter renders full


# ═════════════════════════════════════════════════════════════════
#  Debounce
# ═════════════════════════════════════════════════════════════════

async def _try_insert_debounce(
    db: Any, *, tenant_id: str, sr_id: str,
    note_field: str, transition_kind: str,
) -> bool:
    """Attempt to reserve the (tenant, sr, field, kind) slot.

    Returns True on successful insert (caller may send); False on
    ``DuplicateKeyError`` (already-fired within TTL — caller skips).
    Any OTHER exception logs + returns True so a debounce-collection
    outage never blocks a legitimate send.
    """
    try:
        from pymongo.errors import DuplicateKeyError
    except Exception:  # pragma: no cover — pymongo must exist
        DuplicateKeyError = Exception  # type: ignore
    now = datetime.now(timezone.utc)
    doc = {
        "tenant_id": tenant_id,
        "sr_id": sr_id,
        "note_field": note_field,
        "transition_kind": transition_kind,
        "fired_at": now.isoformat(),
        "expires_at": now + timedelta(hours=DEBOUNCE_TTL_HOURS),
    }
    try:
        await db.notification_debounce.insert_one(doc)
        return True
    except DuplicateKeyError:
        return False
    except Exception as e:
        logger.warning(
            "[notes-notifier] debounce insert failed — proceeding: %s: %s",
            type(e).__name__, e,
        )
        return True


async def ensure_debounce_indexes(db: Any) -> None:
    """Idempotent — call at server startup + at test setup."""
    try:
        await db.notification_debounce.create_index(
            [("tenant_id", 1), ("sr_id", 1),
              ("note_field", 1), ("transition_kind", 1)],
            unique=True,
            name="notification_debounce_composite_uk",
            background=True,
        )
        await db.notification_debounce.create_index(
            "expires_at", expireAfterSeconds=0,
            name="notification_debounce_ttl",
            background=True,
        )
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[notes-notifier] ensure_debounce_indexes crashed: %s", e,
        )


# ═════════════════════════════════════════════════════════════════
#  Notifier
# ═════════════════════════════════════════════════════════════════

async def _dispatch_fanout(
    *, tenant_id: str,
    recipients: List[Dict[str, str]],
    email_subject: str, email_html: str, sms_body: str,
    send_email: Callable[..., Any],
    send_sms: Callable[..., Any],
) -> List[Dict[str, Any]]:
    """Fan out sends concurrently.  One recipient's failure never
    blocks another.  Returns a list of per-recipient result dicts."""
    if not recipients:
        return []

    async def _one(r: Dict[str, str]) -> Dict[str, Any]:
        if r["channel"] == "email":
            res = await send_email(tenant_id, r["address"],
                                    email_subject, email_html)
        elif r["channel"] == "sms":
            res = await send_sms(tenant_id, r["address"], sms_body)
        else:
            return {"channel": r["channel"], "address": r["address"],
                    "status": "unknown_channel"}
        return {"channel": r["channel"], "address": r["address"],
                "recipient_id": r.get("recipient_id", ""),
                "status": (res or {}).get("status"),
                "provider_id": (res or {}).get("provider_id"),
                "error": (res or {}).get("error")}

    results = await asyncio.gather(
        *(_one(r) for r in recipients), return_exceptions=True,
    )
    normalised: List[Dict[str, Any]] = []
    for r, res in zip(recipients, results):
        if isinstance(res, Exception):
            logger.warning(
                "[notes-notifier] fanout to %s (%s) crashed: %s: %s",
                r.get("address"), r.get("channel"),
                type(res).__name__, res,
            )
            normalised.append({
                "channel": r["channel"], "address": r["address"],
                "recipient_id": r.get("recipient_id", ""),
                "status": "failed", "error": str(res),
            })
        else:
            normalised.append(res)
    return normalised


async def notify_note_transitions(
    *, db: Any, tenant: Dict[str, Any],
    sr_id: str, job_id: str, customer_name: str,
    template: Optional[str],
    old_sr: Dict[str, Any], new_sr: Dict[str, Any],
    send_email: Optional[Callable[..., Any]] = None,
    send_sms: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Patch-time entry point.

    Emits a distinct fanout PER transitioning note field so an
    aggressive edit that transitions TWO fields simultaneously
    produces two events (a subject-line per note kind is clearer
    than one lumped subject).

    Never raises.  Send failures WARN + swallow.  Debounce
    collisions log at INFO and skip cleanly.
    """
    # Recipient-resolver comment — see Phase N.5 §A.  ``lead_
    # notification_recipients`` is legacy-named but is the current
    # per-channel opt-in surface; we intentionally reuse it here
    # instead of adding new tenant fields.
    recipients = resolve_note_notification_recipients(tenant)
    if not recipients:
        logger.info("[notes-notifier] no recipients for tenant=%s",
                     tenant.get("id"))
        return {"status": "no_recipients", "fields_fired": []}

    if send_email is None:
        from services.comms_email_adapter import send_email as _se
        send_email = _se
    if send_sms is None:
        from services.comms_sms_adapter import send_sms as _ss
        send_sms = _ss

    ind = industry_label(template)
    link = build_job_admin_link(job_id)
    fired: List[Dict[str, Any]] = []

    for f in NOTE_FIELDS:
        old_v = (old_sr or {}).get(f)
        new_v = (new_sr or {}).get(f)
        if not is_empty_to_populated(old_v, new_v):
            continue
        ok = await _try_insert_debounce(
            db, tenant_id=tenant["id"], sr_id=sr_id,
            note_field=f, transition_kind=TRANSITION_KIND_PATCH,
        )
        if not ok:
            logger.info(
                "[notes-notifier] debounce hit tenant=%s sr=%s field=%s "
                "kind=patch_transition — skipping",
                tenant["id"], sr_id, f,
            )
            continue
        email_pack = build_patch_email(
            industry=ind, customer_name=customer_name,
            note_field=f, new_text=new_v, job_link=link,
        )
        sms_body = build_patch_sms(
            industry=ind, customer_name=customer_name,
            new_text=new_v, job_link=link,
        )
        result = await _dispatch_fanout(
            tenant_id=tenant["id"], recipients=recipients,
            email_subject=email_pack["subject"],
            email_html=email_pack["html"], sms_body=sms_body,
            send_email=send_email, send_sms=send_sms,
        )
        fired.append({"note_field": f, "results": result})

    return {"status": "ok", "fields_fired": fired}


async def notify_submit_finalize(
    *, db: Any, tenant: Dict[str, Any],
    sr_id: str, job_id: str, customer_name: str,
    template: Optional[str], new_sr: Dict[str, Any],
    send_email: Optional[Callable[..., Any]] = None,
    send_sms: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """Submit-time entry point.  Fires IFF at least one of the 3
    note fields is non-empty at submit.  Uses a single per-SR
    debounce key (``note_field="_submit"``, ``transition_kind=
    submit_finalize``) so a submit fires at most once per SR
    regardless of how many fields carry notes.
    """
    any_note = any((new_sr.get(f) or "").strip() for f in NOTE_FIELDS)
    if not any_note:
        return {"status": "no_notes", "fired": False}

    recipients = resolve_note_notification_recipients(tenant)
    if not recipients:
        logger.info("[notes-notifier:submit] no recipients tenant=%s",
                     tenant.get("id"))
        return {"status": "no_recipients", "fired": False}

    if send_email is None:
        from services.comms_email_adapter import send_email as _se
        send_email = _se
    if send_sms is None:
        from services.comms_sms_adapter import send_sms as _ss
        send_sms = _ss

    ok = await _try_insert_debounce(
        db, tenant_id=tenant["id"], sr_id=sr_id,
        note_field="_submit", transition_kind=TRANSITION_KIND_SUBMIT,
    )
    if not ok:
        logger.info(
            "[notes-notifier:submit] debounce hit tenant=%s sr=%s "
            "— skipping submit_finalize",
            tenant["id"], sr_id,
        )
        return {"status": "debounced", "fired": False}

    ind = industry_label(template)
    link = build_job_admin_link(job_id)
    email_pack = build_submit_email(
        industry=ind, customer_name=customer_name,
        new_sr=new_sr, job_link=link,
    )
    sms_body = build_submit_sms(
        industry=ind, customer_name=customer_name,
        new_sr=new_sr, job_link=link,
    )
    results = await _dispatch_fanout(
        tenant_id=tenant["id"], recipients=recipients,
        email_subject=email_pack["subject"],
        email_html=email_pack["html"], sms_body=sms_body,
        send_email=send_email, send_sms=send_sms,
    )
    return {"status": "ok", "fired": True, "results": results}
