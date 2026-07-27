## Delegation Brief · Phase 34 (web) → Phase 33 (mobile)
### Portal Home — Hero Card Moved to TOP, Greeting Tile Removed

**From:** Web team · Phase 34 · Feb 2026
**To:** e1_expo_frontend_dev
**Priority:** P2
**Language:** All comments, tests, and copy in **English**.
**Status:** Web shipped. Mobile parity outstanding.

---

### What changed on the web

`/app/frontend/src/pages/portal/PortalHome.jsx`

1. **Removed** the standalone greeting tile (`<GreetingTile />` block).
   The old friendly-copy card that sat at the top of the portal has been
   deleted from the render tree entirely. Do **not** try to preserve it
   under a mobile-first breakpoint — the product decision was: hero card
   replaces it globally.
2. **Moved** the "hero card" (the tall image-backed banner that used to
   sit lower in the page, below the quick-action tiles) to be the **first
   element after the top nav**. It is now the visual anchor of the portal
   home page.
3. Quick-action tiles (Photos / Videos / Service Reports / Book Visit)
   render **below** the hero card, in the same grid layout as before.
4. Vitest coverage: `/app/frontend/src/test/phase34-portal-home.test.jsx`
   asserts DOM order: `[hero]` → `[qa-service-reports]` etc.

Key `data-testid`s the web side now uses:
- `portal-hero`         (the relocated hero card)
- `portal-photos-page`, `portal-videos-page`, `portal-service-reports`
- `qa-service-reports`, `qa-photos`, `qa-videos`

---

### What we need from mobile

`/app/mobile/app/(portal)/index.tsx` (or wherever the Expo portal home
lives — file name may differ; use the routing table in
`/app/mobile/app/_layout.tsx`).

1. **Delete** the greeting tile component render (the
   "Good morning, {name}" card) from the portal home screen.
   If a `GreetingTile.tsx` exists under
   `/app/mobile/src/components/portal/` and is only used on the home
   screen, delete the file too. If used elsewhere, gate its usage.
2. **Reorder** the render so the hero card renders as the **first child
   of the ScrollView**, above every quick-action tile / list. Same
   ordering as the web page.
3. Keep the hero card's background image identical to the web version
   (Pexels URL `.../261101/...`), but load through `expo-image` (not
   RN's built-in `Image`) so caching is consistent with the rest of the
   app.
4. Preserve **all existing quick-action tiles** (Photos, Videos,
   Service Reports, Book Visit, etc.). Only the greeting card is
   removed; hero simply moves up.

---

### Copy & typography

- **Hero title** (H1 on the card): keep the web copy verbatim
  (see `PortalHome.jsx` around line 111–140 — copy is `"Your service
  history, in one place."` or the current variant). Do NOT re-write it.
- Font sizes on mobile: title = 28px, subtitle = 14px, both centered.

---

### `data-testid` parity (React Native)

React Native doesn't have `data-testid`, but Detox / Maestro read
`testID`. Map 1:1 to the web IDs above:

```tsx
<View testID="portal-hero" ...>
```

---

### Guardrails

- Do NOT touch backend endpoints. The portal home hero pulls
  everything it needs from data already available client-side.
- Do NOT reintroduce the greeting tile "just for mobile." Product
  decision applies globally.
- Do NOT use `flex-direction: row` on the hero — it's a vertical stack
  (image bg + centered title/CTA).
- English-only copy in commits, tests, comments, and PR description.

---

### Reference paths

- Web page:          `/app/frontend/src/pages/portal/PortalHome.jsx`
- Web Vitest:        `/app/frontend/src/test/phase34-portal-home.test.jsx`
- Mobile routing:    `/app/mobile/app/_layout.tsx`
- Mobile home target: `/app/mobile/app/(portal)/index.tsx`

### Deploy

- Mobile: OTA / EAS update after merge. No native modules required.
