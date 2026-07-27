# Delegation Brief · e1_expo_frontend_dev

**From:** Web team (Phase 22 · Feb 2026)
**To:** Expo mobile frontend
**Priority:** P1

## Context
We just shipped a public, no-login portal at `/portal/service/{uuid}` that renders the technician's photos from a submitted service report. The backend now mints a `public_uuid` on every submitted service report and exposes the read-only images via `GET /api/public/service/{uuid}` (60 req/min per IP, no auth, zero customer PII).

The web tech-side `ServiceReport.jsx` (`/app/frontend/src/pages/tech/ServiceReport.jsx`) already gained a "Share visit" button in the report header that appears once the report is `locked` (submitted) and `public_uuid` is set. Clicking it copies the URL to clipboard and shows a toast.

## Ask
Add the same "Share visit" affordance to the Expo tech checkout screen.

## Behavior spec
1. Location — the screen the tech sees AFTER `POST /api/jobs/{id}/service-report/submit` completes. Look for the "Submit Report & Clock Out" or equivalent in the mobile service report flow.
2. Show a "Share visit" secondary button ONLY when:
   - `service_report.submitted_at` is set (i.e., locked)
   - `service_report.public_uuid` is present (backend guarantees both on submit — legacy reports get backfilled on submit)
3. On tap:
   - Build the URL: `${EXPO_PUBLIC_BACKEND_URL}/portal/service/{public_uuid}` (strip trailing slash before concatenating). If `EXPO_PUBLIC_BACKEND_URL` is unset for any reason, fall back to the pre-existing `.env` alias the mobile app already uses. Never hardcode a hostname.
   - Copy the URL to clipboard using Expo's `expo-clipboard` (`Clipboard.setStringAsync(url)`).
   - Show a toast (or Alert / Snackbar — whatever the app uses) with copy: **"Link copied — you can text this to the customer."**
4. Nice-to-have (skip if it adds >30 min of work): a secondary "Share…" option that opens the OS share sheet via `expo-sharing` or `Share.share({ url })`.

## data-testid
Use `data-testid="svc-report-share-visit"` and `data-testid="svc-report-share-toast"` for parity with the web tests.

## Guardrails
- Do NOT touch anything else in the checkout flow — this is a purely additive button.
- Do NOT modify any backend endpoints; the URL scheme is fixed.
- Do NOT display or copy any customer PII — the URL alone is safe.

## References
- Web implementation: `/app/frontend/src/pages/tech/ServiceReport.jsx` (search for `svc-report-share-visit`)
- Vitest coverage: `/app/frontend/src/test/share-visit-button.test.jsx` — same behavior contract you should mirror in your Jest/RTL setup.
- Backend guarantee: `/app/backend/routers/service_reports.py::submit_service_report` backfills `public_uuid` on submit if missing.

## Deployment
No prod redeploy needed on the mobile side until this feature ships as part of a normal mobile release cadence.
