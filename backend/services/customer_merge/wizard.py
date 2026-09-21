"""Phase M1 · Feb-2026 — Customer Merge Wizard service.

Wraps :func:`services.customer_merge.executor.merge_customers` with
the M1-spec contract:

* Single-pair merge (``primary`` × ``duplicate``) rather than the
  auto-merge module's multi-secondary bulk shape.
* Explicit ``field_choices`` payload — per-field ``primary`` /
  ``duplicate`` selection instead of ``newest_wins``.
* M1 error codes: 403 ``cross_tenant_merge_forbidden``, 409
  ``customer_already_deleted``, 400 ``same_customer_merge_forbidden``.
  Role gate (403 ``insufficient_role_for_customer_merge``) lives on
  the route (via :func:`utils.require_admin`).
* Extended re-parent surface — adds communications / messages /
  sms_messages / call_logs / warranty_contracts /
  intelligence_alerts / marketing_deliveries beyond the executor's
  6-collection default.
* Timeline note on the primary via a dedicated ``customer_notes``
  collection (Phase B ``note`` source consumes it — see
  :mod:`routers.communication_timeline`).

Cross-tenant guard is enforced BEFORE any writes. All 403s emit an
``audit_log`` breadcrumb so ops can trace attempted policy
violations later.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import db
from utils import new_id, now_iso

from services.customer_merge.executor import merge_customers


_FIELD_CHOICE_FIELDS = ("name", "email", "phone", "address")


# ─── Extended re-parent surface (in addition to the executor's 6 
# collections: jobs, quotes, payments, service_reports, estimates, 
# leads). These collections all carry a bare ``customer_id`` FK
# scoped by ``tenant_id`` — same shape as the executor's default set.
_EXTRA_REPARENT_COLLECTIONS = (
    # Messaging & comms
    "communications",
    "communications_log",
    "messages",
    "sms_messages",
    "communication_sends",
    "call_logs",
    "voicemails",
    "faxes",
    "notification_dispatch_log",
    "outbound_emails",
    # Marketing surface (Phase B timeline pulls these)
    "marketing_deliveries",
    "marketing_review_requests",
    "marketing_enrollments",
    # Alerts / intelligence
    "intelligence_alerts",
    "review_requests",
    # Contracts / warranties / agreements
    "warranty_contracts",
    "warranty_claims",
    "warranty_reminders_sent",
    "recurring_subscriptions",
    "customer_tasks",
    # Portal & CSAT
    "portal_appointments",
    "portal_chats",
    "csat_surveys",
    "csat_responses",
    "csat_pending",
    # Assets / equipment / properties
    "customer_equipment",
    "properties",
    "contacts",
    # Attachments / documents / activity trail (activity kept for
    # audit continuity; ``activity_log`` rows aren't destroyed, just
    # rewired so the primary's timeline shows historical events).
    "activity_log",
    "documents",
)


async def _reparent_extras(
    tenant_id: str, primary_id: str, duplicate_id: str,
) -> Dict[str, int]:
    """Rewire ``customer_id`` on every extended collection. Returns
    ``{coll: n_rewired}`` — collections with zero matches are
    omitted so the audit stays readable."""
    counts: Dict[str, int] = {}
    q = {"tenant_id": tenant_id, "customer_id": duplicate_id}
    for coll in _EXTRA_REPARENT_COLLECTIONS:
        n = await db[coll].count_documents(q)
        if not n:
            continue
        await db[coll].update_many(
            q, {"$set": {"customer_id": primary_id}},
        )
        counts[coll] = n
    return counts


async def _write_timeline_note(
    tenant_id: str, primary_id: str,
    duplicate_display_name: str, duplicate_id: str,
    author_id: str, merged_at: str,
) -> str:
    """Insert a system-merge note attached to the primary's timeline.
    The timeline builder (``routers.communication_timeline``) reads
    from ``customer_notes`` for the Phase B ``note`` source type."""
    nid = f"note_{new_id()}"
    body = (
        f"Merged with {duplicate_display_name or duplicate_id} on "
        f"{merged_at}. Duplicate ID: {duplicate_id}"
    )
    await db.customer_notes.insert_one({
        "id": nid,
        "tenant_id": tenant_id,
        "customer_id": primary_id,
        "author_id": author_id or "unknown",
        "note_kind": "system_merge",
        "body": body,
        "occurred_at": merged_at,
        "created_at": merged_at,
    })
    return nid


async def _audit_policy_violation(
    kind: str, actor_id: str, tenant_id: str, detail: Dict[str, Any],
) -> None:
    """Best-effort audit_log write for a rejected M1 attempt. Never
    raises — a failed audit must not block the 4xx response."""
    try:
        await db.audit_log.insert_one({
            "id": f"m1_deny_{new_id()}",
            "kind": kind,
            "actor_user_id": actor_id or "unknown",
            "tenant_id": tenant_id,
            "detail": detail or {},
            "created_at": now_iso(),
        })
    except Exception:  # pragma: no cover — audit is best-effort
        pass


class MergeWizardError(Exception):
    """Carries an HTTP status code + M1 error detail string. The
    router unwraps this and re-raises as ``HTTPException``."""

    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


async def execute_wizard_merge(
    tenant_id: str,
    primary_id: str,
    duplicate_id: str,
    field_choices: Optional[Dict[str, str]],
    actor_user_id: str,
) -> Dict[str, Any]:
    """Execute the M1 wizard-driven merge.

    Precondition validation happens BEFORE any writes; the audit
    trail for a rejected call lands in ``audit_log`` via
    :func:`_audit_policy_violation`.
    """
    choices = _normalise_choices(field_choices)

    # ─── Preflight ─────────────────────────────────────────────
    if not primary_id or not duplicate_id:
        raise MergeWizardError(422, "customer_ids_required")
    if primary_id == duplicate_id:
        await _audit_policy_violation(
            "customer_merge_denied", actor_user_id, tenant_id,
            {"reason": "same_customer_merge_forbidden",
                "primary_id": primary_id})
        raise MergeWizardError(400, "same_customer_merge_forbidden")

    primary = await db.customers.find_one(
        {"id": primary_id}, {"_id": 0})
    duplicate = await db.customers.find_one(
        {"id": duplicate_id}, {"_id": 0})
    if not primary:
        raise MergeWizardError(404, "primary_customer_not_found")
    if not duplicate:
        raise MergeWizardError(404, "duplicate_customer_not_found")

    # Cross-tenant guard — 3-way: primary vs duplicate vs the acting
    # session's tenant (all three must match).
    if primary.get("tenant_id") != duplicate.get("tenant_id") \
       or primary.get("tenant_id") != tenant_id:
        await _audit_policy_violation(
            "customer_merge_denied", actor_user_id, tenant_id,
            {"reason": "cross_tenant_merge_forbidden",
                "primary_id": primary_id,
                "duplicate_id": duplicate_id,
                "primary_tenant": primary.get("tenant_id"),
                "duplicate_tenant": duplicate.get("tenant_id"),
                "acting_tenant": tenant_id})
        raise MergeWizardError(403, "cross_tenant_merge_forbidden")

    # Already-deleted / already-merged guard.
    if _is_deleted(primary) or _is_deleted(duplicate) \
       or primary.get("merged_into") or duplicate.get("merged_into"):
        await _audit_policy_violation(
            "customer_merge_denied", actor_user_id, tenant_id,
            {"reason": "customer_already_deleted",
                "primary_id": primary_id,
                "duplicate_id": duplicate_id,
                "primary_deleted": _is_deleted(primary),
                "duplicate_deleted": _is_deleted(duplicate),
                "primary_merged_into": primary.get("merged_into"),
                "duplicate_merged_into": duplicate.get("merged_into")})
        raise MergeWizardError(409, "customer_already_deleted")

    # ─── Snapshot BEFORE any mutation ──────────────────────────
    duplicate_snapshot = dict(duplicate)  # deep-enough copy for audit
    duplicate_display_name = (
        duplicate.get("name") or duplicate.get("email")
        or duplicate.get("phone") or duplicate_id
    )

    # ─── Apply field_choices to primary FIRST ───────────────────
    # The executor uses ``newest_wins`` reconciliation. By writing
    # the caller's choices onto the primary AND bumping its
    # ``updated_at`` to now, the executor will keep the primary's
    # (now-user-chosen) values on all four M1 fields.
    now = now_iso()
    patch: Dict[str, Any] = {}
    for field in _FIELD_CHOICE_FIELDS:
        if choices.get(field) == "duplicate":
            patch[field] = duplicate.get(field)
    if patch:
        patch["updated_at"] = now
        await db.customers.update_one(
            {"id": primary_id, "tenant_id": tenant_id},
            {"$set": patch},
        )
    else:
        # Even with all-primary choices, bump ``updated_at`` so
        # newest-wins prefers the primary for every non-M1 field
        # too (name-of-record contract: primary wins).
        await db.customers.update_one(
            {"id": primary_id, "tenant_id": tenant_id},
            {"$set": {"updated_at": now}},
        )

    # ─── Delegate to the executor ──────────────────────────────
    exec_result = await merge_customers(
        tenant_id=tenant_id,
        primary_id=primary_id,
        secondary_ids=[duplicate_id],
        strategy="newest_wins",
        initiated_by=actor_user_id or "unknown",
        dry_run=False,
        match_type="manual_wizard",
        confidence="manual",
    )

    # ─── Extended re-parent ────────────────────────────────────
    extra_counts = await _reparent_extras(
        tenant_id, primary_id, duplicate_id,
    )

    # ─── Timeline note on primary (Phase B ``note`` source) ────
    note_id = await _write_timeline_note(
        tenant_id, primary_id,
        duplicate_display_name, duplicate_id,
        actor_user_id, now,
    )

    # ─── Extended audit row with duplicate_snapshot + choices ──
    reparent_counts = dict(exec_result.get("related_records_rewired") or {})
    reparent_counts.update(extra_counts)
    from services.customer_merge.audit import write_merge_audit
    audit_id = await write_merge_audit(
        tenant_id=tenant_id,
        primary_id=primary_id,
        secondary_ids=[duplicate_id],
        initiated_by=actor_user_id or "unknown",
        match_type="manual_wizard",
        confidence="manual",
        fields_reconciled=exec_result.get("fields_reconciled") or {},
        empty_fields_filled=exec_result.get("empty_fields_filled") or {},
        related_records_rewired=reparent_counts,
        duplicate_snapshots=[duplicate_snapshot],
        field_choices=choices,
        merge_source="wizard",
    )

    # Belt-and-braces: ensure the duplicate carries the M1-named
    # legacy field alias so downstream tooling that queries
    # ``merged_into_customer_id`` also works. The executor already
    # sets ``merged_into`` on the duplicate.
    await db.customers.update_one(
        {"id": duplicate_id, "tenant_id": tenant_id},
        {"$set": {"merged_into_customer_id": primary_id}},
    )

    return {
        "ok": True,
        "primary_customer_id": primary_id,
        "duplicate_customer_id": duplicate_id,
        "reparent_counts": reparent_counts,
        "field_choices": choices,
        "merged_at": now,
        "audit_log_id": audit_id,
        "timeline_note_id": note_id,
    }


def _normalise_choices(
    choices: Optional[Dict[str, str]],
) -> Dict[str, str]:
    """Fill missing fields with ``"primary"`` (default) and reject
    unknown / mistyped values."""
    out: Dict[str, str] = {}
    src = choices or {}
    for f in _FIELD_CHOICE_FIELDS:
        v = (src.get(f) or "primary").lower().strip()
        if v not in ("primary", "duplicate"):
            v = "primary"
        out[f] = v
    return out


def _is_deleted(customer: Dict[str, Any]) -> bool:
    return bool(
        customer.get("is_deleted") is True
        or customer.get("deleted_at")
    )
