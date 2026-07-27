# Phase 34 · Task Z — Business Card website row + width parity (Mobile)

> Mobile Expo delegation brief. **Do not touch web code**; the web
> agent has already shipped this change on the React portal.

## Web changes shipped (for context)
1. `PortalHome.jsx` — the wrapper around `<BusinessCard variant="compact" />`
   dropped its `max-w-md` cap so the card now spans the same width as
   `ReferralSection` / `MyReferralsSection` inside the `max-w-4xl` shell.
   Wrapper `data-testid="business-card-wrap"` was added for tests.
2. `BusinessCard.jsx` — the "website" `<Row>` (Globe icon + `plofv.com` link)
   is now rendered in **both** `full` and `compact` variants (previously
   gated on `!compact`). The URL is read from the merged business-card
   payload — `card.website_url` — which the backend defaults to
   `https://www.poolandlandscapingofvistancia.com/` for the aquaterra
   tenant via `_BUSINESS_CARD_DEFAULTS` in `routers/tenants.py`.

## Mobile parity task
On the Portal Home / equivalent surface in the Expo app:

* If the business card component has separate full/compact renderers,
  update the compact renderer to include the website row (same source
  URL — call the existing `/tenants/business-card` endpoint).
* Ensure the compact card container width matches the "Refer a Friend"
  card so the two cards line up on the profile home screen. This may
  require removing a width cap on the business-card `View` inside the
  home screen scroll list.
* Icon: use the same `globe` icon as the web (`lucide-react-native`
  ships a `Globe` — mirror the size used for phone/email rows).
* Open the URL via `Linking.openURL` (external browser) — do not
  render an in-app WebView for it.
* Preserve existing `testID` naming — add `business-card-website` for
  parity with the web `data-testid`.

## Verification checklist
- [ ] Website row visible on the compact card at
      `/portal/home` equivalent.
- [ ] URL opens the tenant website in the OS browser.
- [ ] Card width matches the Refer a Friend card exactly.
- [ ] No regression on Save/Share/Copy actions.

Ship as a single mobile PR referencing this brief.
