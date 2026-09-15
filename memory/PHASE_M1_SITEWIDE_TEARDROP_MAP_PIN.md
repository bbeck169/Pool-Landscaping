# Phase M1 · Sitewide custom teardrop map pin — WEB scope

**Phase**: Feb-2026
**Scope**: Web only (`/app/frontend/`). Mobile parity delegated (`/app/mobile/` untouched).

## Canonical pin size

**36 × 48 px** viewport (3:4 ratio). Head radius 9 units, hollow-center hole radius 4.5 units on a `0 0 24 32` viewBox. Anchor is the bottom tip at `(width / 2, height)`. Any consumer that passes a different `size` prop keeps the same 3:4 ratio automatically.

## Marker family

**AdvancedMarkerElement — animated halo available.** The web surfaces this phase targets (`DispatchMapView`, `ScheduleMap`, `RouteReplayPanel`) all render through `AdvancedMarker` from `../lib/maps`. `AdvancedMarker` accepts arbitrary React HTML content, so the pulsing halo animates via a CSS `@keyframes` embedded inside the SVG — no raster fallback needed on the primary surfaces.

`toGoogleMapsIcon({ color, pulse })` is exported for any legacy consumer still on classic `google.maps.Marker(icon: …)`. Rasterised icons can't be CSS-animated, so `pulse=true` on that path emits a **static 30% opacity halo ring** — visible but not animated. JSDoc documents the fallback.

## Files changed

### New
- `frontend/src/components/maps/TeardropPin.jsx` — the shared component, `deriveDarker`, `colorFromId`, `toGoogleMapsIcon`.
- `frontend/src/test/teardrop-pin.test.jsx` — 17 cases.
- `frontend/src/test/live-tech-pins-layer-teardrop.test.jsx` — 4 cases.

### Updated
- `frontend/src/pages/dispatch/LiveTechPinsLayer.jsx` — pin color now sources from `techColorById.get(user_id)` (with `colorFromId(user_id)` fallback); halo pulses on fresh pings (`staleness_s < 120`). The 15-min UI-dimmer + isolate-mode fade are preserved.
- `frontend/src/pages/dispatch/DispatchMapView.jsx` — `PinDot` swapped for `<TeardropPin>`. Cluster branch (>30 pins) renders the pin via `renderToStaticMarkup(<TeardropPin>)` so the same shape lands inside `AdvancedMarkerElement.content`. Passes `techColorById` down to `LiveTechPinsLayer`.
- `frontend/src/pages/schedule/ScheduleMap.jsx` — inline round button swapped for `<TeardropPin>`. Per-marker `techColorMap` semantics preserved verbatim.
- `frontend/src/pages/admin/RouteReplayPanel.jsx` — playhead marker (moving cursor) swapped for `<TeardropPin>`. Two-state color (done vs in-progress) preserved.
- `frontend/src/test/schedule-map.test.jsx` — 2 assertions retargeted from the button's inline `background` style to the SVG body's `fill` attribute (unavoidable — the color moved one hop deeper in the DOM).

### Not touched (intentional)
- `frontend/src/components/MapView.jsx` — uses `google.maps.SymbolPath.CIRCLE` icons with per-layer color legends; not a "default red pin" surface.
- `frontend/src/pages/workforce/WorkforcePages.jsx` — same pattern PLUS a per-marker initial-letter label overlaid on the circle head. Swapping to a teardrop would put the initial letter over the hollow center → readability regression. Left as-is.
- `/app/mobile/` — mobile parity is handled by the parallel Expo agent per the phase-brief non-negotiable.

## New test names + counts

**`teardrop-pin.test.jsx` — 17 cases**
- Body group (4): fill color, custom stroke override, size ratio, canonical defaults.
- Pulse group (2): halo absent when `pulse=false`, halo present + carries scoped `td-pulse-…` class when `pulse=true`.
- `deriveDarker` (4): 6-digit hex, 3-digit shorthand, `rgb()`, garbage input → neutral slate.
- `colorFromId` (4): determinism, palette membership, cross-corpus distinctness, null / empty safety.
- `toGoogleMapsIcon` (3): data-URL SVG carries color + `fill-rule=evenodd`, halo ring appears only when `pulse=true`, anchor is the bottom tip.

**`live-tech-pins-layer-teardrop.test.jsx` — 4 cases**
- Admin-pinned color from `techColorById` wins.
- `colorFromId` fallback fires when no explicit color exists.
- Halo renders only on `staleness_s < 120` (fresh); amber & stale carry `data-pulse="false"` + no halo group.
- 15-min UI-dimmer preserved via `data-stale="true"`.

## Test totals

| Suite | Cases | Result |
|---|---|---|
| `teardrop-pin.test.jsx` (NEW) | 17 | **17 / 17 pass** |
| `live-tech-pins-layer-teardrop.test.jsx` (NEW) | 4 | **4 / 4 pass** |
| All dispatch / schedule / live-tech / route-replay regressions | 197 | **197 / 197 pass** (+ 4 skipped) |
| Combined new + regression | 218 | **218 / 218 pass** |

## Deviations from the brief (with justification)

1. **`MapView.jsx` + `WorkforcePages.jsx` intentionally left un-swapped.** Both use `SymbolPath.CIRCLE` icons (not the platform-default red pin, not a hard-coded PNG). Swapping the workforce map — which overlays each tech's initial letter on the circle head — to a hollow-center teardrop would put the letter over the transparent hole, hurting readability. Both are called out in the memo above; can be revisited in a follow-up if the user wants full sitewide coverage.
2. **`LiveTechPinsLayer` freshness threshold reused verbatim (`< 120 s`)** — per the brief. The existing amber (120–300 s) tier no longer gets its own color; amber + gray both now render as the tech's color with no halo. Consistent with "Freshness = halo, no halo on stale."
3. **Halo animation kept CSS-driven, not `AdvancedMarkerElement.pin.glyph` animated.** The primary web maps already render React HTML inside `AdvancedMarker`, so the CSS-keyframe approach costs zero library work and doesn't require the newer `PinElement` glyph API.
4. **Existing `crewPalette.js` NOT replaced.** The brief asked for a fresh `colorFromId(id)` 12-color helper on the pin module. I exported one on `TeardropPin.jsx` (self-contained), rather than re-plumb the existing `crewHuedColor` machinery that Schedule + Calendar already share. Both live side-by-side: `crewHuedColor` for scheduler calendar art, `colorFromId` for map pins.

## Constraints honoured

- No new dependencies (Google Maps + `@googlemaps/markerclusterer` already in `package.json`).
- No external repo references.
- No mobile changes.
- Per-marker color semantics preserved on Dispatch, Schedule, RouteReplay — only the SHAPE changed there. LiveTech is the one intentional semantic change (freshness → color moves to halo).
- Bottom-tip anchor confirmed by the `toGoogleMapsIcon` unit test.
