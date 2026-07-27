## Delegation Brief · Phase 34 (web) → Phase 33 (mobile)
### Portal Home — Last Visit moved ABOVE Ask a Concierge (revised)

**From:** Web team · Phase 34 · Feb 2026 · Task R (revised)
**To:** e1_expo_frontend_dev
**Priority:** P3
**Language:** English only.
**Status:** Web shipped. Mobile parity outstanding.

**Note:** supersedes the earlier
`phase33_portal_last_visit_above_referral_mobile.md` brief (deleted).
Target position changed from "above Refer a Friend" to
"above Ask a Concierge".

---

### What changed on web

`/app/frontend/src/pages/portal/PortalHome.jsx`

The Last Visit card (`data-testid="last-visit-card"`) now renders
immediately **above** the Ask a Concierge block (`data-testid=
"portal-ai-section"`). Content / styling / handlers unchanged — pure
DOM relocation.

Final render order on the portal home (top → bottom):

1. Top CTA row (Call Now + Request Service)
2. Welcome-back hero card
3. Stat circles
4. Alerts row (Overdue / Pending estimates / Unread messages)
5. Quick Actions grid
6. **Last Visit ← now here**
7. Ask a Concierge
8. Refer a Friend (`ReferralSection`)
9. My Referrals (`MyReferralsSection`)
10. Business Card

The Terms of Service nudge banner has been removed entirely (Task S′).

### What we need from mobile

Corresponding mobile home screen (likely
`/app/mobile/app/(portal)/index.tsx`):

1. Find the Last Visit card render (search `last-visit-card` testID
   or the "Last visit" copy).
2. Physically MOVE the render so it sits immediately above the Ask
   a Concierge block (`testID="portal-ai-section"`).
3. Preserve `testID="last-visit-card"` verbatim.
4. Do NOT change styling, handlers, or props.
5. Preserve empty-state behaviour — hide the card entirely when
   there is no `data.last_visit`.

### Guardrails

- No backend touches. The card data comes from the existing
  `/api/customer-portal/home` payload.
- English-only.
- The old brief with the "above Refer a Friend" target is
  SUPERSEDED — do not honour it.

### Reference

- Web page: `/app/frontend/src/pages/portal/PortalHome.jsx`
  (search `data-testid="last-visit-card"` — new position is
   immediately above `data-testid="portal-ai-section"`)

### Deploy

- Mobile: OTA / EAS update after merge.
