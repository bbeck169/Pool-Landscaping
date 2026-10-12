"""Feb-2026 · Slice 5 — Customer-portal AI carve-out (Skedra + Billy).

The two customer-facing AI employees are surfaced ONLY through the
routes in this module. Every path here:

* requires ``role == "customer"``
* scopes reads/writes strictly to ``current_user.customer_id`` in the
  current tenant
* enforces ``employee.audience == "customer"`` — so a customer can
  never open a conversation with an admin-audience employee (Casey,
  Emmie, Buddy, …) even by sending a valid employee id from another
  scope

Escalation reuses the Slice 3D infrastructure (internal message +
tenant-admin bell + best-effort Expo push) so a fallback "I've asked
our team to reach out" reply is immediately actionable by the human
admin group.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import get_current_user, new_id, now_iso
from utils import not_deleted_filter as _nd
from routers.tenants import get_current_tenant
from routers.ai_employees import (
    CHAT_MSG_COST,
    _get_employee,
    _llm_chat,
    seed_ai_employees_for_tenant,
)
from services.ai_credits import debit_credits, ensure_tenant_credits_initialized

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════
def _require_customer(user: dict) -> str:
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer portal only")
    cid = user.get("customer_id")
    if not cid:
        raise HTTPException(403, "Customer id missing on user")
    return cid


def _num(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(n: float) -> str:
    return "${:,.2f}".format(round(float(n or 0), 2))


# ═══════════════════════════════════════════════════════════════════════
# customer_scoped_context — the ONLY data a customer AI can see
# ═══════════════════════════════════════════════════════════════════════
async def customer_scoped_context(
    tenant_id: str,
    customer_id: str,
    kind: str,
) -> Dict[str, Any]:
    """Build the LLM context payload for a single customer.

    ``kind`` is ``"scheduling"`` (Skedra) or ``"billing"`` (Billy) —
    each returns a strict subset of the customer's own data, redacted
    of internal notes, tech identities beyond first name, pricing
    breakdowns, tenant HQ, other customers' identifiers, and any
    cross-customer aggregate.

    Never raises — a missing customer returns a mostly-empty payload
    the AI can politely say "I don't have that on file for you" over.
    """
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0},
    ) or {}
    ctx: Dict[str, Any] = {
        "kind": kind,
        "customer": {
            "name": cust.get("name"),
            # NEVER include email/phone/address on the LLM side — the
            # customer already knows their own contact details, and
            # this shrinks the leak surface if the LLM regurgitates.
        },
    }

    today = datetime.now(timezone.utc).date().isoformat()

    if kind == "scheduling":
        upcoming = await db.jobs.find(
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "status": {"$in": ["scheduled", "active", "pending", "requested"]},
                "scheduled_start": {"$gte": f"{today}T00:00:00+00:00"},
            },
            {"_id": 0, "id": 1, "title": 1, "service_type": 1,
             "job_type": 1, "scheduled_start": 1, "scheduled_end": 1,
             "status": 1, "property_id": 1},
        ).sort("scheduled_start", 1).to_list(20)

        past = await db.jobs.find(
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "status": "completed",
            },
            {"_id": 0, "id": 1, "title": 1, "service_type": 1,
             "job_type": 1, "scheduled_start": 1, "completed_at": 1,
             "property_id": 1},
        ).sort("scheduled_start", -1).to_list(5)

        ctx["upcoming_visits"] = [
            {
                "date": str(j.get("scheduled_start") or "")[:10],
                "service_type": j.get("service_type") or j.get("job_type"),
                "title": j.get("title"),
                "status": j.get("status"),
            }
            for j in upcoming
        ]
        ctx["recent_completed_visits"] = [
            {
                "date": str(j.get("scheduled_start") or j.get("completed_at") or "")[:10],
                "service_type": j.get("service_type") or j.get("job_type"),
                "title": j.get("title"),
            }
            for j in past
        ]

        # Service types offered — union of service_type over the
        # customer's OWN historical jobs (avoids leaking the tenant's
        # full catalog to a customer).
        types = {
            j.get("service_type") or j.get("job_type")
            for j in (upcoming + past)
        }
        types.discard(None)
        types.discard("")
        ctx["service_types_available"] = sorted(types)

    elif kind == "billing":
        # Feb-2026 · Slice J2 — Billy now has FULL invoice access for
        # the caller customer only. Cross-customer isolation preserved
        # (every query below is scoped by ``tenant_id + customer_id``);
        # this ask is about DEPTH on the caller's own data, not
        # BREADTH across customers.

        # Cap the window to the last 24 months so the LLM context
        # doesn't blow up on ancient tenants. Full lifetime aggregates
        # (spend, credit) are still computed off the whole set below.
        window_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=730)
        ).isoformat()

        # ── Pull EVERY invoice for this customer + line items ──────
        all_invoices = await db.quotes.find(
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "doc_type": "invoice",
            },
            # Full projection now — we intentionally expose the line
            # items to the AI so it can answer "what was on the July
            # invoice" style questions. Internal-only fields are
            # dropped by the sanitizer below.
            {"_id": 0},
        ).to_list(2000)

        recent_invoices = [
            i for i in all_invoices
            if str(i.get("issued_at") or i.get("created_at") or "") >= window_cutoff
        ] or all_invoices  # fall back to all if tenant has <24mo history

        # ── Aggregates + aging (whole history) ─────────────────────
        balance = past_due = credit = 0.0
        open_ct = past_ct = 0
        lifetime_spend = 0.0
        aging = {"current_0_30": 0.0, "days_31_60": 0.0,
                 "days_61_90": 0.0, "days_90_plus": 0.0}

        def _days_past(due_iso: str) -> int:
            try:
                due_d = datetime.strptime(due_iso[:10], "%Y-%m-%d").date()
                today_d = datetime.strptime(today, "%Y-%m-%d").date()
                return (today_d - due_d).days
            except (TypeError, ValueError):
                return 0

        for inv in all_invoices:
            total = _num(inv.get("total"))
            paid = _num(inv.get("amount_paid"))
            remaining = round(total - paid, 2)
            due = str(inv.get("due_date") or "")[:10]
            lifetime_spend += paid
            if remaining > 0:
                balance += remaining
                open_ct += 1
                if due and due < today:
                    past_due += remaining
                    past_ct += 1
                    d = _days_past(due)
                    if d <= 30:
                        aging["current_0_30"] += remaining
                    elif d <= 60:
                        aging["days_31_60"] += remaining
                    elif d <= 90:
                        aging["days_61_90"] += remaining
                    else:
                        aging["days_90_plus"] += remaining
                else:
                    aging["current_0_30"] += remaining
            elif remaining < 0:
                credit += -remaining

        # ── Redacted-yet-detailed invoice list for the LLM ────────
        def _clean_line_item(li: Dict[str, Any]) -> Dict[str, Any]:
            # Drop internal SKUs, costs, margins; keep customer-facing
            # description + quantity + unit price + line total.
            qty = _num(li.get("quantity") or li.get("qty") or 1)
            unit = _num(li.get("unit_price") or li.get("price"))
            line_total = _num(
                li.get("total") or li.get("line_total") or (qty * unit)
            )
            return {
                "description": li.get("description") or li.get("name") or "",
                "quantity": qty,
                "unit_price": _money(unit),
                "total": _money(line_total),
                "category": li.get("category") or li.get("income_category") or None,
            }

        ctx["invoices"] = []
        for inv in sorted(
            recent_invoices,
            key=lambda x: str(x.get("issued_at") or x.get("created_at") or ""),
            reverse=True,
        ):
            total = _num(inv.get("total"))
            paid = _num(inv.get("amount_paid"))
            remaining = round(total - paid, 2)
            due = str(inv.get("due_date") or "")[:10] or None
            issued = str(inv.get("issued_at") or inv.get("created_at") or "")[:10]
            line_items = inv.get("line_items") or []
            if not isinstance(line_items, list):
                line_items = []
            ctx["invoices"].append({
                "invoice_number": inv.get("invoice_number"),
                "issued": issued,
                "due": due,
                "days_past_due": (
                    _days_past(due) if (due and remaining > 0 and due < today) else 0
                ),
                "subtotal": _money(_num(inv.get("subtotal") or inv.get("total"))),
                "tax": _money(_num(inv.get("tax"))),
                "total": _money(total),
                "amount_paid": _money(paid),
                "remaining": _money(remaining),
                "status": inv.get("status"),
                "payment_status": inv.get("payment_status"),
                "title": inv.get("title") or inv.get("description") or "",
                "line_items": [_clean_line_item(li) for li in line_items[:40]],
                # Never expose: internal_notes, admin_notes, cost/margin
                # fields, tech identifiers, or any tenant HQ data.
            })

        # ── Payment history (masked, receipt-linked) ──────────────
        payments: List[Dict[str, Any]] = []
        try:
            rows = await db.payments.find(
                {"tenant_id": tenant_id, "customer_id": customer_id},
                {"_id": 0, "amount": 1, "paid_at": 1, "created_at": 1,
                 "method": 1, "brand": 1, "last4": 1,
                 "invoice_id": 1, "invoice_number": 1,
                 "receipt_url": 1, "status": 1},
            ).sort("paid_at", -1).to_list(200)
            for p in rows:
                payments.append({
                    "date": str(p.get("paid_at") or p.get("created_at") or "")[:10],
                    "amount": _money(_num(p.get("amount"))),
                    "method": p.get("method") or "card",
                    "brand": p.get("brand") or None,
                    "last4": p.get("last4") or None,
                    "invoice_number": p.get("invoice_number"),
                    "receipt_url": p.get("receipt_url") or None,
                    "status": p.get("status") or "succeeded",
                })
        except Exception as exc:  # pragma: no cover
            logger.warning("[j2] payments read failed: %s", exc)
        ctx["payment_history"] = payments

        # ── Recurring / subscription info ─────────────────────────
        recurring: List[Dict[str, Any]] = []
        try:
            rows = await db.billing_plans.find(
                {"tenant_id": tenant_id, "customer_id": customer_id},
                {"_id": 0, "service": 1, "amount": 1, "cadence": 1,
                 "next_run_at": 1, "active": 1, "start_date": 1},
            ).to_list(50)
            for plan in rows:
                recurring.append({
                    "service": plan.get("service") or "Service",
                    "amount": _money(_num(plan.get("amount"))),
                    "cadence": plan.get("cadence") or "monthly",
                    "active": bool(plan.get("active")),
                    "next_run": str(plan.get("next_run_at") or "")[:10] or None,
                    "started": str(plan.get("start_date") or "")[:10] or None,
                })
        except Exception as exc:  # pragma: no cover
            logger.warning("[j2] billing_plans read failed: %s", exc)
        ctx["recurring_services"] = recurring

        # ── Aggregate summary at the top of the payload ───────────
        ctx["balance_due"] = _money(balance)
        ctx["past_due"] = _money(past_due)
        ctx["credit"] = _money(credit)
        ctx["lifetime_spend"] = _money(lifetime_spend)
        ctx["open_invoice_count"] = open_ct
        ctx["past_due_invoice_count"] = past_ct
        ctx["invoice_count_total"] = len(all_invoices)
        ctx["aging"] = {k: _money(v) for k, v in aging.items()}

        # Next payment due — earliest open invoice with a due_date.
        upcoming_due = None
        for inv in all_invoices:
            total = _num(inv.get("total"))
            paid = _num(inv.get("amount_paid"))
            if total - paid <= 0:
                continue
            due = str(inv.get("due_date") or "")[:10]
            if not due:
                continue
            if upcoming_due is None or due < upcoming_due["due"]:
                upcoming_due = {
                    "invoice_number": inv.get("invoice_number"),
                    "due": due,
                    "amount": _money(round(total - paid, 2)),
                }
        ctx["next_payment_due"] = upcoming_due

        # ── Payment methods on file (masked) ──────────────────────
        methods: List[Dict[str, Any]] = []
        if cust.get("default_payment_method_id"):
            methods.append({
                "type": "card",
                "brand": cust.get("pm_brand") or "Card",
                "last4": cust.get("pm_last4") or "",
            })
        ach_rows = await db.payment_methods.find(
            {"tenant_id": tenant_id, "customer_id": customer_id, "type": "ach"},
            {"_id": 0, "verified": 1, "created_at": 1},
        ).sort("created_at", -1).to_list(10)
        for row in ach_rows:
            methods.append({
                "type": "ach",
                "verified": bool(row.get("verified")),
            })
        ctx["payment_methods_on_file"] = methods

    return ctx


def _format_context_for_prompt(ctx: Dict[str, Any]) -> str:
    """Render the context payload as a fenced JSON block the model can
    read literally. Keeping it structured (JSON, not prose) makes it
    easier for the model to quote exact numbers back to the customer
    without paraphrasing them.
    """
    return (
        "You have been given the CALLER CUSTOMER's own data below in "
        "JSON. Answer only from this payload; do not invent numbers "
        "or dates outside it.\n"
        "```json\n"
        + json.dumps(ctx, indent=2, default=str)
        + "\n```"
    )


# Detectors used to decide whether a reply counts as "escalate-worthy".
# The AI is instructed to prefix its own escalation with markers we
# search for; we also match the "I've asked our team" refusal phrasing
# so the escalation fires even when the model doesn't emit the marker.
_ESCALATE_MARKERS = (
    "ESCALATE:",
    "I'll ask our team",
    "I'll flag this to our billing team",
    "I've escalated",
    "asked our team to reach out",
    "flag this to our billing team",
)


def _looks_escalation(reply_text: str) -> bool:
    if not reply_text:
        return False
    low = reply_text.lower()
    return any(m.lower() in low for m in _ESCALATE_MARKERS)


# ═══════════════════════════════════════════════════════════════════════
# Routes — enumeration + conversations + messages
# ═══════════════════════════════════════════════════════════════════════
@router.get("/customer-portal/ai-employees")
async def list_customer_ai_employees(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Return only the customer-audience AI employees for this tenant."""
    _require_customer(user)
    # Lazy seed keeps parity with the admin surface.
    await seed_ai_employees_for_tenant(tenant["id"])
    rows = await db.ai_employees.find(
        {"tenant_id": tenant["id"], "audience": "customer", "active": True},
        {"_id": 0, "id": 1, "key": 1, "name": 1, "role": 1,
         "avatar_emoji": 1, "avatar_url": 1, "audience": 1},
    ).sort("key", 1).to_list(20)
    return rows


class ConvCreate(BaseModel):
    title: Optional[str] = None


async def _customer_conversation(tenant_id: str, cid_conv: str,
                                   customer_id: str) -> Dict[str, Any]:
    doc = await db.ai_employee_conversations.find_one(
        {"id": cid_conv, "tenant_id": tenant_id,
         "customer_id": customer_id}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Conversation not found")
    return doc


@router.get("/customer-portal/ai-employees/{eid}/conversations")
async def list_customer_conversations(
    eid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    cid = _require_customer(user)
    await _get_employee(tenant["id"], eid, expected_audience="customer")
    rows = await db.ai_employee_conversations.find(
        {"tenant_id": tenant["id"], "employee_id": eid,
         "customer_id": cid},
        {"_id": 0},
    ).sort("updated_at", -1).to_list(20)
    return rows


@router.post("/customer-portal/ai-employees/{eid}/conversations",
              status_code=201)
async def create_customer_conversation(
    eid: str, body: ConvCreate = ConvCreate(),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    cid = _require_customer(user)
    emp = await _get_employee(tenant["id"], eid, expected_audience="customer")
    # Single-latest-conversation-per-employee — surface it if it
    # exists so the customer picks up their thread on reopen.
    existing = await db.ai_employee_conversations.find_one(
        {"tenant_id": tenant["id"], "employee_id": eid,
         "customer_id": cid},
        {"_id": 0},
        sort=[("updated_at", -1)],
    )
    if existing:
        return existing
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "employee_id": eid,
        "customer_id": cid,
        "audience": "customer",
        "title": body.title or f"{emp.get('name') or 'AI'} chat",
        "message_count": 0,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.ai_employee_conversations.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/customer-portal/ai-employees/{eid}/conversations/{cid_conv}/messages")
async def list_customer_messages(
    eid: str, cid_conv: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    cid = _require_customer(user)
    await _get_employee(tenant["id"], eid, expected_audience="customer")
    await _customer_conversation(tenant["id"], cid_conv, cid)
    rows = await db.ai_employee_messages.find(
        {"tenant_id": tenant["id"], "conversation_id": cid_conv},
        {"_id": 0},
    ).sort("created_at", 1).to_list(200)
    return rows


class MessageIn(BaseModel):
    text: str


async def _escalate_conversation(
    *,
    tenant: dict,
    customer_id: str,
    customer_name: str,
    employee: dict,
    conversation_id: str,
    user_text: str,
    reason: str,
) -> str:
    """Reuse the Slice 3D infrastructure — create an internal message,
    fan out a bell to every admin, best-effort Expo push. Returns the
    canonical assistant reply the customer will see."""
    topic = employee.get("role") or employee.get("name") or "AI conversation"
    friendly_reply = (
        "I've asked our team to reach out about this — someone will "
        "follow up shortly."
    )

    # 1) Persist the outbound admin-facing internal message (reuses
    #    ``db.messages`` — same collection the admin thread reads from
    #    via /communications/{customer_id}).
    header = (
        f"AI escalation from {customer_name} · {topic}\n"
        f"Reason: {reason}\n"
        f"Customer said: {user_text.strip()}"
    )
    msg_id = new_id()
    msg_doc = {
        "id": msg_id,
        "tenant_id": tenant["id"],
        "customer_id": customer_id,
        "sender": "customer",
        "sender_name": customer_name,
        "text": header,
        "kind": "ai_escalation",
        "ai_escalation": {
            "employee_id": employee.get("id"),
            "employee_key": employee.get("key"),
            "conversation_id": conversation_id,
            "reason": reason,
        },
        "read_by_customer": True,
        "read_by_staff": False,
        "created_at": now_iso(),
    }
    await db.messages.insert_one(msg_doc)

    # 2) Bell fan-out — reuse the same helper the service-request
    #    escalation uses so admins get one unified inbox.
    try:
        from services.notifications import enqueue_for_tenant_admins
        await enqueue_for_tenant_admins(
            tenant["id"],
            kind="inbound_customer_message",
            title=f"AI escalation from {customer_name}",
            body=f"{topic} · {reason}",
            source_ref={
                "kind": "ai_escalation",
                "message_id": msg_id,
                "customer_id": customer_id,
                "employee_key": employee.get("key"),
            },
            href=f"/communication/{customer_id}",
            priority="normal",
        )
    except Exception as exc:  # pragma: no cover — logged, never blocks
        logger.warning("ai_escalation bell enqueue failed: %s", exc)

    # 3) Realtime + Expo push (best-effort, mirrors 3D).
    try:
        from routers.realtime import bus
        from routers.mobile_push import send_push_to_user
        admins = await db.users.find(
            {"tenant_id": tenant["id"],
             "role": {"$in": ["admin", "super_admin"]}},
            {"_id": 0, "id": 1},
        ).to_list(200)
        for a in admins:
            if not a.get("id"):
                continue
            try:
                await bus.broadcast(a["id"], {
                    "type": "ai_escalation",
                    "payload": {
                        "customer_id": customer_id,
                        "customer_name": customer_name,
                        "employee_key": employee.get("key"),
                        "message_id": msg_id,
                    },
                })
            except Exception:
                pass
            try:
                await send_push_to_user(
                    a["id"],
                    f"AI escalation from {customer_name}",
                    f"{topic} · {reason}",
                    data={"kind": "ai_escalation",
                          "message_id": msg_id,
                          "customer_id": customer_id},
                )
            except Exception:
                pass
    except Exception as exc:
        logger.warning("ai_escalation fan-out failed: %s", exc)

    return friendly_reply


@router.post("/customer-portal/ai-employees/{eid}/conversations/{cid_conv}/messages",
              status_code=201)
async def send_customer_message(
    eid: str, cid_conv: str, body: MessageIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Customer sends a message to Skedra or Billy.

    1. Debit 1 credit from the tenant pool (soft — never blocks).
    2. If the tenant has zero-or-negative balance BEFORE the call,
       skip the LLM, reply with the graceful unavailable message, and
       escalate — so the customer always gets an actionable outcome.
    3. Otherwise: build a customer-scoped context, prepend it to the
       system prompt, call the LLM, persist the reply. If the reply
       reads as an escalation OR this is the 2nd unresolved turn,
       fire the Slice 3D escalation wire alongside the reply.
    """
    cid = _require_customer(user)
    emp = await _get_employee(tenant["id"], eid, expected_audience="customer")
    conv = await _customer_conversation(tenant["id"], cid_conv, cid)

    # Persist the customer turn.
    user_msg = {
        "id": new_id(), "tenant_id": tenant["id"],
        "conversation_id": cid_conv, "employee_id": eid,
        # Feb-2026 · MARCO · Sub-phase B — stamp every message with
        # ``sender_employee_id`` so a multi-persona transcript can
        # be re-assembled per-speaker.  Customer-facing personas
        # never participate in delegation loops (only admin
        # personas with ``orchestrator=True`` can call
        # ``delegate_task``), but the field is stamped uniformly
        # across both send paths to keep the message schema flat.
        "sender_employee_id": eid,
        "role": "user", "text": body.text,
        "created_at": now_iso(),
    }
    await db.ai_employee_messages.insert_one(user_msg)

    # Snapshot the tenant credit balance BEFORE the debit so we can
    # detect a "zero credits" state and short-circuit gracefully.
    t = await ensure_tenant_credits_initialized(tenant["id"])
    balance_before = int(t.get("ai_credits_balance", 0))

    escalated = False
    escalate_reason: Optional[str] = None
    assistant_text: str
    provider = "stub"

    if balance_before <= 0:
        # Zero-balance — DO NOT call the LLM. Escalate directly.
        assistant_text = (
            "Our concierge is currently unavailable — I've passed your "
            "note to our team and someone will get back to you shortly."
        )
        escalate_reason = "tenant_credits_exhausted"
        await _escalate_conversation(
            tenant=tenant,
            customer_id=cid,
            customer_name=(user.get("name") or "Customer"),
            employee=emp,
            conversation_id=cid_conv,
            user_text=body.text,
            reason=escalate_reason,
        )
        escalated = True
    else:
        # Normal path — debit + LLM.
        await debit_credits(
            tenant["id"], CHAT_MSG_COST,
            feature="other",
            ref_id=cid_conv, ref_type="ai_employee_conversation",
            reason=f"ai_employees.{emp['key']}.chat.customer",
            actor_user_id=user.get("id"),
        )

        # Build the customer-scoped context — the ONLY data the LLM
        # is allowed to see for this call.
        kind = "billing" if emp.get("key") == "billy" else "scheduling"
        ctx = await customer_scoped_context(tenant["id"], cid, kind)
        # Task RR · Feb 2026 — append the tool schema so the LLM can
        # emit ```tool ...``` fences to fetch data dynamically. The
        # dispatcher enforces this persona's read_access_scope and
        # auto-injects the caller's customer_id — the LLM cannot
        # cross-customer-lookup.
        from services.ai_employee_tools import (
            tool_schema_prompt_snippet,
            parse_tool_fence,
            dispatch_tool,
        )
        system_prompt = (
            emp["system_prompt"] + "\n\n"
            + _format_context_for_prompt(ctx) + "\n\n"
            + tool_schema_prompt_snippet(emp)
        )
        # MTH-C · Feb-2026 — prepend the tenant's tone-voice directive
        # so per-tenant tone rules take effect at request time.
        try:
            from services.tenant_ai_rules.prompt_injection import (
                build_tone_directive,
            )
            from services.tenant_ai_rules.resolver import (
                resolve_rules_for_tenant,
            )
            _mth_c_resolved = await resolve_rules_for_tenant(tenant["id"])
            _mth_c_directive = build_tone_directive(
                _mth_c_resolved.get("rules") or {},
            )
            if _mth_c_directive:
                system_prompt = f"{_mth_c_directive}\n\n{system_prompt}"
        except Exception as _mth_c_exc:                            # noqa: BLE001
            logger.warning(
                "[mth-c] tone directive skipped for tenant=%s: %s",
                tenant.get("id"), _mth_c_exc,
            )

        history = await db.ai_employee_messages.find(
            {"tenant_id": tenant["id"], "conversation_id": cid_conv},
            {"_id": 0, "role": 1, "text": 1},
        ).sort("created_at", 1).to_list(20)

        r = await _llm_chat(system_prompt, body.text, history)
        assistant_text = r["text"]
        provider = r.get("provider", "stub")

        # Task RR · tool loop — up to 3 rounds. If the LLM emitted
        # a ```tool``` fence, dispatch it, feed the result back,
        # and re-prompt. This is a best-effort loop: any parse /
        # dispatch failure surfaces as a structured error which the
        # LLM can politely explain.
        tool_history: List[Dict[str, Any]] = []
        for _round in range(3):
            parsed = parse_tool_fence(assistant_text)
            if not parsed:
                break
            tname, targs = parsed
            outcome = await dispatch_tool(
                tenant_id=tenant["id"],
                persona=emp,
                caller_kind="customer",
                caller_customer_id=cid,
                tool_name=tname,
                args=targs,
            )
            tool_history.append({"name": tname, "args": targs,
                                       "outcome_preview": str(outcome)[:200]})
            payload = outcome.get("result") if "result" in outcome else outcome
            follow = (
                f"Tool `{tname}` returned:\n"
                f"```json\n{json.dumps(payload, default=str)[:3000]}\n```\n"
                "Answer the user's question with this data. If it "
                "doesn't help, offer to escalate."
            )
            r2 = await _llm_chat(system_prompt, follow, history)
            assistant_text = r2["text"]
            provider = r2.get("provider", provider)

        # Escalation trigger — model-emitted marker OR the 2nd
        # unresolved turn (per spec).
        prior_user_turns = sum(
            1 for h in history if h.get("role") == "user"
        )
        if _looks_escalation(assistant_text):
            escalate_reason = "ai_declined_to_answer"
            escalated = True
        elif prior_user_turns >= 2:
            # This is at least the 3rd user turn without resolution
            # (prior_user_turns includes the just-inserted turn +
            # earlier turns). Give the human a heads-up.
            escalate_reason = "multi_turn_unresolved"
            escalated = True

        if escalated:
            # Overwrite the reply with the friendly canonical text
            # only when the model didn't produce a coherent one.
            if assistant_text.startswith("[stub") or not assistant_text.strip():
                assistant_text = (
                    "I've asked our team to reach out about this — "
                    "someone will follow up shortly."
                )
            await _escalate_conversation(
                tenant=tenant,
                customer_id=cid,
                customer_name=(user.get("name") or "Customer"),
                employee=emp,
                conversation_id=cid_conv,
                user_text=body.text,
                reason=escalate_reason,
            )

    # Persist the assistant turn.
    assistant_msg = {
        "id": new_id(), "tenant_id": tenant["id"],
        "conversation_id": cid_conv, "employee_id": eid,
        # Feb-2026 · MARCO · Sub-phase B — sender is the persona
        # replying to the customer.  Customer-facing personas
        # (Skedra, Billy) can't delegate, so sender is always the
        # URL-path employee.
        "sender_employee_id": eid,
        "role": "assistant", "text": assistant_text,
        "escalated": escalated,
        "escalate_reason": escalate_reason,
        "provider": provider,
        "tool_calls": locals().get("tool_history") or [],
        "created_at": now_iso(),
    }
    await db.ai_employee_messages.insert_one(assistant_msg)

    # Bump the conversation counters.
    await db.ai_employee_conversations.update_one(
        {"id": cid_conv, "tenant_id": tenant["id"]},
        {"$set": {"updated_at": now_iso()},
         "$inc": {"message_count": 2}},
    )

    user_msg.pop("_id", None)
    assistant_msg.pop("_id", None)
    return {
        "user_message": user_msg,
        "assistant_message": assistant_msg,
        "escalated": escalated,
        "escalate_reason": escalate_reason,
    }


# ═══════════════════════════════════════════════════════════════════
# Task RR/SS Phase 2 · Feb 2026 — Customer-scoped credit balance
# endpoint. Powers the Portal Home CREDIT stat tile.
#
# P0b Stage 2 S2-2 · Feb-2026 — ROUTE REWRITTEN. Previously this
# endpoint read ``customers.credits_balance_cents`` (PLURAL legacy
# field) directly off the customer doc. That field is NEVER
# re-stamped by the canonical mutation choke point
# (``services.customer_balance.mutate_credit``), so every customer
# whose credit was granted via the admin "Issue Credit" button, a
# referral reward, or the referral-watcher saw $0 on the portal
# tile even though admin profile showed the correct balance. 3rd
# recurrence of this bug (see /app/memory/credit_parity_rca.md).
#
# The response shape stays identical to the pre-fix wire so the
# current frontend doesn't break during the deprecation window —
# only the SOURCE of the number changes, from the stale plural
# field to the canonical ``compute_customer_balance`` compute.
# The ``canonical: true`` flag is added so clients that want to
# verify can introspect without re-fetching.
# ═══════════════════════════════════════════════════════════════════
@router.get("/customer-portal/credits/balance")
async def get_own_credit_balance(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    cid = _require_customer(user)
    from services.customer_balance import compute_customer_balance
    canonical = await compute_customer_balance(db, tenant["id"], cid)
    balance_cents = int(canonical.get("credit_balance_cents") or 0)
    return {
        "balance_cents": balance_cents,
        "balance_dollars": round(balance_cents / 100.0, 2),
        "canonical": True,
    }


@router.post("/customer-portal/ai-employees/{eid}/conversations/{cid_conv}/handoff",
              status_code=201)
async def manual_handoff(
    eid: str, cid_conv: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Customer taps the "Handoff to human" button in the composer
    footer. Fires the escalation with the whole transcript summarised
    onto the internal message."""
    cid = _require_customer(user)
    emp = await _get_employee(tenant["id"], eid, expected_audience="customer")
    conv = await _customer_conversation(tenant["id"], cid_conv, cid)

    # Grab the last few user turns to summarise the request for the
    # admin inbox. Full transcript would be too noisy for a bell row.
    tail = await db.ai_employee_messages.find(
        {"tenant_id": tenant["id"], "conversation_id": cid_conv,
         "role": "user"},
        {"_id": 0, "text": 1},
    ).sort("created_at", -1).to_list(3)
    tail.reverse()
    summary = " · ".join((m.get("text") or "").strip()[:120] for m in tail) or \
        "(no messages yet)"

    await _escalate_conversation(
        tenant=tenant,
        customer_id=cid,
        customer_name=(user.get("name") or "Customer"),
        employee=emp,
        conversation_id=cid_conv,
        user_text=summary,
        reason="manual_handoff",
    )
    return {"ok": True}
