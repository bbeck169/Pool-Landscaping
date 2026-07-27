## Delegation Brief · Phase 34 · Task T — Review gating (mobile)

**From:** Web / backend team · Phase 34 · Feb 2026 · Task T
**To:** e1_expo_frontend_dev
**Priority:** P2
**Language:** English only.
**Status:** Backend + web NOT YET SHIPPED. Brief documents the target
so mobile can build in parallel.

---

### Product intent

Classic NiceJob-style review gating. When a customer submits a
review through the app (portal, mobile, or the automated
post-service email/SMS):

- **4 or 5 stars** → prompt the customer to also post their review
  on the tenant's Google Business Profile.
- **1, 2, or 3 stars** → capture internally, do NOT prompt Google.
  Fire an internal alert email + SMS so the tenant can respond
  privately.

### Backend contract (target)

`POST /api/reviews`

Auth: authenticated portal customer.

Body:
```json
{
  "rating": 5,               // int 1..5
  "text":   "Loved the service!",
  "photos": ["https://…"],    // optional array of media URLs
  "visit_id": "…"            // optional link to a specific visit
}
```

Response 200:
```json
{
  "id": "<review_id>",
  "rating": 5,
  "prompt": "google" | "internal",
  "google_review_url": "https://g.page/r/…/review"  // only when prompt=google
}
```

Persistence (`reviews` collection):
```
id, tenant_id, customer_id, visit_id?,
rating, text, photos[],
is_public: (rating >= 4),
google_prompt_shown: (rating >= 4),
google_click_at?,          // populated by POST /api/reviews/{id}/google-clicked
created_at
```

Tenant setting (source of truth for the Google URL):
`settings.reviews.google_review_url` — for PLOFV populate this to
`https://g.page/r/Ca2a51Mdb29qEBM/review`. Bundle a small migration/
seed helper that upserts this value into the PLOFV tenant's
`settings` doc.

Internal-alert destinations (fall back to the Task-I service-request
defaults if the review-specific settings aren't set):
- `settings.notifications.negative_review_email` (fallback `brian@plofv.com`)
- `settings.notifications.negative_review_sms` (fallback `+16028874400`)

For `rating <= 3` the endpoint also fires (guarded, per Task L; will
dry-run in preview for everyone except the Brian allow-list):

- Email to negative-review email: subject `"New low-rating review from {customer} ({rating}★)"`, body includes rating, customer contact info, review text, deep link to the review in admin CRM.
- SMS to negative-review phone: short summary + deep link.

Both wrapped in try/except — a transport failure never blocks the
customer's ack.

### Frontend contract (target)

Both web and mobile submit forms behave identically:

1. Star rating (1–5) + optional textarea + optional photo upload.
2. Submit → POST `/api/reviews`.
3. If response `prompt == "google"`:
   - Show modal / follow-up screen. Heading:
     **"Thanks for the {rating}-star review! Would you mind sharing
     it on Google too?"**
   - Primary CTA "Post on Google" → opens
     `response.google_review_url` in a new tab (web:
     `target="_blank"`, `rel="noopener noreferrer"`; mobile: RN
     `Linking.openURL`).
   - Optional: pre-copy the review text to the clipboard
     (`navigator.clipboard.writeText` on web,
     `expo-clipboard.setStringAsync` on mobile) so the customer can
     paste it into the Google form.
   - Secondary "Maybe later" closes the modal.
   - Fire best-effort `POST /api/reviews/{id}/google-clicked` when
     the customer taps the Google CTA (analytics).
4. If response `prompt == "internal"`:
   - Show a private-feedback thank-you screen. Heading:
     **"Thanks for the honest feedback — we'll be in touch."**
   - Copy: "Your feedback goes directly to our management team so
     we can make things right."
   - No Google CTA.

Web testids (mobile mirrors as `testID`):
- `review-submit-form`, `review-rating-star-{1..5}`, `review-text`,
  `review-photos`, `review-submit`,
- `review-google-prompt-modal`, `review-google-cta`,
  `review-google-maybe-later`,
- `review-internal-thanks`, `review-internal-thanks-copy`.

### NiceJob-parity email / SMS templates

Every review-request email + SMS the tenant already sends
post-service should point the "Leave a Review" CTA at the internal
portal form FIRST, not directly at Google. The gating happens inside
the app. Templates the mobile agent doesn't own, but flag any
mobile-side deep links that go straight to Google — those must be
updated to route through the portal review submit screen.

### Analytics fields to persist

Aggregate per tenant per month (for a later dashboard tile):
`high_reviews`, `low_reviews`, `google_clicks`. Just persist the raw
review docs — the aggregation query can be added later without a
schema change.

### Mobile task

1. Locate or build the mobile review-submit screen (`/app/mobile/app/(portal)/reviews/submit.tsx` or the equivalent).
2. Wire submit to `POST /api/reviews` per the contract above.
3. Branch on `prompt`:
   - `"google"` → modal with the Google CTA. Use `Linking.openURL`
     to open the URL. Fire the `/google-clicked` analytics call.
   - `"internal"` → thank-you screen, no Google CTA.
4. Preserve every `testID` mirror to web.
5. Cache the tenant Google URL from `response.google_review_url` —
   do NOT hardcode it in the app.
6. Photo upload can go through the existing service-report media
   upload endpoint (or its equivalent for reviews if one exists);
   do NOT invent a new endpoint.

### Guardrails

- English-only.
- Do NOT auto-forward low reviews to any public site.
- Do NOT hardcode the Google URL client-side.
- Do NOT bypass the internal alert on `rating <= 3` — even if the
  transport fails, the endpoint must still return success to the
  customer.

### Reference paths (once web ships)

- Backend router: `/app/backend/routers/reviews.py`
- Web submit page: `/app/frontend/src/pages/portal/PortalReviewSubmit.jsx`
- Web pytest: `/app/backend/tests/test_phase34_task_t_review_gating.py`

### Deploy

- Mobile: OTA / EAS update. Depends on backend `/api/reviews` shipping first.
