# Delegation Brief · e1_expo_frontend_dev · Phase 33 · Brand Logo Consistency

**From:** Web team (Phase 33 · Feb 2026)
**To:** Expo mobile frontend
**Priority:** P2
**Status:** Web + backend PDF templates shipped. Mobile parity blocked on your side.

## Context
User confirmed `/app/frontend/public/logo-full.png` (green leaf + blue water splash + "POOL & LANDSCAPING OF VISTANCIA" text) is the correct brand mark. It has now been rolled out across every brand-visible surface:

- **Web login (`Login.jsx`):** logo (140px tall, centered) → "Welcome to" (48px) → "Pool & Landscaping of Vistancia LLC" (24px, exactly half). All centered, stacked vertically on the hero panel.
- **Mobile login (`login.tsx`):** logo (120px, `width: 80%`) → same two-line header (28px / 14px). `heroTop` layout flipped from `flex-direction: row` to `column` + centered `textAlign` on brand text lines.
- **Estimate HTML template (`routers/estimator.py::_estimate_html`):** `<img>` header at 120px tall, centered, above the existing header block. Reads tenant's stored logo URL (`settings.business_card.logo_url`) with fallback to `https://app.plofv.com/logo-full.png`.
- **Invoice HTML/PDF templates:** deferred — the two invoice routers (`invoices_mp15.py`, `invoice_viewer.py`) do not currently embed HTML templates in the ways we're used to; user directive was **additive only**, so we're leaving them alone until we can verify the render path. Follow-up work item.
- **Mobile asset already in place:** `/app/mobile/assets/logo-full.png` (was already there — same file as web).

## Ask
Verify mobile parity and finish the remaining mobile-side surfaces:

1. **Login screen** — already done web-side; the layout change in `/app/mobile/app/login.tsx` is live. Please smoke-test on iOS + Android hardware and verify the logo renders crisply at native resolution. If you need a `logo-full@2x.png` / `@3x.png` variant for retina, generate one and drop it next to the existing file.

2. **Splash / launcher icon** — currently the Expo app's icon and splash use a generic placeholder (see `app.json` / `app.config.ts`). Replace with the brand logo:
   - `icon`: crop or letterbox the leaf+splash portion to a square (recommend 1024×1024 PNG with transparent background).
   - `splash.image`: full logo centered on the app's brand color background.
   - Regenerate the Android adaptive icon foreground / background layers if needed.
   - Follow the Expo docs for `expo prebuild` if you're using CNG.

3. **`<BrandLogo>` reusable component** — create `/app/mobile/src/components/BrandLogo.tsx` with the API:
   ```tsx
   <BrandLogo size="sm" | "md" | "lg" />
   ```
   - `sm` = 40px tall (headers, drawer, cards)
   - `md` = 80px tall (modals, sub-screens)
   - `lg` = 140px tall (login, splash, marketing)
   - Wraps `expo-image`'s `<Image>` with `source={require("../../assets/logo-full.png")}`, `contentFit="contain"`, and `accessibilityLabel="Pool & Landscaping of Vistancia"`.

4. **Refactor mobile surfaces to use `<BrandLogo />`:**
   - Login screen — swap the inline `<Image>` (added by web team in the Phase 33 pass) for `<BrandLogo size="lg" />`.
   - Drawer / header — if there's a top-nav bar with a small logo, wire `<BrandLogo size="sm" />`.
   - Customer portal, invoice preview, estimate preview inside the mobile app — same treatment.

5. **Icon-only variant (optional, defer if effort > 30 min):** if the codebase has surfaces that need just the leaf+splash without the text (favicon, tab-bar icon, sidebar collapsed state on tablets), generate `logo-icon.png` from the existing full logo by cropping the mark. The web team hasn't done this yet — deferred to whichever team has ImageMagick / a design pipeline handy.

## Guardrails
- `expo-image` for all logo renders — not the built-in RN `Image` (better cache + FastImage-parity).
- `accessibilityLabel="Pool & Landscaping of Vistancia"` on every render.
- Do NOT touch backend endpoints; PDF/email templates already handle the logo server-side.
- Do NOT modify `Login.jsx` (web-only file).
- No native module additions — everything above should work with the existing Expo SDK 50+ / RN 0.73+ stack.

## Web references
- Web login: `/app/frontend/src/pages/Login.jsx` (Phase 33 layout — logo top, then two-line brand header centered)
- Estimate template: `/app/backend/routers/estimator.py::_estimate_html`
- Existing mobile login: `/app/mobile/app/login.tsx` (Phase 33 layout already applied; you're refactoring to `<BrandLogo />` next)
- Vitest coverage: `/app/frontend/src/test/phase30-login-tweaks.test.jsx` — proves DOM order `[logo] → [line1] → [line2] → [form]` on web; mirror this in an Expo Jest / Detox test if your suite supports it.

## Deployment
- Backend + web: prod redeploy after these changes are merged.
- Mobile: OTA/EAS update needed after your side ships. No native module changes if you stick with `expo-image` + `require()`.
