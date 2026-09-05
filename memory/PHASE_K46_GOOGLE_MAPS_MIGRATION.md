# Phase K46 · Google-only Maps Migration (Feb 2026)

## Executive summary

Ripped `@rnmapbox/maps` out of the mobile stack (root cause of the
Phase K45 Android white-screen crash) and standardised the entire
Expo app on Google Maps via `react-native-maps`. Killed the last
HERE plugin remnants at the same time. Wired the shared native
navigation deep-link helper (`openNativeNavTo`) into every
"Navigate" button so techs can hop from a route pin straight into
Google/Apple Maps turn-by-turn without leaving the schedule
screen.

**An EAS rebuild is required.** Removing `@rnmapbox/maps` alters the
native auto-linked manifest — a JS-only OTA update cannot ship this
change. Run `eas build --profile <production|preview> --platform all`
before promoting a new store binary.

## Root cause recap (K45)

* The K45 investigation traced the persistent Android white-screen
  crash to `@rnmapbox/maps`' native constructor. On Fabric / new
  arch, that constructor throws synchronously at app boot when the
  Mapbox access token is missing or mis-wired at build time. The
  throw fires before the JS bundle finishes loading, blanking the
  shell.
* K45c experimented with a lazy-require pattern to defer the throw
  until first map render — the user later cancelled it. K46 is the
  permanent fix: no Mapbox at all.

## Files touched

### Mobile
| File | Change |
|------|--------|
| `mobile/src/components/dispatch/LiveTechPinsMap.tsx` | Full rewrite on `react-native-maps` + `PROVIDER_GOOGLE`. Style toggle now cycles `standard` / `satellite` / `hybrid` (Google `mapType` prop) instead of three Mapbox style URLs. AsyncStorage key unchanged (`dispatch_map_style_v1`). Guarded by `hasGoogleMapsKey()`. |
| `mobile/src/components/dispatch/LiveTechPinsWrapper.tsx` | Removed the dynamic-require try/catch and the "dev client required" fallback banner — `react-native-maps` ships with every Expo shell so no gate is needed. Poll cadence + expand toggle preserved. |
| `mobile/src/components/schedule/DailyRouteMap.native.tsx` | Already migrated to `react-native-maps` earlier in this session; K46 adds a "Navigate" button to the pin callout that dispatches through `openNativeNavTo`. |
| `mobile/src/components/schedule/NavigateJobButton.tsx` | Replaced the `mapsDeepLink.ts` path with `openNativeNavTo`. Coord-only for the K46 native scheme; falls back silently to universal HTTPS Google Maps directions when the native scheme isn't openable. |
| `mobile/src/utils/mapsKey.tsx` | Dropped `hasMapboxToken` — the helper is now Google-only. |
| `mobile/app.config.js` | Removed the `["@rnmapbox/maps", {}]` plugin registration and the `extra.mapboxToken` plumbing. Google Maps API keys stay wired via `android.config.googleMaps.apiKey` / `ios.config.googleMapsApiKey`. |
| `mobile/app/_layout.tsx` | Deleted the `__DEV__` Mapbox token placeholder guard useEffect. |
| `mobile/package.json` | Removed `@rnmapbox/maps` from `dependencies`. `yarn install` regenerated `yarn.lock` (Mapbox subtree fully purged). |

### Tests
| File | Change |
|------|--------|
| `mobile/__tests__/mapsKey.test.ts` | Removed the `hasMapboxToken` tests + added a regression guard asserting the symbol is no longer exported. |
| `mobile/__tests__/k46-google-maps-only.test.ts` | **New** — Jest source-inspection guard for the entire K46 landing state (package.json, app.config.js, LiveTechPinsMap, wrapper, Navigate buttons, root layout). |
| `frontend/src/test/phase38b-live-pins.test.jsx` | Rewritten as a K46 lock-in test — verifies Mapbox is absent, Google-only surfaces are wired, and the wrapper no longer does dynamic-require. |
| `frontend/src/test/phase38-mobile-dispatch-parity.test.jsx` | Flipped the "@rnmapbox/maps must be present" assertion to "must be absent". |

### Preserved on purpose
* `backend/services/reverse_geocoder.py` — still calls Mapbox's geocoding API server-side. Per user directive this file stays as-is; the K46 scope is client-side only.
* `mobile/src/lib/maps/hereAdapter.tsx` / `provider.ts` / `heresdkStatus.generated.ts` — the K45b nuclear stub of HERE is left intact. The Adapter no-ops end-to-end and the resolver always returns `google`; no runtime side effects.
* `mobile/src/services/navigation/mapsDeepLink.ts` — Still exists for address-based deep links (which the K46 coord-only helper doesn't cover). Both helpers coexist.

## Contract of `openNativeNavTo(lat, lng, label?)`

```
iOS      → maps://?daddr=<lat>,<lng>[&q=<label>]      (Apple Maps)
Android  → google.navigation:q=<lat>,<lng>            (Google Maps intent)
Fallback → https://www.google.com/maps/dir/?api=1&destination=<lat>,<lng>
```

Silent fallback to the universal HTTPS URL when the native scheme
isn't openable (e.g. no default maps app on Android, or iOS 14+'s
`canOpenURL` returns false without an `LSApplicationQueriesSchemes`
entry). Never rejects. Coord-only by design — address-based navigation
is intentionally deferred to `mapsDeepLink.ts` for surfaces that
lack lat/lng.

## Verification

* `yarn install` — clean, `@rnmapbox/maps` gone from `yarn.lock`.
* `node -e "require('./app.config.js')"` — parses; 8 plugin entries; no `mapboxToken` in `extra`.
* Jest suite: `mapsKey.test.ts` passes; new `k46-google-maps-only.test.ts` locks in the state.
* Vitest suite: `phase38-mobile-dispatch-parity.test.jsx` + `phase38b-live-pins.test.jsx` refactored to enforce the Google-only landing.
* Backend Pytest: untouched — the migration is client-only.

## Deferred / follow-ups

* **EAS rebuild required.** Kick off a fresh `eas build` on the next promoted version — the auto-linked native manifest changed.
* **K47** — Invoice-view-tracking feature. Starts immediately after this ship report per the standing directive; answers locked at 1b / 2d / 3c / 4b.
* **`services/navigation/mapsDeepLink.ts`** — Still consumed by any address-only surfaces (there are none I could find, but the file stays as a safe fallback). Consider consolidating with `nativeNav.ts` in a future phase once we're sure no address-only path remains.
