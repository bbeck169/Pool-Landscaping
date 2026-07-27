## Delegation Brief · Phase 34 (web) → Phase 33 (mobile)
### Portal Home — Move "Ask a Concierge" Above "Refer a Friend"

**From:** Web team · Phase 34 · Feb 2026
**To:** e1_expo_frontend_dev
**Priority:** P2
**Language:** All comments, tests, and copy in **English**.
**Status:** Web shipped. Mobile parity outstanding.

---

### What changed on the web

`/app/frontend/src/pages/portal/PortalHome.jsx`

The "Ask a concierge" AI Employees block used to render at the very
**bottom** of the portal home (after the Last-visit card). It has been
moved to render **immediately above** the "Refer a Friend" section.

The final vertical order of the middle-of-page sections on web is now:

1. Hero card (already at top — see phase33_portal_home_hero_top_mobile.md)
2. Stat circles / alerts
3. Quick Actions grid
4. **Ask a concierge (AI Employees) ← MOVED HERE**
5. Refer a Friend (`<ReferralSection />`)
6. My Referrals (`<MyReferralsSection />`)
7. Business Card
8. Last visit card

Nothing else moved. No content, styling, or props changed — pure DOM
reorder only.

### `data-testid`s preserved (mirror to `testID` on mobile)

- `portal-ai-section`         (the whole "Ask a concierge" block)
- `portal-ai-<key>-card`      (per-employee card, e.g. `portal-ai-billy-card`)

---

### What we need from mobile

Mobile portal home is at `/app/mobile/app/(portal)/index.tsx` (or the
equivalent in the current expo-router tree — see `_layout.tsx` for the
source of truth).

1. Locate the AI Employees / concierge section render.
2. Move it in the JSX tree so it renders **immediately above** the
   "Refer a Friend" section (whichever component that maps to on
   mobile — likely `<ReferralSection />` or an inline block).
3. Preserve all `testID`s exactly as on web (see table above).
4. Do **not** change styling, spacing, copy, props, or icons. If a
   `marginTop` needs adjusting so the visual rhythm matches the new
   position, keep the change surgical (one style tweak, no rewrite).
5. If the AI Employees section is rendered by a child component that
   decides its own position, adjust the parent's ordering rather than
   restyling the child.

---

### Guardrails

- Do NOT touch backend endpoints. The concierge cards read from
  `GET /api/customer-portal/ai-employees` — nothing changed there.
- Do NOT reintroduce the block at the bottom "just in case."
- Do NOT localize; English only.
- Preserve empty-state behaviour: hide the whole block when the
  `aiEmployees` array is empty (matches web).

---

### Reference paths

- Web page:    `/app/frontend/src/pages/portal/PortalHome.jsx`
                (search for `data-testid="portal-ai-section"` — new location
                 is right above `<ReferralSection />`)
- Web Vitest:  `/app/frontend/src/test/phase34-portal-concierge-reorder.test.jsx`
                (optional — add if project convention requires)

### Deploy

- Mobile: OTA / EAS update after merge. No native modules required.
