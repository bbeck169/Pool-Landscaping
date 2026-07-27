# Mobile delegation — AI Employee tool-driven Ask Concierge

**Feb 2026 · Task RR followup for the mobile customer portal.**

Backend is the source of truth. The mobile app doesn't need any new
routes — existing conversation endpoints
(``POST /api/customer-portal/ai-employees/{eid}/conversations/{cid}/messages``)
now transparently execute tool calls server-side before returning
the assistant reply.

## What changed on the server

* Skedra + Billy (customer-audience personas) now advertise a
  read-only tool schema to the LLM at conversation time. The LLM
  can emit a ``` ```tool ``` ``` code fence to fetch:
  * ``lookup_customer`` — own profile fields
  * ``lookup_invoices`` — recent invoices (last 12, filterable)
  * ``lookup_invoice_detail`` — full invoice with line items + PDF
  * ``lookup_next_visit`` — next upcoming visit
  * ``lookup_service_history`` — last N completed visits
  * ``lookup_balance`` — unpaid / past-due / credit balance
* All 6 customer-scoped tools auto-inject the caller's own
  ``customer_id`` — the LLM cannot look up any other customer's
  data regardless of what the prompt tries to make it do.
* Every tool call is audit-logged to ``ai_tool_calls`` (90-day TTL)
  with ``called_by_customer_id`` populated so operators can trace
  what the AI fetched on the customer's behalf.

## What mobile should ship

1. **Nothing route-shape-wise.** The response envelope from the
   messages POST is unchanged: ``{user_message, assistant_message,
   escalated, escalate_reason}``. The mobile client already renders
   ``assistant_message.text`` and shows the escalation banner —
   both continue to work.
2. **Optional UX polish**: the assistant message now carries a new
   ``tool_calls`` field (list of ``{name, args, outcome_preview}``).
   Consider showing a small "🔍 Looking up your account…"
   indicator while the request is in flight — mobile perceived
   latency will go up by ~0.5-2s per tool hop (LLM round-trips
   twice when a tool is called).
3. **No new data-testids required** unless the polish indicator
   ships; if it does, use ``ai-concierge-tool-indicator``.

## Do NOT

* Ship a mobile-only tool dispatcher. Every tool executes server-
  side; letting the mobile client emit tool intents would bypass
  the rate limits + audit trail.
* Cache tool outputs across sessions. Balances / next-visits are
  time-sensitive; the server has to re-fetch every conversation
  turn.
* Ship any admin-only persona (``tenant_all`` scope) to the mobile
  customer portal — the customer-audience gate is still enforced
  by ``_get_employee(expected_audience="customer")`` on every
  request. If mobile ever needs to expose admin personas it
  belongs behind a separate role-gated route.

## Rollout note

The tool loop is capped at 3 rounds per user turn. If the LLM
loops (tool → response → tool → …) it will stop cleanly and let
whatever text it produced at round 3 render. Escalation heuristics
are unchanged.
