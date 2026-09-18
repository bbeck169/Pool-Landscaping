# Native TeardropPin Device Verification Checklist

Last updated: 2026-02-18
Target build: production (after `@react-native-community/slider` native dep + redesigned pin ship)

## Prerequisites
- iOS or Android device with the latest production build installed (post `eas build --profile production` from the ops runbook at `/app/memory/ops_runbook_prod_deploy.md`)
- Admin login credentials (see `/app/memory/test_credentials.md`)
- At least one job scheduled today with a technician assigned
- At least one active tech route with jobs on the calendar
- Cellular OR Wi-Fi connectivity (map tiles + GPS pings need the network)

## Test 1 — Dispatch Board / Schedule map pin geometry
1. Open the app, sign in as admin
2. Navigate to the Schedule tab
3. Confirm each visible job renders as a teardrop pin with:
   - [ ] Colored teardrop head (per-tech color)
   - [ ] White inner circle inside the head
   - [ ] Numbered/lettered label centered in the white circle
   - [ ] Tapered stem pointing down to the geographic anchor
   - [ ] Soft drop shadow beneath the tip
4. Screenshot at least one pin cluster
5. Tap a pin — the callout/detail sheet should surface without a red-box

## Test 2 — Live tech tracking (if GPS active)
1. Navigate to the Live Tech / Routes screen
2. Confirm each tech marker renders as a teardrop pin
3. Confirm tech initials appear in the white inner circle (label centered)
4. If a tech is moving with GPS bearing enabled:
   - [ ] (future — pending mobile parity for Feb-2026 Sprint 1 Section D) confirm the direction chevron sits above the head and points forward relative to the tech's heading
   - [ ] Chevron color matches the pin fill
   - [ ] Chevron rotates smoothly as the bearing updates

## Test 3 — Color contrast with pin body
1. Assign a technician a bright color (e.g., amber `#F59E0B`, cyan `#06B6D4`) via admin Web → Team → color swatch
2. Reload the mobile app (kill + reopen)
3. Confirm that tech's pins render the new color at good contrast against the map tile — the label inside the white inner circle should still be legible
4. Assign an off-palette color the backend blocks (e.g., pure white `#FFFFFF`):
   - [ ] Web returns 400 `color_contrast_too_low` and the mobile app never sees an unreadable pin

## Test 4 — ColorPicker screen (native module smoke test)
1. Navigate to admin → technician detail → "Map pin color"
2. Confirm the picker opens without a red-box crash (this exercises the `@react-native-community/slider` native dep)
3. Slide the picker; the preview should update smoothly (no dropped frames on mid-tier hardware)
4. Save a new color; return to the map; confirm the new color is applied on the next tile load

## Test 5 — Clustering + zoom transitions (regression guard)
1. Zoom out until pin clustering activates
2. Confirm cluster bubbles render (numbered) — teardrops should NOT appear at cluster zoom levels
3. Zoom back in — cluster bubbles should split back into individual teardrop pins with the correct color + label per tech
4. Pan / pinch / rotate — pins should stay anchored at the correct lat/lng (bottom-tip anchor, NOT center)

## Failure modes to look for
- Pins render as pinpoint dots or default markers instead of the teardrop SVG → react-native-svg or Skia not correctly linked; needs a rebuild
- Label text overflows or misaligns → font-size scaling issue on this device class; log the device model + OS version
- ColorPicker crashes on open → slider native module not in the current build; needs `eas build --profile production` with the current `mobile/package.json`
- Drop shadow missing → RN-SVG version mismatch; verify the version in `mobile/package.json` matches the last-known-good ship
- Chevron never appears (once mobile parity ships) → GPS bearing not propagated by the ingest endpoint; verify `POST /api/gps/pings` payload carries `heading_degrees`

## Reporting back
Send the screenshots + any failing checkbox items to the dev team with:
- Device model (e.g., iPhone 14 Pro, Pixel 7)
- OS version (e.g., iOS 17.4, Android 14)
- App build number (Settings → About)
- Timestamp + Wi-Fi/cellular state
- Which technician you were viewing (for tenant-scoped reproducibility)

## Owner + escalation
- **Primary QA owner**: ops team on-call
- **Escalation path**: mobile-parity delegation agent (do NOT edit `/app/mobile/` directly)
- **Related runbook**: `/app/memory/ops_runbook_prod_deploy.md` (build + release checklist)
- **Related web parity**: `/app/frontend/src/components/maps/TeardropPin.jsx` (Feb-2026 Sprint 1 Section D added the `headingDegrees` chevron on the web pin; mobile parity is a separate mobile-agent ticket)
