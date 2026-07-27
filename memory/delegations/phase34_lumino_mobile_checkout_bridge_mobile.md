# Phase 34 · Lumino mobile checkout bridge — Feb 2026

> **Mobile agent brief only. Backend Phase 2 is shipped on web.**

## Backend endpoints ready for mobile

- `POST /api/payments/setup-session` — returns `{checkout_url, session_id}` (Lumino hosted vault).
- `POST /api/payments/lumino/return` — takes `{session_id}`, returns `{status, next_step}` for the post-return screen.

## Mobile flow

1. Customer taps "Add card" → app calls `POST /api/payments/setup-session`.
2. Receive `{checkout_url}`. Open with:
   - iOS/Android: `expo-web-browser` → `WebBrowser.openAuthSessionAsync(checkout_url, "plofv://payment-return")`
   - Fallback: `Linking.openURL(checkout_url)`.
3. Lumino redirects to `plofv://payment-return?session_id=...` when done.
4. App parses `session_id`, calls `POST /api/payments/lumino/return`.
5. Render success / cancelled / failed screen — same testids as web:
   - `payment-return-success`
   - `payment-return-cancelled`
   - `payment-return-failed`
6. Deep-link config: register `plofv://` scheme in `app.json` and forward `payment-return` route to the return screen.

## Do NOT

- Do NOT show a card form in-app. Lumino's hosted checkout is the ONLY entry point — PCI scope stays with them.
- Do NOT enter live keys. Preview stays mock-only per user directive.

## Preview safety

Mobile hits the same guarded backend adapter. Preview short-circuits with mock responses — no live API is contacted from the mobile client.
