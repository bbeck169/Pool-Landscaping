# Delegation Brief · e1_expo_frontend_dev · Phase 29

**From:** Web team (Phase 29 · Feb 2026)
**To:** Expo mobile frontend
**Priority:** P1
**Status:** Web slice shipped in preview. Mobile parity blocked on your side.

## Context
We just shipped the "Send Email / Send SMS" composer template picker + live preview on the web customer contact page. Operators can now:

1. Tap Email or Text on a customer's page → opens a modal.
2. Pick from saved templates in a sidebar (or leave "Custom message" default) — picking one populates subject + body, editable.
3. Hit "Preview" → the backend substitutes merge tags for **that specific customer** and returns the rendered subject/body.
4. Send. Backend already logs the send to `comms_log` (unchanged).

The backend contract is stable and matches the endpoints your mobile app can call today.

## Backend contract

### Templates list
```
GET /api/marketing/templates?channel=email&active=true    (or channel=sms)
```
Returns `{"templates": [{"id", "name", "channel", "category", "subject", "body", "active", ...}]}`. Filter by channel is a first-class query param — do NOT filter client-side (you'd miss pagination if we add it).

### Live preview
```
POST /api/customers/{cid}/preview-message
Body: {"channel": "email" | "sms", "subject": "...", "body": "..."}
```
Response:
```
{
  "channel": "email",
  "subject_rendered": "Hi Jane!",                # null for SMS
  "body_rendered": "<p>Your address is 18420 W. Cactus...</p>",  # HTML for email, plain text for SMS
  "unresolved_tokens": ["NONSENSE_TOKEN", ...]   # merge tags that had no data
}
```

- Auth: `require_admin` (super_admin or admin only). Techs can't preview / send from the composer.
- SMS channel: response has `subject_rendered: null` and `body_rendered` is HTML-stripped plain text.
- Email channel: `body_rendered` is HTML — render inside a WebView or a rich text container in the composer preview panel.
- 404 when the customer doesn't exist. 422 when channel isn't `email|sms`.

### Send
Endpoints unchanged — the composer just POSTs the fields the operator typed:
```
POST /api/customers/{cid}/send-email    Body: {to, subject, body, customer_id}
POST /api/customers/{cid}/send-sms      Body: {to, body, customer_id}
```
Backend uses the exact same UPPERCASE + Mustache render pipeline as the preview endpoint, so what the operator saw is what will go out.

## Ask
Add the same template picker + preview flow to the Expo customer contact screen.

## Behavior spec

1. **Trigger** — on the customer detail screen, tapping the Email or Text button (which today likely fires a direct send) opens the new composer sheet instead. Same UX as the web modal.
2. **Modal layout** — a bottom-sheet or full-screen modal with:
   - Header: `Send Email` or `Send SMS` (based on which button was tapped).
   - Template list at top OR left (adapt to your existing sheet patterns):
     - First item: **"Custom message"** — pre-selected by default, empty body.
     - Then all templates from `GET /api/marketing/templates?channel=email|sms&active=true`.
   - Below list: subject input (email only) + body textarea. Show `${message.length} chars` counter for SMS.
   - Footer buttons: `Cancel` · `Preview` · `Send`.
3. **Selecting a template** populates `subject` + `body`. User can freely edit.
4. **"Custom message" tap** clears both fields (reset to blank).
5. **Preview tap** — POST to `/api/customers/{cid}/preview-message` with the current subject/body/channel. Show the rendered output inline (or in a stacked child sheet) — email as HTML in a small WebView, SMS as plain text in a `<Text>`. Surface `unresolved_tokens` as a soft-warn chip if non-empty.
6. **Send tap** — POST to `/api/customers/{cid}/send-email` or `/send-sms` with the current fields. On 200, toast "Sent" and close the sheet.

## data-testid parity (match web contract)
- `cd-send-templates` — the template list container
- `cd-send-template-custom` — the "Custom message" row (default-selected)
- `cd-send-template-{template_id}` — one per fetched template
- `cd-send-subject` — subject input (email only)
- `cd-send-message` — body textarea
- `cd-send-char-count` — SMS character counter
- `cd-send-preview` — preview button
- `cd-send-preview-panel` — the rendered-output panel
- `cd-send-preview-subject` — rendered subject line
- `cd-send-preview-body-html` (email) / `cd-send-preview-body-text` (SMS)
- `cd-send-preview-unresolved` — the soft-warn chip listing unresolved tokens
- `cd-send-submit` — send button

## Guardrails
- Do NOT hardcode URLs — use `EXPO_PUBLIC_BACKEND_URL`.
- Do NOT modify backend endpoints; contracts are stable.
- Do NOT render the raw HTML from `body_rendered` in a `<Text>` — use a WebView or a lightweight HTML renderer (react-native-render-html). Otherwise `<p>` tags will show up as literal text in the preview.
- Do NOT send emails/SMS during Expo Jest tests — mock the fetch layer.

## Web references
- Backend source: `/app/backend/routers/customers.py::customer_preview_message`
- Web composer: `/app/frontend/src/pages/customers/CustomerDetail.jsx` — search for `SendComposeModal`
- Vitest coverage: `/app/frontend/src/test/phase29-composer-template-picker.test.jsx`
- Pytest coverage: `/app/backend/tests/test_phase29_composer_template_picker.py`

## Deployment
Backend is live on preview and will be live on prod after the next web deploy (user handles). No mobile-side deploy is needed until this ships as part of a normal Expo release.
