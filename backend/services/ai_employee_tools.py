"""Task RR · Feb 2026 — AI Employee tool registry + dispatcher.

Read-only tool layer for the customer-facing AI Employees (Skedra +
Billy) and admin-facing personas. Ships:

* An 8-tool registry (see ``TOOL_REGISTRY``) — every tool is a plain
  async function that takes ``tenant_id`` + kwargs and returns a JSON-
  safe dict / list. No side effects. No writes.

* An access-control matrix per tool:
    - ``customer_scoped``: the tool auto-injects the caller's own
      ``customer_id`` and refuses to serve any other customer's data.
    - ``tenant_all``: the tool has no per-customer scope and can be
      called by an admin-scope persona OR by a customer-scope persona
      whose PERSONA has been flipped to ``tenant_all`` by a
      super_admin. Customer-callers of a ``customer_scoped`` persona
      are ALWAYS denied ``tenant_all`` tools regardless.

* Rate limiting — two overlapping windows enforced against the
  ``ai_tool_calls`` collection:
    - per-persona: 100 calls / 60s within a tenant.
    - per-caller (customer or admin): 30 calls / 60s across all
      personas.

* Audit log — every dispatch writes exactly one ``ai_tool_calls`` row
  regardless of outcome, so operators can see refused / rate-limited
  calls too.  A TTL index on ``created_at`` (90 days) is created on
  first use.

* Structured errors — every failure path returns
  ``{"error": "<code>", "detail": "<human>"}`` that the LLM can
  politely surface in its next turn. The dispatcher NEVER raises to
  the conversation loop.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("ai_employee_tools")

# ────────────────────────────────────────────────────────────────
# Scope enum values — kept as bare strings to avoid enum import in
# hot paths and to match Mongo doc field values 1:1.
# ────────────────────────────────────────────────────────────────
SCOPE_TENANT_ALL = "tenant_all"
SCOPE_CUSTOMER = "customer_scoped"
# Feb-2026 · MARCO · Sub-phase B — orchestrator-only scope.  Only
# personas seeded with ``orchestrator=True`` may invoke tools tagged
# with this scope.  Currently there is exactly one such tool:
# ``delegate_task``.  The scope is orthogonal to
# ``read_access_scope`` (a persona can be ``tenant_all`` OR
# ``customer_scoped`` AND independently ``orchestrator=True``).
SCOPE_ORCHESTRATOR = "orchestrator"
VALID_SCOPES = frozenset(
    {SCOPE_TENANT_ALL, SCOPE_CUSTOMER, SCOPE_ORCHESTRATOR},
)

# Rate-limit windows (calls / seconds).
PER_PERSONA_LIMIT = (100, 60)
PER_CALLER_LIMIT = (30, 60)

# Audit retention (days).
AUDIT_TTL_DAYS = 90


@dataclass
class ToolSpec:
    name: str
    description: str
    params: List[str]                                 # informational only
    handler: Callable[..., Awaitable[Any]]
    required_scope: str                               # SCOPE_TENANT_ALL / SCOPE_CUSTOMER / SCOPE_ORCHESTRATOR
    # True if the tool needs a ``customer_id`` argument (either
    # provided or auto-injected from the caller's session).
    needs_customer_id: bool
    # Feb-2026 · MARCO · Sub-phase B — orchestrator tools
    # (currently ``delegate_task``) need extra conversation state
    # that the standard read-only tools don't carry: the
    # conversation id, the invoking persona doc, the requesting
    # admin user doc, etc.  When ``needs_conversation_context`` is
    # True the dispatcher expects the caller to pass a
    # ``conversation_context`` dict alongside the tool args; the
    # handler receives it as a kwarg.  Read-only tools default to
    # False and never see the extra state.
    needs_conversation_context: bool = False


# ═══════════════════════════════════════════════════════════════════
# Tool handlers — all read-only, all tenant-scoped by first arg.
# ═══════════════════════════════════════════════════════════════════

async def _t_lookup_customer(tenant_id: str, *, customer_id: Optional[str] = None,
                                    query: Optional[str] = None) -> Any:
    """Return a customer profile — public fields only. Accepts either
    an exact ``customer_id`` or a free-text ``query`` matching name /
    email / phone. Returns the first hit or an ``error`` payload."""
    from config import db
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if customer_id:
        q["id"] = customer_id
    elif query and isinstance(query, str):
        # Very light-touch match — case-insensitive substring on the
        # 3 identifying fields. The tool is read-only so a false hit
        # only surfaces public info anyway.
        rx = {"$regex": query.strip(), "$options": "i"}
        q["$or"] = [{"name": rx}, {"email": rx}, {"phone": rx}]
    else:
        return {"error": "bad_args", "detail": "customer_id or query required"}
    doc = await db.customers.find_one(q, {"_id": 0})
    if not doc:
        return {"error": "not_found", "detail": "no customer matches"}
    return {
        "id": doc.get("id"),
        "name": doc.get("name"),
        "email": doc.get("email"),
        "phone": doc.get("phone"),
        "address": doc.get("address"),
        "tags": doc.get("tags") or [],
        "is_active": doc.get("is_active", True),
        "credits_balance_cents": int(doc.get("credits_balance_cents") or 0),
    }


async def _t_lookup_invoices(tenant_id: str, *, customer_id: str,
                                    status: Optional[str] = None,
                                    limit: int = 12) -> Any:
    from config import db
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 12
    q: Dict[str, Any] = {"tenant_id": tenant_id, "customer_id": customer_id,
                              "doc_type": "invoice"}
    if status:
        q["payment_status"] = status
    rows = await db.quotes.find(
        q, {"_id": 0, "id": 1, "number": 1, "total": 1, "total_cents": 1,
              "amount_paid": 1, "due_date": 1, "payment_status": 1,
              "paid_at": 1, "credits_applied_cents": 1, "created_at": 1},
    ).sort("created_at", -1).limit(limit).to_list(limit)
    today = datetime.now(timezone.utc).date()
    out: List[Dict[str, Any]] = []
    for r in rows:
        due = r.get("due_date") or ""
        past_due = 0
        if due and (r.get("payment_status") or "") != "paid":
            try:
                d = datetime.strptime(due[:10], "%Y-%m-%d").date()
                past_due = max(0, (today - d).days)
            except (TypeError, ValueError):
                pass
        out.append({
            "id": r.get("id"),
            "number": r.get("number"),
            "amount": r.get("total"),
            "credit_applied_cents": int(r.get("credits_applied_cents") or 0),
            "status": r.get("payment_status"),
            "due_date": due,
            "paid_at": r.get("paid_at"),
            "past_due_days": past_due,
        })
    return out


async def _t_lookup_invoice_detail(tenant_id: str, *, invoice_id: str,
                                          customer_id: Optional[str] = None) -> Any:
    """Full invoice detail. If ``customer_id`` is provided, the tool
    refuses to serve invoices that don't belong to that customer —
    which is the customer-scoped guard for Billy."""
    from config import db
    q: Dict[str, Any] = {"tenant_id": tenant_id, "id": invoice_id,
                              "doc_type": "invoice"}
    if customer_id:
        q["customer_id"] = customer_id
    doc = await db.quotes.find_one(q, {"_id": 0})
    if not doc:
        return {"error": "not_found", "detail": "no invoice for this customer"}
    return {
        "id": doc.get("id"),
        "number": doc.get("number"),
        "customer_id": doc.get("customer_id"),
        "line_items": doc.get("line_items") or [],
        "subtotal": doc.get("subtotal"),
        "tax": doc.get("tax"),
        "total": doc.get("total"),
        "amount_paid": doc.get("amount_paid"),
        "credit_applied_cents": int(doc.get("credits_applied_cents") or 0),
        "balance": round(float(doc.get("total") or 0)
                            - float(doc.get("amount_paid") or 0), 2),
        "status": doc.get("payment_status"),
        "due_date": doc.get("due_date"),
        "notes": doc.get("notes"),
        "pdf_url": doc.get("pdf_url"),
    }


async def _t_lookup_next_visit(tenant_id: str, *, customer_id: str) -> Any:
    from config import db
    today = datetime.now(timezone.utc).date().isoformat()
    job = await db.jobs.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id,
          "status": {"$in": ["scheduled", "active", "pending", "requested"]},
          "scheduled_start": {"$gte": f"{today}T00:00:00+00:00"}},
        {"_id": 0, "id": 1, "scheduled_start": 1, "service_type": 1,
          "job_type": 1, "technician_id": 1, "technician_name": 1,
          "title": 1, "notes": 1, "checklist_summary": 1},
        sort=[("scheduled_start", 1)],
    )
    if not job:
        return None
    return {
        "id": job.get("id"),
        "scheduled_start": job.get("scheduled_start"),
        "service_type": job.get("service_type") or job.get("job_type"),
        "technician_name": job.get("technician_name"),
        "checklist_summary": job.get("checklist_summary"),
        "notes": job.get("notes"),
    }


async def _t_lookup_service_history(tenant_id: str, *, customer_id: str,
                                          limit: int = 5) -> Any:
    from config import db
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 5
    rows = await db.jobs.find(
        {"tenant_id": tenant_id, "customer_id": customer_id,
          "status": "completed"},
        {"_id": 0, "id": 1, "scheduled_start": 1, "completed_at": 1,
          "service_type": 1, "job_type": 1, "technician_name": 1,
          "chemicals_summary": 1, "photo_ids": 1, "invoice_id": 1},
    ).sort("scheduled_start", -1).limit(limit).to_list(limit)
    return [{
        "scheduled_start": r.get("scheduled_start") or r.get("completed_at"),
        "service_type": r.get("service_type") or r.get("job_type"),
        "technician_name": r.get("technician_name"),
        "chemicals_summary": r.get("chemicals_summary"),
        "photos_count": len(r.get("photo_ids") or []),
        "invoice_id": r.get("invoice_id"),
    } for r in rows]


async def _t_lookup_schedule(tenant_id: str, *, date_from: str, date_to: str,
                                    technician_id: Optional[str] = None) -> Any:
    """Tenant-wide schedule digest — NEVER returns any customer PII.
    tenant_all-only."""
    from config import db
    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "scheduled_start": {"$gte": f"{date_from[:10]}T00:00:00+00:00",
                                "$lte": f"{date_to[:10]}T23:59:59+00:00"},
    }
    if technician_id:
        q["technician_id"] = technician_id
    rows = await db.jobs.find(
        q, {"_id": 0, "scheduled_start": 1, "technician_id": 1,
             "technician_name": 1},
    ).sort("scheduled_start", 1).to_list(2000)
    by_day: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        day = str(r.get("scheduled_start") or "")[:10]
        if not day:
            continue
        d = by_day.setdefault(day, {"date": day, "visit_count": 0,
                                              "technicians_working": set(),
                                              "first_visit_time": None,
                                              "last_visit_time": None})
        d["visit_count"] += 1
        if r.get("technician_name"):
            d["technicians_working"].add(r["technician_name"])
        ts = r.get("scheduled_start")
        if ts:
            if d["first_visit_time"] is None or ts < d["first_visit_time"]:
                d["first_visit_time"] = ts
            if d["last_visit_time"] is None or ts > d["last_visit_time"]:
                d["last_visit_time"] = ts
    out = []
    for _, d in sorted(by_day.items()):
        d["technicians_working"] = sorted(d["technicians_working"])
        out.append(d)
    return out


async def _t_lookup_balance(tenant_id: str, *, customer_id: str) -> Any:
    from config import db
    today = datetime.now(timezone.utc).date()
    invoices = await db.quotes.find(
        {"tenant_id": tenant_id, "customer_id": customer_id,
          "doc_type": "invoice"},
        {"_id": 0, "total": 1, "amount_paid": 1, "due_date": 1,
          "payment_status": 1},
    ).to_list(2000)
    unpaid_total = 0.0
    past_due = 0.0
    unpaid_count = 0
    oldest_days = 0
    for inv in invoices:
        if (inv.get("payment_status") or "").lower() == "paid":
            continue
        outstanding = round(float(inv.get("total") or 0)
                                 - float(inv.get("amount_paid") or 0), 2)
        if outstanding <= 0:
            continue
        unpaid_count += 1
        unpaid_total += outstanding
        due = inv.get("due_date") or ""
        try:
            d = datetime.strptime(due[:10], "%Y-%m-%d").date()
            days = (today - d).days
            if days > 0:
                past_due += outstanding
                if days > oldest_days:
                    oldest_days = days
        except (TypeError, ValueError):
            pass
    cust = await db.customers.find_one(
        {"tenant_id": tenant_id, "id": customer_id},
        {"_id": 0, "credits_balance_cents": 1},
    ) or {}
    return {
        "unpaid_total_cents": int(round(unpaid_total * 100)),
        "past_due_cents": int(round(past_due * 100)),
        "credit_balance_cents": int(cust.get("credits_balance_cents") or 0),
        "oldest_unpaid_days": oldest_days,
        "count_unpaid_invoices": unpaid_count,
    }


async def _t_search_customers(tenant_id: str, *, query: str,
                                     limit: int = 10) -> Any:
    """tenant_all-only. Redacted output — no full contact info."""
    from config import db
    if not query or not isinstance(query, str) or len(query.strip()) < 2:
        return {"error": "bad_args",
                  "detail": "query must be at least 2 characters"}
    try:
        limit = max(1, min(int(limit), 10))
    except (TypeError, ValueError):
        limit = 10
    rx = {"$regex": query.strip(), "$options": "i"}
    rows = await db.customers.find(
        {"tenant_id": tenant_id,
          "$or": [{"name": rx}, {"email": rx}, {"phone": rx},
                    {"address": rx}]},
        {"_id": 0, "id": 1, "name": 1, "address": 1, "phone": 1,
          "is_active": 1},
    ).limit(limit).to_list(limit)
    def _short(addr: Any) -> str:
        s = str(addr or "").strip()
        return (s[:40] + "…") if len(s) > 40 else s
    def _last4(phone: Any) -> str:
        digits = "".join(c for c in str(phone or "") if c.isdigit())
        return digits[-4:] if len(digits) >= 4 else ""
    return [{
        "id": r.get("id"),
        "name": r.get("name"),
        "address_short": _short(r.get("address")),
        "phone_last4": _last4(r.get("phone")),
        "is_active": r.get("is_active", True),
    } for r in rows]


# ═══════════════════════════════════════════════════════════════════
# Feb-2026 · MARCO · Sub-phase B — orchestrator tools.
#
# ``delegate_task`` — the ONLY tool with ``SCOPE_ORCHESTRATOR``.
# Ships MARCO's ability to hand off admin requests to a specialist
# persona.  Guard rail order (all in ``dispatch_tool``):
#
#   1. Scope guard: invoking persona must carry ``orchestrator=True``.
#   2. Target guard: target_employee_key must exist, be admin
#      audience, and NOT itself be an orchestrator (blocks
#      delegate-to-orchestrator loops even before the target's
#      system prompt tells them not to re-delegate).
#
# On success the tool appends a system-style transcript entry to
# the CURRENT conversation (so the audit trail shows the hand-off),
# runs the target persona's turn against the SAME conversation
# history + brand_brain, persists the target's reply stamped with
# ``sender_employee_id = target.id`` + ``delegated_by_employee_id
# = invoker.id``, and returns a compact summary to MARCO's tool
# loop.
# ═══════════════════════════════════════════════════════════════════
async def _t_delegate_task(
    tenant_id: str,
    *,
    target_employee_key: str,
    task_description: str,
    context: Optional[Dict[str, Any]] = None,
    conversation_context: Dict[str, Any],
) -> Any:
    """Orchestrator delegation.  See module-level block-comment for
    guard-rail order and side-effect summary."""
    from config import db as _db

    cid = conversation_context.get("conversation_id")
    invoker = conversation_context.get("invoker_persona") or {}
    ctx_tenant = conversation_context.get("tenant_id") or tenant_id
    _user = conversation_context.get("user") or {}

    if not cid or not invoker.get("id"):
        return {
            "error": "bad_context",
            "detail": "conversation_context missing conversation_id or"
                        " invoker_persona",
        }
    if not target_employee_key:
        return {
            "error": "bad_args",
            "detail": "target_employee_key required",
        }
    if not task_description:
        return {
            "error": "bad_args",
            "detail": "task_description required",
        }

    # ── Target guard ───────────────────────────────────────────
    target = await _db.ai_employees.find_one(
        {"tenant_id": ctx_tenant, "key": target_employee_key,
          "$or": [
              {"audience": "admin"},
              {"audience": {"$exists": False}},
          ]},
        {"_id": 0},
    )
    if not target:
        return {
            "error": "unknown_target",
            "detail": (
                f"no admin-audience AI employee with key "
                f"{target_employee_key!r}"
            ),
        }
    if target.get("orchestrator") is True:
        return {
            "error": "cannot_delegate_to_orchestrator",
            "detail": (
                "orchestrators cannot delegate to other"
                " orchestrators — the delegation chain must"
                " terminate on a specialist"
            ),
        }
    if target.get("active") is False:
        return {
            "error": "target_inactive",
            "detail": (
                f"target persona {target_employee_key!r} is"
                f" disabled — the admin needs to re-enable it"
                f" from the AI Employees dock first"
            ),
        }

    # ── System transcript entry (visible to both participants) ─
    from datetime import datetime as _dt, timezone as _tz
    def _now() -> str:
        return _dt.now(_tz.utc).isoformat().replace("+00:00", "Z")
    def _nid() -> str:
        # Match the utils.new_id shape without importing from utils
        # here (keeps the tool file free of routers/utils cycles).
        return hashlib.sha1(f"{_now()}-{_dt.now(_tz.utc).timestamp()}".encode()).hexdigest()[:24]

    sys_msg = {
        "id": _nid(), "tenant_id": ctx_tenant,
        "conversation_id": cid,
        "employee_id": invoker.get("id"),
        "sender_employee_id": invoker.get("id"),
        "role": "system",
        "text": (
            f"[{invoker.get('name') or invoker.get('key')}]"
            f" delegated to [{target.get('name') or target.get('key')}]"
            f" — {task_description}"
        ),
        "kind": "delegation_handoff",
        "delegated_to_employee_id": target["id"],
        "created_at": _now(),
    }
    await _db.ai_employee_messages.insert_one(sys_msg)

    # ── Ensure target is a participant on the conversation ────
    await _db.ai_employee_conversations.update_one(
        {"id": cid, "tenant_id": ctx_tenant},
        {"$addToSet": {"participant_employee_ids": target["id"]}},
    )

    # ── Build target's system prompt with delegation preamble ─
    from routers.ai_employees import (
        _get_brand_brain, _brand_brain_summary, _llm_chat,
    )
    bb = await _get_brand_brain(ctx_tenant)
    ctx_dump = json.dumps(context or {}, default=str)[:600]
    preamble = (
        f"You are being delegated to by "
        f"{invoker.get('name') or invoker.get('key')}. "
        f"Task: {task_description}. "
        f"Context from {invoker.get('name') or invoker.get('key')}: "
        f"{ctx_dump}. "
        f"Respond directly to the admin — do not re-delegate."
    )
    target_system_prompt = (
        f"{preamble}\n\n{target['system_prompt']}\n\n"
        f"— Shared brand brain —\n{_brand_brain_summary(bb)}"
    )

    # ── Fetch full conversation transcript for shared context ─
    history = await _db.ai_employee_messages.find(
        {"tenant_id": ctx_tenant, "conversation_id": cid,
          "role": {"$in": ["user", "assistant", "system"]}},
        {"_id": 0, "role": 1, "text": 1},
    ).sort("created_at", 1).to_list(50)

    # ── Invoke target persona ─────────────────────────────────
    r = await _llm_chat(target_system_prompt, task_description, history)
    reply_text = (r.get("text") or "").strip() or (
        "[stub] " + task_description[:200]
    )

    # ── Persist target's reply stamped with its own identity ──
    reply_msg = {
        "id": _nid(), "tenant_id": ctx_tenant,
        "conversation_id": cid,
        "employee_id": target["id"],
        "sender_employee_id": target["id"],
        "role": "assistant",
        "text": reply_text,
        "provider": r.get("provider") or "stub",
        "delegated_by_employee_id": invoker.get("id"),
        "kind": "delegation_reply",
        "created_at": _now(),
    }
    await _db.ai_employee_messages.insert_one(reply_msg)

    # ── Bump conversation counters for the two extra messages ─
    await _db.ai_employee_conversations.update_one(
        {"id": cid, "tenant_id": ctx_tenant},
        {"$set": {"updated_at": _now()},
          "$inc": {"message_count": 2}},
    )

    return {
        "delegated_to": target.get("name") or target.get("key"),
        "delegated_to_key": target.get("key"),
        "delegated_to_employee_id": target["id"],
        "target_reply_excerpt": reply_text[:400],
    }


# ═══════════════════════════════════════════════════════════════════
# Registry.
# ═══════════════════════════════════════════════════════════════════
TOOL_REGISTRY: Dict[str, ToolSpec] = {
    "lookup_customer": ToolSpec(
        name="lookup_customer",
        description="Get a customer profile (name, address, phone, email, "
                        "tags, active status, credit balance) by customer_id or "
                        "free-text query.",
        params=["customer_id?", "query?"],
        handler=_t_lookup_customer,
        required_scope=SCOPE_CUSTOMER,     # customer-scoped personas may look
                                                     # up their OWN customer only.
        needs_customer_id=False,
    ),
    "lookup_invoices": ToolSpec(
        name="lookup_invoices",
        description="Recent invoices for a customer (last 12 by default, "
                        "max 20). Optional status filter (paid/unpaid).",
        params=["customer_id", "status?", "limit?"],
        handler=_t_lookup_invoices,
        required_scope=SCOPE_CUSTOMER,
        needs_customer_id=True,
    ),
    "lookup_invoice_detail": ToolSpec(
        name="lookup_invoice_detail",
        description="Full invoice detail — line items, totals, credit "
                        "applied, balance, notes, PDF link.",
        params=["invoice_id", "customer_id?"],
        handler=_t_lookup_invoice_detail,
        required_scope=SCOPE_CUSTOMER,
        needs_customer_id=False,          # dispatcher injects customer_id for
                                                     # customer-scoped personas to enforce
                                                     # per-invoice ownership.
    ),
    "lookup_next_visit": ToolSpec(
        name="lookup_next_visit",
        description="Next upcoming scheduled visit for a customer, or null.",
        params=["customer_id"],
        handler=_t_lookup_next_visit,
        required_scope=SCOPE_CUSTOMER,
        needs_customer_id=True,
    ),
    "lookup_service_history": ToolSpec(
        name="lookup_service_history",
        description="Last N completed service visits for a customer "
                        "(default 5, max 20).",
        params=["customer_id", "limit?"],
        handler=_t_lookup_service_history,
        required_scope=SCOPE_CUSTOMER,
        needs_customer_id=True,
    ),
    "lookup_balance": ToolSpec(
        name="lookup_balance",
        description="Unpaid balance, past-due, credit balance, oldest "
                        "past-due days for a customer.",
        params=["customer_id"],
        handler=_t_lookup_balance,
        required_scope=SCOPE_CUSTOMER,
        needs_customer_id=True,
    ),
    "lookup_schedule": ToolSpec(
        name="lookup_schedule",
        description="Tenant-wide schedule summary by day for a date "
                        "range. NEVER returns customer names or PII. "
                        "tenant_all-only.",
        params=["date_from", "date_to", "technician_id?"],
        handler=_t_lookup_schedule,
        required_scope=SCOPE_TENANT_ALL,
        needs_customer_id=False,
    ),
    "search_customers": ToolSpec(
        name="search_customers",
        description="Fuzzy customer search (redacted output — phone "
                        "last-4 only, address truncated). tenant_all-only.",
        params=["query", "limit?"],
        handler=_t_search_customers,
        required_scope=SCOPE_TENANT_ALL,
        needs_customer_id=False,
    ),
    # ─── Feb-2026 · MARCO · Sub-phase B · orchestrator tool ────
    "delegate_task": ToolSpec(
        name="delegate_task",
        description=(
            "Hand off the current admin request to a specialist AI "
            "employee.  Only MARCO (the orchestrator) can call this "
            "tool.  ``target_employee_key`` must be one of the "
            "specialist personas (casey / emmie / buddy / vizzy / "
            "dexter / soshie / scouty / commet).  ``task_description``"
            " is a one-sentence brief for the specialist.  "
            "``context`` is an optional dict with any snippets the "
            "specialist should see (excerpts from the admin's "
            "message, ids, etc.)."
        ),
        params=["target_employee_key", "task_description", "context?"],
        handler=_t_delegate_task,
        required_scope=SCOPE_ORCHESTRATOR,
        needs_customer_id=False,
        needs_conversation_context=True,
    ),
}


# ═══════════════════════════════════════════════════════════════════
# Rate limiting + audit.
# ═══════════════════════════════════════════════════════════════════
_indexes_ready = False


async def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        from config import db
        # TTL on created_at → auto-purge after AUDIT_TTL_DAYS.
        await db.ai_tool_calls.create_index(
            "created_at",
            expireAfterSeconds=AUDIT_TTL_DAYS * 24 * 60 * 60,
        )
        # Support fast per-persona / per-caller counts.
        await db.ai_tool_calls.create_index([
            ("tenant_id", 1), ("persona_id", 1), ("created_at", -1)])
        await db.ai_tool_calls.create_index([
            ("tenant_id", 1),
            ("called_by_customer_id", 1), ("created_at", -1)])
        _indexes_ready = True
    except Exception as exc:                                        # noqa: BLE001
        log.warning("ai_tool_calls index create skipped: %s", exc)


async def _count_since(query: Dict[str, Any], seconds: int) -> int:
    from config import db
    since = (datetime.now(timezone.utc)
                 - timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
    return await db.ai_tool_calls.count_documents(
        {**query, "created_at": {"$gte": since}},
    )


async def _audit(row: Dict[str, Any]) -> None:
    from config import db
    row["created_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        await db.ai_tool_calls.insert_one(row)
    except Exception as exc:                                        # noqa: BLE001
        log.warning("ai_tool_calls insert failed: %s", exc)


def _args_hash(args: Dict[str, Any]) -> str:
    try:
        s = json.dumps(args or {}, sort_keys=True, default=str)
    except Exception:
        s = str(args)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════
# Public dispatch entrypoint.
# ═══════════════════════════════════════════════════════════════════
async def dispatch_tool(
    *,
    tenant_id: str,
    persona: Dict[str, Any],
    caller_kind: str,                     # "customer" or "admin"
    caller_id: Optional[str] = None,     # user id (admin) or None (customer)
    caller_customer_id: Optional[str] = None,
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    # Feb-2026 · MARCO · Sub-phase B — extra state for orchestrator
    # tools.  ONLY consumed when the tool's ``needs_conversation_context``
    # flag is True; ignored for read-only tools.  Keeps the read-only
    # dispatch path byte-identical to pre-B behavior.
    conversation_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Single entrypoint — every tool call goes through here.

    Returns a dict with either the tool result under ``result`` OR a
    structured error under ``error`` (never raises). Every call is
    audited to ``ai_tool_calls`` including refusals and rate limits.
    """
    await _ensure_indexes()
    args = dict(args or {})
    persona_id = persona.get("id") or ""
    persona_scope = (persona.get("read_access_scope") or SCOPE_CUSTOMER).strip()
    persona_is_orchestrator = bool(persona.get("orchestrator"))

    audit_row: Dict[str, Any] = {
        "id": _args_hash(f"{persona_id}:{tool_name}:{datetime.now(timezone.utc).timestamp()}"),
        "tenant_id": tenant_id,
        "persona_id": persona_id,
        "persona_key": persona.get("key"),
        "persona_scope": persona_scope,
        "persona_is_orchestrator": persona_is_orchestrator,
        "tool_name": tool_name,
        "args_hash": _args_hash(args),
        "called_by_user_id": caller_id if caller_kind == "admin" else None,
        "called_by_customer_id": (caller_customer_id
                                          if caller_kind == "customer" else None),
    }

    # ── Tool existence ──────────────────────────────────────────
    spec = TOOL_REGISTRY.get(tool_name)
    if not spec:
        audit_row["result_status"] = "unknown_tool"
        await _audit(audit_row)
        return {"error": "unknown_tool", "detail": f"tool '{tool_name}' does not exist"}

    # ── Feb-2026 · MARCO · Sub-phase B · Orchestrator scope guard.
    # ``delegate_task`` is the only tool tagged SCOPE_ORCHESTRATOR
    # today.  Non-orchestrator personas are refused with a clear
    # message the LLM can politely surface.  Runs BEFORE the
    # read-only scope guard below so a customer-scoped, non-
    # orchestrator persona hits the orchestrator refusal (which is
    # the tighter, more informative message) instead of the
    # tenant_all refusal.
    if spec.required_scope == SCOPE_ORCHESTRATOR:
        if not persona_is_orchestrator:
            audit_row["result_status"] = "permission_denied"
            audit_row["result_summary"] = (
                "orchestrator tool from non-orchestrator persona"
            )
            await _audit(audit_row)
            return {
                "error": "permission_denied",
                "detail": (
                    "Only the executive orchestrator (MARCO) can"
                    " delegate to other AI employees.  This persona"
                    " must respond directly."
                ),
            }
        # Also refuse a customer-scoped orchestrator caller — the
        # only orchestrator persona (MARCO) is admin-audience, but
        # defence-in-depth against a mis-configured seed.
        if caller_kind == "customer":
            audit_row["result_status"] = "permission_denied"
            audit_row["result_summary"] = (
                "orchestrator tool from customer caller"
            )
            await _audit(audit_row)
            return {
                "error": "permission_denied",
                "detail": (
                    "delegation is an admin-only capability"
                ),
            }

    # ── Persona-scope × tool-scope guard ────────────────────────
    # A customer-scoped persona can only invoke tools with
    # SCOPE_CUSTOMER (never tenant_all).
    if persona_scope == SCOPE_CUSTOMER and spec.required_scope == SCOPE_TENANT_ALL:
        audit_row["result_status"] = "permission_denied"
        audit_row["result_summary"] = "tenant_all tool from customer_scoped persona"
        await _audit(audit_row)
        return {"error": "permission_denied",
                  "detail": "this tool requires tenant-wide access, which "
                                "this AI is not authorized for"}

    # ── Cross-customer guard (customer-scoped personas only) ────
    if persona_scope == SCOPE_CUSTOMER and spec.required_scope == SCOPE_CUSTOMER:
        # Auto-inject the caller's own customer_id when the tool
        # needs one; refuse if the LLM tried to specify a different id.
        want = args.get("customer_id")
        if want and caller_customer_id and want != caller_customer_id:
            audit_row["result_status"] = "permission_denied"
            audit_row["result_summary"] = "cross-customer read attempted"
            await _audit(audit_row)
            return {"error": "permission_denied",
                      "detail": "cannot look up another customer's data"}
        if spec.needs_customer_id and not want and caller_customer_id:
            args["customer_id"] = caller_customer_id
        # For lookup_invoice_detail (needs_customer_id=False but
        # supports it), inject to enforce per-invoice ownership.
        if (tool_name == "lookup_invoice_detail"
                and not args.get("customer_id") and caller_customer_id):
            args["customer_id"] = caller_customer_id

    # ── Rate limits ─────────────────────────────────────────────
    persona_count = await _count_since(
        {"tenant_id": tenant_id, "persona_id": persona_id},
        PER_PERSONA_LIMIT[1],
    )
    if persona_count >= PER_PERSONA_LIMIT[0]:
        audit_row["result_status"] = "rate_limited_persona"
        await _audit(audit_row)
        return {"error": "rate_limited",
                  "detail": "I'm looking things up faster than I should — "
                                "please try again in a moment"}
    if caller_kind == "customer" and caller_customer_id:
        caller_count = await _count_since(
            {"tenant_id": tenant_id,
              "called_by_customer_id": caller_customer_id},
            PER_CALLER_LIMIT[1],
        )
        if caller_count >= PER_CALLER_LIMIT[0]:
            audit_row["result_status"] = "rate_limited_caller"
            await _audit(audit_row)
            return {"error": "rate_limited",
                      "detail": "too many lookups in the last minute — "
                                    "please try again in a moment"}

    # ── Execute ─────────────────────────────────────────────────
    # Feb-2026 · MARCO · Sub-phase B — inject conversation_context
    # kwarg for orchestrator tools that need it.  Other tools
    # never see the extra state.
    handler_kwargs: Dict[str, Any] = dict(args)
    if spec.needs_conversation_context:
        if conversation_context is None:
            audit_row["result_status"] = "bad_context"
            audit_row["result_summary"] = (
                "orchestrator tool called without conversation_context"
            )
            await _audit(audit_row)
            return {
                "error": "bad_context",
                "detail": (
                    "conversation_context required for this tool"
                ),
            }
        handler_kwargs["conversation_context"] = conversation_context

    try:
        result = await spec.handler(tenant_id, **handler_kwargs)
        audit_row["result_status"] = ("tool_error"
                                              if isinstance(result, dict)
                                              and result.get("error")
                                              else "ok")
        audit_row["result_summary"] = str(result)[:400]
        await _audit(audit_row)
        return {"result": result}
    except TypeError as exc:
        audit_row["result_status"] = "bad_args"
        audit_row["result_summary"] = str(exc)[:400]
        await _audit(audit_row)
        return {"error": "bad_args", "detail": str(exc)}
    except Exception as exc:                                        # noqa: BLE001
        log.warning("tool %s crashed: %s", tool_name, exc)
        audit_row["result_status"] = "crashed"
        audit_row["result_summary"] = str(exc)[:400]
        await _audit(audit_row)
        return {"error": "tool_failed", "detail": str(exc)}


def tool_schema_prompt_snippet(persona: Dict[str, Any]) -> str:
    """Return the tool-schema block that should be appended to the
    persona's system prompt at conversation time. Filters tools by
    the persona's ``read_access_scope`` so a customer-scoped persona
    never sees ``tenant_all`` tools in its option list.

    Feb-2026 · MARCO · Sub-phase B — orchestrator tools
    (``delegate_task``) are surfaced ONLY on personas seeded with
    ``orchestrator=True``.  Non-orchestrator personas never see the
    delegation tool in their option list, so the LLM has no route
    to attempt it and hit the ``dispatch_tool`` refusal.
    """
    scope = (persona.get("read_access_scope") or SCOPE_CUSTOMER).strip()
    is_orch = bool(persona.get("orchestrator"))
    available: List[ToolSpec] = []
    for t in TOOL_REGISTRY.values():
        if t.required_scope == SCOPE_ORCHESTRATOR:
            if is_orch:
                available.append(t)
            continue
        if t.required_scope == SCOPE_TENANT_ALL:
            if scope == SCOPE_TENANT_ALL:
                available.append(t)
            continue
        # SCOPE_CUSTOMER — always visible.
        available.append(t)
    lines = ["# TOOLS AVAILABLE (read-only)"]
    for t in available:
        lines.append(f"- **{t.name}**({', '.join(t.params)}): {t.description}")
    lines.append(
        "\nWhen you need to fetch data, respond with a JSON code fence:\n"
        '```tool\n{"name":"lookup_next_visit","args":{}}\n```\n'
        "The system will substitute the tool output and continue. "
        "For customer-scoped tools you may omit ``customer_id`` — it "
        "will be auto-injected from the caller's session. Never make "
        "up numbers; always call a tool when the user asks about "
        "specific data."
    )
    return "\n".join(lines)


def parse_tool_fence(reply_text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Extract ``{name, args}`` from the first ``\\`\\`\\`tool ... \\`\\`\\``` fence
    in the reply text. Returns ``None`` if no valid fence is present."""
    if not isinstance(reply_text, str):
        return None
    o = reply_text.find("```tool")
    if o < 0:
        return None
    c = reply_text.find("```", o + 7)
    if c < 0:
        return None
    raw = reply_text[o + 7:c].strip()
    try:
        call = json.loads(raw)
    except Exception:
        return None
    name = str(call.get("name") or "")
    if not name:
        return None
    args = call.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    return name, args
