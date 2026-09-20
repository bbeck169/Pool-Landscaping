# Phase A4 · Feb-2026 — Proactive Intelligence: Renewal Engine

## Scope shipped
- **Schema audit — no new collection.** Reused the existing
  `warranty_contracts` collection from Phase 28.1 (Warranty /
  Service-Plan Portal). Fields consumed: `id`, `tenant_id`,
  `customer_id`, `customer_name_snapshot`, `plan_id`,
  `plan_name_snapshot`, `plan_kind_snapshot`, `end_date`
  (ISO date string), `status IN {active, cancelled, renewed,
  expired}`, `price_paid` (dollars).  Auto-renew flag comes from
  the joined `warranty_plans.renewal_kind == "auto"`.
- New scan module `backend/services/intelligence/renewal_scan.py`.
  Entry point `run_renewal_scan(tenant_id=None, now=None)` — the
  test-injectable `now` is used to control the 30-day window.
- Emission per (agreement, 30d milestone). Alert key
  `renewal_due:agreement:{contract_id}:30d` → permanent dedup.
- Two email tracks via the D6 i18n composer:
  * `email.renewal_proposal.*` — manual-renewal contracts.
  * `email.renewal_receipt.*` — auto-renewal contracts.
  Five keys per track (subject, body_intro, body_price, body_cta,
  body_footer). Full-sentence keys, no fragment concat.
  Populated in `en` / `es` / `fr`, placeholder-parity verified.
- HMAC-signed CTA token — `sign_renewal_token(contract_id)` →
  `"{contract_id}.{exp_epoch}.{sig}"`, TTL 60 days, HS256 truncated
  to 32 hex chars (matches the `marketing_campaigns.py` pattern).
  Verify helper returns `contract_id | None`. Constant-time
  signature comparison via `hmac.compare_digest`.
- Cron: daily 07:45 UTC (staggered 45 min behind A1, 30 min A2,
  15 min A3).
- Routes:
  * `POST /api/intelligence/scans/renewal/run-now` — admin+.
  * `POST /api/agreements/{agreement_id}/resend-renewal-email` —
    admin+, tech gets 403 `insufficient_role_for_alerts`.
- Frontend `IntelligenceAlerts` row for `renewal_due`:
  * Summary chip variants:
      - manual → `{plan} · $89.00/mo · expires 2026-03-14`
      - auto   → `{plan} · $79.00/mo · [AUTO-RENEW] 2026-03-14`
  * CTA #1 — **View agreement** deep-links to
    `/customers/{cid}?tab=warranties&highlight={agreement_id}`
    (CustomerDetail already reads `tab` from the query param at
    line 206 → warranties tab opens directly).
  * CTA #2 — **Resend renewal email** POSTs the new admin
    endpoint, `sonner` toast on success/error.

## Tests
- Backend: `backend/tests/test_renewal_scan_a4.py`
  → **13 / 13 passed** (`pytest`, 6.3 s wall).
- Frontend: `frontend/src/pages/admin/__tests__/IntelligenceAlerts.renewal.test.jsx`
  → **8 / 8 passed** (`vitest`, 0.2 s).
- Full backend combined suite (A1 + A2 + A3 + A4 + D6 sweep + D6.2
  sweep): **126 / 126 passed** — confirms D6 drift-guard accepts
  the new keys.
- Full frontend sweep (AlertBell 23 + chemistry 6 + churn 9 +
  renewal 8 + header-cleanup 5): **51 / 51 passed**.

## Follow-ups (backlog)
- CustomerDetail warranties tab does not currently consume the
  `highlight` query param — the tab opens (via `tab=warranties`)
  but the specific row isn't scrolled/pulsed. Small
  `useSearchParams` addition on the warranties panel when it's
  next touched.
- Customer-portal `/customer-portal/agreements/{id}/renew` page
  that consumes the HMAC token — the signer + verifier live in
  `services/intelligence/renewal_scan.py` (`sign_renewal_token` /
  `verify_renewal_token`); the FE page is a Phase A4+ deliverable.

## API surface
- `POST /api/intelligence/scans/renewal/run-now` — admin+.
- `POST /api/agreements/{agreement_id}/resend-renewal-email` — admin+.
- Total intelligence-related routes in OpenAPI: **9** (4 producers
  + 4 alert CRUD + 1 resend-email).
