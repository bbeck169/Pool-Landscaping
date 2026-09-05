# Phase K45b · HERE Maps nuclear removal — SHIPPED
### with URGENT K45c call-out: `@rnmapbox/maps` is the actual Android crash suspect

**Feb-2026 · P0 · Mobile only · JS + Expo config plugin only**

---

## TL;DR

- Shipped everything K45b briefed (removed the last HERE references
  from the Expo config plugin, hard-throw sentinel in the adapter,
  full package.json / yarn.lock / plugin regression guards).
- **HERE was already gone from `package.json` / `yarn.lock` /
  `node_modules` before K45b started.** K45b closed the last remaining
  gap (the guarded `app.config.js` plugin entry).
- Strong new evidence: the ongoing Android white-screen is NOT caused
  by HERE. The actual crash source is almost certainly
  **`@rnmapbox/maps`** — the *installed* dep that drives the Schedule
  daily route map and uses the exact eager-require + missing-native
  pattern K45 identified. **Details in section 3 below — READ THIS.**

## 1. Autolinking evidence for HERE — was it in the build?

**No.** As of this workspace state (before K45b started):

| Location | HERE reference? |
|---|---|
| `mobile/package.json` `dependencies` | **NO** — `react-native-here-explore` is not listed |
| `mobile/package.json` `devDependencies` | **NO** |
| `mobile/yarn.lock` | **0 matches** for `here-explore` |
| `mobile/node_modules/react-native-here-explore/` | **Does not exist** |
| `mobile/android/` | Directory does not exist — this is a pure managed Expo project. Native folders are generated on-demand by `expo prebuild` inside EAS. |
| `mobile/ios/` | Same — does not exist in workspace. |
| `mobile/app.config.js` | **YES (before K45b)** — line 224-236 registered `react-native-here-explore` as an Expo config plugin, but guarded on `process.env.EXPO_PUBLIC_HERE_ACCESS_KEY_ID`. |
| `mobile/.env` `EXPO_PUBLIC_HERE_ACCESS_KEY_ID` | **Empty** — so the guard yielded `[]` (no plugin registered) at prebuild time. |

**Conclusion:** HERE was NOT being autolinked into the K45 EAS
build. The K45b hypothesis that "package.json presence causes
autolinking to try to load missing binaries" is correct in principle
but does not apply to this project's actual state. HERE was already
disabled at every layer that matters. K45b cleaned up the last
ceremonial reference (the guarded plugin block).

## 2. `package.json` diff (before / after K45b)

**Zero change to `package.json` / `yarn.lock`.** HERE was already
absent. Only `app.config.js` changed at the plugin-registration
layer:

```diff
       "expo-asset",
-      // Phase K39b · Feb-2026 — HERE Maps plugin.  Registered ONLY
-      // when the HERE credentials env is set so devs building with
-      // ``EXPO_PUBLIC_MAPS_PROVIDER=google`` (the default) don't have
-      // to touch HERE at all.  Manual .aar / .xcframework drop docs
-      // in ``mobile/heresdk/README.md``.
-      ...(process.env.EXPO_PUBLIC_HERE_ACCESS_KEY_ID
-        ? [
-            [
-              "react-native-here-explore",
-              {
-                accessKeyId: process.env.EXPO_PUBLIC_HERE_ACCESS_KEY_ID,
-                accessKeySecret: process.env.HERE_ACCESS_KEY_SECRET || undefined,
-              },
-            ],
-          ]
-        : []),
+      // Phase K45b · Feb-2026 — HERE Maps plugin registration removed.
+      // See mobile/heresdk/README.md for the re-enable procedure.
     ],
```

Plus the sentinel amendments to `hereAdapter.tsx` (hard-throw
`_loadHere`, placeholder for every export) and a new
`__tests__/k45b-here-removed.test.ts` regression guard.

## 3. **⚠️ URGENT — the real Android crash suspect: `@rnmapbox/maps`**

The user reports the Android white-screen survives K45 + a fresh EAS
build + reinstall. I did NOT touch this in K45b (out of scope per the
brief's non-goals), but here is the evidence I gathered:

### 3a. `@rnmapbox/maps` IS installed and IS the map engine

- `mobile/package.json` deps: `@rnmapbox/maps: ^10.1.34`
- Used directly (bypassing the `@/src/lib/maps` abstraction!) by:
  - `mobile/app/(app)/schedule/calendar.tsx` — **the exact Schedule surface that white-screens**
  - `mobile/src/components/schedule/DailyRouteMap.native.tsx`
  - `mobile/src/components/dispatch/LiveTechPinsMap.tsx` +
    `LiveTechPinsWrapper.tsx`
- The Expo config plugin is registered UNCONDITIONALLY in
  `app.config.js:202`: `["@rnmapbox/maps", {}]`.

### 3b. It has the SAME eager-require pattern K45 was written to fix

`mobile/src/components/schedule/DailyRouteMap.native.tsx:53-60`:

```ts
// Dynamic require — throws in Expo Go without the dev-client. We
// catch and render the fallback banner instead of crashing.
let MapboxGL: any = null;
let mapboxImportError: string | null = null;
try {
  MapboxGL = require("@rnmapbox/maps").default;
} catch (e: any) {
  mapboxImportError = e?.message || String(e);
}
```

This is **at module scope**. The `try/catch` only catches *JS
resolution errors*. If the native Mapbox constructor throws inside
`MainApplication.onCreate()` on Android (which happens when the
downloads token wasn't wired at Gradle build time, or when the
runtime access token flows through in a state Mapbox rejects), the
process dies before JS ever runs — the JS try/catch is powerless.

This is **exactly the K45 crash pattern**, just on a different (real,
installed) dep.

### 3c. Missing token wiring

- `mobile/.env` has `EXPO_PUBLIC_MAPBOX_TOKEN=pk.eyJ1IjoiYmJlY2sx…`
  (public runtime token — checked in to `.env`, so present in every
  build).
- **`RNMAPBOX_MAPS_DOWNLOAD_TOKEN` (the `sk.*` build-time token) is
  NOT in `.env`** — only in `.env.example`. Per Mapbox's docs, this
  is REQUIRED as an EAS secret for the Android Gradle build to
  download the Mapbox Maps AAR. If it's missing on the EAS build
  environment, the Android build produces a broken app that crashes
  at `MapboxMapView`'s constructor.
- Only `LiveTechPinsMap.tsx:78` calls `Mapbox.setAccessToken()`.
  `DailyRouteMap.native.tsx` (Schedule) never calls it. If Schedule
  is the first Mapbox surface to mount, tile source will fail — but
  that alone should degrade gracefully, not crash. The
  eager-require + native-constructor-throw path is the crash.

### 3d. What K45c should do

**Do NOT do this in K45b — the user's brief was explicit "Everything
else is paused."** Filing this as a K45c candidate for the next
dispatch:

1. **Move the `require("@rnmapbox/maps")` in
   `DailyRouteMap.native.tsx` into a lazy loader inside a component
   body** — exact same shape as K45's `_loadHere()` fix for HERE.
2. Same for `LiveTechPinsMap.tsx` (already better — its Mapbox use
   is inside an effect, but the top-level `import` should still be a
   dynamic `require`).
3. **Verify `RNMAPBOX_MAPS_DOWNLOAD_TOKEN` is configured as an EAS
   secret** on the build project. If it isn't, that alone explains
   the Android crash without any code change — but the eager require
   is still wrong on principle.
4. Wrap every Mapbox surface in an ErrorBoundary that renders the
   Google adapter fallback via `@/src/lib/maps`. Right now Schedule
   bypasses the `@/src/lib/maps` abstraction entirely.
5. Consider consolidating: `react-native-maps` (Google) + `@rnmapbox/maps`
   (Mapbox) both installed is redundant. Pick one. If Google is
   fine, drop Mapbox to eliminate the whole class of crash.

## 4. Belt-and-suspenders audit of other unused native deps

Per your instruction — reported, NOT removed:

| Package | Direct JS imports | Native? | Recommendation |
|---|---|---|---|
| `react-native-webrtc` | 1 file (`walkie/LivePanel.tsx`) | Yes, heavy | **Keep** — actively used by the walkie feature. |
| `@config-plugins/react-native-webrtc` | Config plugin | Native | **Keep** — required by the above. |
| `react-native-signature-canvas` | 1 file | WebView-based, lightweight | **Keep** — actively used. |
| `expo-speech-recognition` | 0 direct `import from` matches — but actually used in `app/os/lana.tsx` via a different import style | Native mic access | **Keep** — investigate the import shape but it's actively used. |
| `expo-symbols` | 0 imports found | iOS SF Symbols | **Investigate** — possibly dead code; low crash risk (Expo module, well-behaved). Consider dropping in a later cleanup phase. |
| `react-native-worklets` | 0 direct imports | Peer of Reanimated 4.x | **Keep** — transitive peer dep of `react-native-reanimated: 4.1.1`. Removing breaks Reanimated. |
| `expo-task-manager` | 3 files | Native background tasks | **Keep** — actively used. |
| `expo-video-thumbnails` | 1 file | Native ffmpeg | **Keep** — actively used. |
| `react-native-plaid-link-sdk` | Not installed | N/A | Already absent — Stripe Financial Connections path is used instead. |
| `react-native-here-explore` | Not installed (this phase's target) | N/A | Now enforced-absent by K45b's regression guard. |

**Nothing else looked like a crash candidate at the same severity
class as `@rnmapbox/maps`.**

## 5. Prebuild output

**Cannot run `expo prebuild --clean` in this workspace** — the pod
doesn't have the full Android SDK / Xcode toolchain locally, and
prebuild output for a real device belongs on EAS, not in the dev
container. The regression guard in
`__tests__/k45b-here-removed.test.ts` covers the invariant that
matters (no HERE plugin reference in `app.config.js`), which
`expo prebuild` reads at build time.

If the user wants a prebuild dry-run, that has to happen on the EAS
side or on a workstation with the Expo CLI + SDK toolchain — I'll
happily draft an EAS build-hook script that fails the build if a
grep for `react-native-here-explore` in the generated
`android/settings.gradle` returns anything.

## 6. Test result delta

```
$ cd /app/mobile && yarn jest __tests__/k45b-here-removed.test.ts \
    __tests__/k45-lazy-here.test.ts \
    __tests__/maps-abstraction.test.ts \
    __tests__/portal-maps-guard.test.ts
Test Suites: 4 passed, 4 total
Tests:       40 passed, 40 total
```

- **New K45b suite:** 5 tests, all green (package.json guard,
  yarn.lock guard, app.config.js guard, hard-throw contract, no-crash
  barrel resolve under `provider=here`).
- **Updated K45 suite:** the "no top-level require" test now asserts
  the require is entirely absent (K45b superset of K45).
- **Full mobile jest run:** same 921 pass / 32 pre-existing fails as
  the K45 baseline. No new regressions.

## 7. **⚠️ USER ACTION REQUIRED — you MUST cut a new EAS build**

**OTA update alone will NOT propagate this fix** because the Expo
config plugin list changed (removed the HERE plugin registration).
The generated native manifest for Android AND iOS will differ from
the K45 build.

1. `cd mobile && yarn install` (to be safe — no lockfile changes
   expected, but confirms the tree is clean).
2. Cut a new EAS build (Android + iOS).
3. Reinstall on device.
4. **However** — based on section 3 above, I do NOT expect this
   build alone to fix the Android white-screen. The K45c Mapbox
   fix is the follow-up you'll need.

## 8. Files changed

```
 M mobile/app.config.js                          — plugin removal
 M mobile/src/lib/maps/hereAdapter.tsx           — hard-throw sentinel
 M mobile/heresdk/README.md                      — re-enable procedure
 M mobile/__tests__/k45-lazy-here.test.ts        — assertion softened
                                                   (require entirely gone)
?? mobile/__tests__/k45b-here-removed.test.ts    — package guard suite
```

## 9. Queue status

- [x] K45 (JS-side lazy require, mobile) — shipped.
- [x] **K45b** (nuclear HERE removal, this phase) — shipped.
- [ ] **K45c** — Mapbox eager-require fix + download-token audit.
  **Not started.** Awaiting your dispatch.

---

### One line for the user

The Android crash almost certainly is NOT HERE — it is `@rnmapbox/maps`
with the same eager-require + missing-native-token pattern. K45b
closed the last HERE ceremonial reference; K45c is the actual fix
for the observed regression. Please dispatch K45c.
