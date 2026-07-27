## Delegation Brief · Phase 34 (web) → Phase 33 (mobile)
### Retire "Book Service" + Simplify Request Service to Free Text

**From:** Web / backend team · Phase 34 · Feb 2026 · Task H + I
**To:** e1_expo_frontend_dev
**Priority:** P1
**Language:** All comments, tests, and copy in **English**.
**Status:** Web + backend shipped. Mobile parity outstanding.

---

### 1. Remove "Book Service" from the customer portal on mobile (Task H)

The customer-facing self-service booking flow has been **retired**.
Web changes:

- `/app/frontend/src/nav/roleNav.js` — dropped the `{to: "/portal/book",
  label: "Book Service"}` entry.
- `/app/frontend/src/layouts/AppLayout.jsx` — dropped the `Book` bottom-nav /
  sidebar entry.
- `/app/frontend/src/App.js` — the `/portal/book` route is now a
  `<Navigate to="/portal/request-service" replace />` shim so any legacy
  bookmark 302s to the Request flow. Import of `PortalBook` is commented
  out; the source file remains on disk for legacy reference only.

Mobile ask:

1. Remove the `Book` (or `Book Service`) tab / drawer entry from
   `/app/mobile/app/(portal)/_layout.tsx` (or wherever the tab / drawer
   configuration lives).
2. Remove the corresponding screen route file (`(portal)/book.tsx` or
   whichever the current path is). If keeping it around as reference is
   preferred, add a top-of-file banner `// DEPRECATED — Phase 34 · Task H`
   and don't wire it into the router.
3. If any Portal Home / Dashboard tile on mobile still says "Book
   Service" — replace it with a link to the Request Service screen.
4. Add a small react-native redirect: any deep link to `/portal/book`
   should push the Request Service screen instead so notification /
   old-app-version deep links don't crash.
5. Admin-side scheduling / dispatch UI is UNTOUCHED — this only affects
   the customer portal.

### 2. Simplify Request Service to a single free-text field (Task I)

The customer-portal Request Service screen no longer asks for a Service
Type. It accepts one paragraph textarea + optional preferred date.

Web changes (`/app/frontend/src/pages/portal/PortalPages.jsx` ·
`PortalRequestService`):

- Service Type `<select>` removed.
- New required textarea labeled **"What service do you need?"**
  - `placeholder="Describe what you need — e.g., green pool, broken sprinkler, tree trim, etc."`
  - `minLength=10`, `maxLength=2000`
  - Character counter + live hint under the field
  - `data-testid="rs-details"`, `data-testid="rs-details-count"`,
    `data-testid="rs-details-hint"`
- Preferred Date input kept (optional). Testid `rs-date`.
- Submit button testid `rs-submit`.

Mobile ask:

1. On `/app/mobile/app/(portal)/request.tsx` (or the equivalent):
   - Remove the Service Type `Picker` / `SelectField`.
   - Add a `<TextInput multiline numberOfLines={6}
     textAlignVertical="top">` with the same label + placeholder + limits
     + counter + hint.
   - Preserve the preferred-date field.
   - Preserve any attachment upload behavior if present.
   - `testID`s: `rs-details`, `rs-details-count`, `rs-details-hint`,
     `rs-date`, `rs-submit`.
2. Post payload to the existing endpoint:
   ```json
   POST /api/customer-portal/service-requests
   {
     "request_details": "<paragraph>",
     "preferred_date": "YYYY-MM-DD (optional)"
   }
   ```
   The backend now defaults `service_type` to `"general_request"` if
   omitted — DO NOT send `service_type` from mobile.
3. Legacy `notes` field is still accepted by the backend for older
   deployed mobile builds during the rollout window, but new code
   should use `request_details`.
4. Notifications (email to Brian + SMS to +1 602-887-4400) are fired
   **server-side** — mobile has NOTHING extra to do for those.

### Backend contract summary

```
POST /api/customer-portal/service-requests
Body:
  request_details: string (required, 10..2000 chars)
  preferred_date:  string (optional, YYYY-MM-DD)
Response 200:
  { ok: true,
    message_id: <uuid>,
    notified_admins: N,
    email_notification: { to, status },
    sms_notification:   { to, status } }
```

`email_notification.status` / `sms_notification.status` will be one of
`sent | queued | mocked | suppressed | failed | skipped`. All statuses
are non-blocking — the customer always sees success.

### Guardrails

- English only.
- No mobile-side email/SMS sends. That's the backend's job.
- Do NOT reintroduce the Service Type picker "just in case."
- Preserve the existing pull-to-refresh and toast patterns.
- Keep `testID`s stable so QA regression suites keep passing.
- No changes to the admin/dispatch mobile surface.

### Reference paths

- Web request page: `/app/frontend/src/pages/portal/PortalPages.jsx`
  (function `PortalRequestService`, ~line 720)
- Backend endpoint: `/app/backend/routers/customer_portal.py`
  (function `create_service_request`, ~line 436)
- Web nav files:    `/app/frontend/src/nav/roleNav.js`,
                    `/app/frontend/src/layouts/AppLayout.jsx`
- Web router:       `/app/frontend/src/App.js` (`/portal/book` shim)

### Deploy

- Mobile: OTA / EAS update after merge. No native module changes.
