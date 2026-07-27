## Delegation Brief · Phase 34 (web) → Phase 33 (mobile)
### Portal Home — Last Visit moved above Refer a Friend

**From:** Web team · Phase 34 · Feb 2026 · Task R
**To:** e1_expo_frontend_dev
**Priority:** P3
**Language:** English only.
**Status:** Web shipped. Mobile parity outstanding.

---

### What changed on web

`/app/frontend/src/pages/portal/PortalHome.jsx`

The Last Visit card (`data-testid="last-visit-card"`) used to render
at the very bottom of the portal home (after Business Card). It has
been moved to render directly under the Ask a Concierge block and
above the Refer a Friend section. No content / styling / handler
changes — pure DOM relocation.

New render order on the portal home (top → bottom):

1. Top CTA row (Call Now + Request Service)
2. Welcome-back hero card
3. Stat circles
4. Alerts row
5. Terms of Service banner (conditional)
6. Quick Actions grid
7. Ask a Concierge
8. **Last Visit ← moved here**
9. Refer a Friend
10. My Referrals
11. Business Card

### What we need from mobile

Corresponding mobile home screen: `/app/mobile/app/(portal)/index.tsx`
(or the equivalent in the current expo-router tree).

1. Find the Last Visit card render (search `last-visit-card` testID or
   the "Last visit" copy).
2. Physically MOVE the render so it sits between the Ask Concierge
   block and the Refer a Friend block.
3. Preserve `testID="last-visit-card"` verbatim so QA regression
   suites keep working.
4. Do NOT change styling, handlers, or props.

### Guardrails

- No backend touches. The card data comes from the existing
  `/api/customer-portal/home` payload.
- English-only.
- Preserve empty-state behavior — hide the card entirely when there
  is no `data.last_visit`.

### Reference paths

- Web page: `/app/frontend/src/pages/portal/PortalHome.jsx`
  (search `data-testid="last-visit-card"` — new position sits
   between the concierge block and `<ReferralSection />`)

### Deploy

- Mobile: OTA / EAS update after merge.
