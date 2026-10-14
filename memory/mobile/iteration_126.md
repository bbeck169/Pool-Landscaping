# Iteration 126 — Email Builder mobile parity (P2 #11)

- Surface: drawer → Communications → "Email Builder" / "Templates" (admin + super_admin) → (app)/comms/templates list → [code] detail (meta, Send-test panel, Preview modal with WebView).
- Role gate = backend `_require_admin` + web `AdminOnly` (admin, super_admin). The 4-role admin/super_admin/owner/manager set is ONLY the test-send recipient allow-list.
- Shared `api` wrapper untouched; EmailTestSendPanel.postTemplateTestSend is the single raw-fetch call site (Retry-After).
- Expo web: WebView → stripped-text fallback; Retry-After hidden by CORS → 60s fallback (TD-48 note).
- Preview env: test-send returns status "suppressed_not_demo" (comms whitelist) → info toast "Sent to X — delivery suppressed not demo".
- Deferred: edit-on-mobile (TD-48).
