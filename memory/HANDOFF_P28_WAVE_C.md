# Handoff — Phase 28 Wave C (Feb 15 2026)

## Aggregate
- **OpenAPI: 545 → 558 (+13 endpoints)**
- **Tests: 61/61 pass** across Phase 23-28 suites (54 fast + 7 warranty) — 0 regressions.

## Module 28.1 — Warranty / Service-Plan Portal
- `routers/warranties.py` with 13 endpoints (plans, contracts, claims, portal, cron trigger).
- Auto-seeds 4 default plans per tenant on first GET.
- Contract `end_date` auto-computed via `dateutil.relativedelta(months=+N)`.
- Claim-filing flips contract → `claim_pending`; admin resolve/reject → back to `active`.
- Customer portal endpoints scoped to `user.customer_id` — customer can only see/file on OWN contracts.
- APScheduler daily `warranty_expiration_scan` at 08:00 UTC. Stage-based reminders (60/30/14/7/1). Idempotent via `warranty_reminders_sent` docs. Dev trigger `POST /warranties/_test/run-scan-now`.
- 7/7 tests pass (plan CRUD + role gating, contract auto-end-date, cancel, admin claim, customer portal flow, expiration + idempotency, tenant/role isolation).

## Module 28.2 — Water Photo UI Hook
- Added "🔬 Analyze water photo (Claude Vision)" button to Chemical Readings section on the admin service report page.
- Modal wires directly to Phase 27.3's `/service-report/analyze-water-photo` endpoint.
- Pulls current form-state readings, calls Claude Vision, renders clarity + issues + recommendations table.
- Each recommendation row has a **1-tap "+ Add"** button that appends to `chemicals_added` with the AI-recommended amount + unit + urgency note.
- Handles the missing-photo case ("Add a water photo first") and `mocked:true` explicitly (badge with reason).
- Mobile parity deferred (endpoint is production-ready; a compact Expo modal is a small polish PR).

## Frontend
- Admin sidebar (Customers group): "Warranty Plans", "Warranty Contracts", "Warranty Claims".
- Customer portal route: `/portal/warranties` — active-contract cards + File Claim CTA + prompt-based description entry.

## Known follow-ups (all non-blocking)
- Warranty cron is 08:00 UTC only; per-tenant local-time deferred.
- Water photo mobile modal still deferred (endpoint ready).
- Warranty renew endpoint creates a follow-up contract; consider auto-renewal cron for `renewal_kind: "auto"` plans in a follow-up.

## HIGHLIGHTED
- Warranty emails use existing Resend pipeline; if customer has no email or Resend is unverified, the reminder is still logged (`status: skipped_no_email` or `failed`) — **never silently dropped**.
- All customer-portal endpoints enforce `user.role == "customer"` AND `customer_id` match on the contract — no cross-customer data leakage.
