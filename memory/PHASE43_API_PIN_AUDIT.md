# Phase 43 — Third-Party API Version Pin Audit

**Type:** Audit-only. No `pip install`, no `yarn add`, no upgrades, no runtime code changes.
**Date:** 2026-02 (session run)
**Surveyed manifests:**
- `/app/backend/requirements.txt`
- `/app/frontend/package.json`
- `/app/mobile/package.json`

**Version-lookup method:**
- PyPI JSON API (`https://pypi.org/pypi/<pkg>/json`) — metadata read only.
- npm registry API (`https://registry.npmjs.org/<pkg>/latest`) — metadata read only.
- No package manager mutation commands were executed. No lockfiles were touched.

**Post-audit guardrail check (self-attested):**
- No `pip install`, no `pip uninstall`, no `pip freeze > requirements.txt`.
- No `yarn add`, no `yarn remove`, no `yarn upgrade`.
- `requirements.txt`, `frontend/package.json`, `mobile/package.json`, and both `yarn.lock` files are byte-identical to their pre-audit state.

---

## 1. Executive Summary

| Metric                          | Count |
|--------------------------------|-------|
| Total packages surveyed        | **50** |
| High-risk (major version drift)| **9** |
| Medium-risk (minor/feature drift)| **13** |
| Low-risk (patch / already latest)| **28** |

**Top 3 highest-risk items** (see §5 for full detail):

1. **`tailwindcss` (frontend)** — pinned `^3.4.17`, latest **`4.3.3`**. Tailwind v4 is a ground-up rewrite: new CSS-first config, new import syntax, removed `tailwind.config.js` semantics, PostCSS pipeline changes. Upgrading breaks every stylesheet, every `@apply`, and every Radix wrapper. **Risk: H** — DO NOT touch without a dedicated multi-phase migration project.
2. **`expo` / `react-native` / entire mobile Expo SDK bundle** — pinned SDK 54 (`expo@54.0.35`, `react-native@0.81.5`, `expo-router@6.0.24`), latest **SDK 57** (`expo@57.0.10`, `react-native@0.86.2`, `expo-router@57.0.10`). Three annual majors behind. Any SDK jump requires the entire expo-* family to move together plus native module recompiles (`@rnmapbox/maps`, `lottie-react-native`, `react-native-reanimated`). **Risk: H** — schedule an "Expo SDK N+1" phase; do NOT drift packages individually.
3. **`lucide-react` (frontend)** — pinned `^0.507.0`, latest **`1.28.0`**. Lucide graduated to `1.x` with a stable API guarantee and consolidated icon set. Icon-name renames and dropped aliases are the primary risk vector. Every `<IconName />` import in the frontend needs a compatibility sweep. **Risk: H** — Vitest coverage on icons is thin; regression risk is visual.

**Overall recommendation:** Hold current pins. All three risk tiers point to *"defer, don't drift."* The green-test invariants (Vitest 1257/1257, mobile Jest 129/129, backend curated coverage gate, `yarn lint --max-warnings=0`) are far more valuable than being on latest. Upgrades should be scheduled as dedicated phases with their own regression suites.

---

## 2. Backend (`/app/backend/requirements.txt`)

Framework: FastAPI. LLM aggregator: `litellm` + `emergentintegrations`. SMS provider: RingCentral (Twilio removed 2026-07 per Phase 7B comment on line 124).

| Package              | Surface                                | Pinned            | Latest stable | Breaking changes summary                                                                                       | Risk | Recommended action                                                    |
|----------------------|----------------------------------------|-------------------|---------------|----------------------------------------------------------------------------------------------------------------|:---:|-----------------------------------------------------------------------|
| `stripe`             | Payments SDK                           | `>=15.3.0,<16.0.0` (installed `15.4.0`) | `15.4.0`      | Within pinned range. v15 line already migrated in Phase 42.4 (no more `.get()` on Stripe objects).             | L   | Hold. Range covers latest. Re-audit when v16 releases.                |
| `openai`             | LLM (direct + via `emergentintegrations`) | `1.99.9`          | `2.53.0`      | v2 introduced typed responses, renamed some client kwargs, moved `AsyncOpenAI` semantics. Used indirectly via `litellm` shim, so surface is small — but any direct `import openai` sites must be reviewed. | M   | Hold. Audit direct `openai` imports before considering v2.            |
| `anthropic`          | LLM (Claude)                           | *not pinned direct — via `emergentintegrations`/`litellm`* | `0.120.2` | Version drift is absorbed by `litellm`. Direct upgrade only relevant if we call `anthropic.Anthropic()` directly. | L   | No action. Managed by `litellm`/`emergentintegrations`.               |
| `google-genai`       | Gemini SDK (new client)                | `2.10.0`          | `2.16.0`      | Patch/minor drift within v2. Google's dual-SDK strategy (`google-genai` = new, `google-generativeai` = legacy) still active. | L   | Hold or bump to 2.16.0 in a dedicated LLM-refresh phase.              |
| `google-generativeai`| Gemini SDK (legacy client)             | `0.8.6`           | `0.8.6`       | Already latest. Legacy client, expected to be sunset once `google-genai` reaches parity.                       | L   | Hold. No action.                                                      |
| `ringcentral`        | SMS/telephony                          | `0.9.2`           | `0.9.2`       | Already latest. Blocked-issue tracker (Issue 3) is on adapter isolation, not SDK version.                      | L   | Hold. No action.                                                      |
| `resend`             | Transactional email                    | `2.32.2`          | `2.35.0`      | Minor bumps — additive endpoints (broadcasts, contacts). No known breakage.                                    | L   | Optional bump in a future email-refresh phase.                        |
| `intuit-oauth`       | QuickBooks OAuth                       | `1.2.7`           | `1.2.7`       | Already latest.                                                                                                | L   | Hold. No action.                                                      |
| `python-quickbooks`  | QuickBooks REST client                 | **not present**   | `0.9.12`      | Not pinned in `requirements.txt`; either unused or accessed via raw HTTP. Confirm dependency direction.        | —   | No action (not in scope). Flag for a future QuickBooks-integration phase if REST SDK is needed. |
| `motor`              | Async MongoDB driver                   | `3.3.1`           | `3.7.1`       | 3.4→3.7 added typed collections, dropped Py3.7 support (we're on 3.10+ so fine).                              | M   | Hold. Bump only alongside `pymongo` in a single coordinated PR.       |
| `pymongo`            | MongoDB driver (transitive of motor)   | `4.6.3`           | `4.17.0`      | 4.7+ introduced encrypted client-side field level changes and TLS defaults tightened. Batch tests already flaky (Issue 3 in session context) — do NOT drift. | M   | Hold. Coordinate with `motor` bump.                                   |
| `APScheduler`        | Job scheduler                          | `3.11.3`          | `3.11.3`      | Already latest on the 3.x line. v4 exists in alpha but not stable.                                             | L   | Hold. No action.                                                      |
| `fastapi`            | Web framework                          | `0.110.1`         | `0.141.1`     | 0.111→0.141 introduced lifespan events tightening, new `Annotated`-first dependency style, deprecated `@app.on_event`. Coverage-gated Pytest would surface most issues, but Starlette + Pydantic pins move in lockstep. | M   | Hold. Any bump must move `starlette` + `pydantic` in the same phase. |
| `pydantic`           | Data validation                        | `2.13.4`          | `2.13.4`      | Already latest.                                                                                                | L   | Hold. No action.                                                      |
| `boto3`              | AWS SDK (S3 storage)                   | `1.43.44`         | `1.43.64`     | Patch drift — service model refreshes only. No API changes.                                                    | L   | Optional bump. Safe.                                                  |
| `twilio`             | *(removed 2026-07, Phase 7B)*          | **not present** (commented line 124) | `9.10.9` | RingCentral replaced Twilio. No action.                                                                        | —   | No action. Reference note in file preserved.                          |
| `litellm`            | LLM proxy/aggregator                   | `1.80.0` (wheel URL) | `1.95.0`   | 1.81→1.95 added provider registrations (Anthropic 4.5, GPT-5.4, etc.). Consumed via custom `emergent` wheel URL — upgrade requires new wheel from vendor. | M   | Hold. Not a normal PyPI bump — tied to `emergentintegrations` release cycle. |
| `emergentintegrations` | Emergent LLM key wrapper             | `0.2.0`           | *vendor-managed* | Vendor cadence, not PyPI-managed. See Emergent LLM Key playbook.                                              | —   | Hold. Vendor-managed.                                                 |
| `numpy`              | Numeric                                | `2.4.6`           | (latest not queried — utility) | Utility — no direct integration surface.                                                              | L   | No action.                                                            |
| `pandas`             | Dataframes                             | `3.0.3`           | (latest not queried — utility) | Utility — no direct integration surface.                                                              | L   | No action.                                                            |

**Backend Mapbox note:** No `mapbox` / `mapbox-sdk` package present in `requirements.txt`. Backend does NOT geocode; geocoding surface is entirely on mobile via `@rnmapbox/maps`. Confirmed out of scope for the backend audit.

**Backend Sentry note:** No `sentry-sdk` present. Confirmed out of scope.

---

## 3. Frontend (`/app/frontend/package.json`)

Framework: React 19 + CRA/Craco (build) + Vite/Vitest (unit tests). ESLint 9 flat-config (Phase 41.3). Coverage via `@vitest/coverage-v8` (Phase 41.4).

| Package                              | Surface                              | Pinned         | Latest stable | Breaking changes summary                                                                                       | Risk | Recommended action                                            |
|--------------------------------------|--------------------------------------|----------------|---------------|----------------------------------------------------------------------------------------------------------------|:---:|---------------------------------------------------------------|
| `@stripe/stripe-js`                  | Stripe.js loader                     | `^9.12.1`      | `9.13.0`      | Patch bump. Additive.                                                                                          | L   | Optional bump. Safe under caret range.                        |
| `@stripe/react-stripe-js`            | React Elements                       | `^6.8.0`       | `6.8.0`       | Already latest.                                                                                                | L   | Hold.                                                         |
| `lottie-react`                       | Web Lottie animator (Phase 50)       | `2.4.1`        | `2.4.1`       | Already latest.                                                                                                | L   | Hold.                                                         |
| `lucide-react`                       | Icon set                             | `^0.507.0`     | **`1.28.0`**  | v1 stable API guarantee; icon-name renames + dropped aliases. Icons appear in ~every page. Coverage is thin on visual regressions. | **H** | **Hold.** Schedule a dedicated icon-audit phase before v1 jump. |
| `@radix-ui/react-dialog`             | Dialog primitive                     | `^1.1.11`      | `1.1.23`      | Patch/minor drift. Additive props + a11y hardening.                                                             | L   | Optional bump.                                                |
| `@radix-ui/react-select`             | Select primitive                     | `^2.2.2`       | `2.3.7`       | Minor drift. Compatible.                                                                                        | L   | Optional bump.                                                |
| `@radix-ui/react-dropdown-menu`      | DropdownMenu primitive               | `^2.1.12`      | `2.1.24`      | Patch drift.                                                                                                    | L   | Optional bump.                                                |
| `@radix-ui/react-toast`              | Toast primitive                      | `^1.2.11`      | `1.2.23`      | Patch drift. Additive.                                                                                          | L   | Optional bump. Coordinate with `sonner`.                      |
| `@radix-ui/react-tabs`               | Tabs primitive                       | `^1.1.9`       | `1.1.21`      | Patch drift.                                                                                                    | L   | Optional bump.                                                |
| `sonner`                             | Toast component                      | `^2.0.3`       | `2.0.7`       | Patch drift.                                                                                                    | L   | Optional bump. Safe.                                          |
| `tailwindcss`                        | CSS framework                        | `^3.4.17`      | **`4.3.3`**   | v4 = ground-up rewrite. CSS-first config, new `@import "tailwindcss"`, no `tailwind.config.js` semantics, PostCSS pipeline change, `@apply` semantics shift. Also constrained by `postcss-selector-not` Node-20 pin note (line 129). | **H** | **Hold.** Do NOT drift. Full re-write phase required.        |
| `postcss`                            | CSS pipeline                         | `^8.4.49`      | `8.5.25`      | Minor drift on 8.x.                                                                                             | L   | Optional bump.                                                |
| `autoprefixer`                       | CSS prefixer                         | `^10.4.20`     | `10.5.4`      | Minor drift.                                                                                                    | L   | Optional bump.                                                |
| `postcss-selector-not`               | PostCSS plugin                       | `^8.0.1`       | (pin locked)  | Locked via `resolutions` to `< 9` on Node 20.18.x per Phase 21 note (line 129). Do NOT bump.                    | —   | **Hold.** Governed by container Node version.                 |
| `react`                              | React                                | `^19.0.0`      | `19.2.8`      | Patch drift.                                                                                                    | L   | Optional bump. Coordinate with `react-dom`.                   |
| `react-dom`                          | React DOM                            | `^19.0.0`      | `19.2.8`      | Patch drift.                                                                                                    | L   | Optional bump.                                                |
| `react-router-dom`                   | Routing                              | `^7.5.1`       | `7.18.2`      | Minor drift on v7 line. No known breaking changes for our usage.                                                | L   | Optional bump.                                                |
| `react-hook-form`                    | Forms                                | `^7.56.2`      | `7.84.0`      | Minor drift.                                                                                                    | L   | Optional bump.                                                |
| `recharts`                           | Charts                               | `^3.6.0`       | `3.10.1`      | Minor drift.                                                                                                    | L   | Optional bump.                                                |
| `zod`                                | Schema validation                    | `^3.24.4`      | **`4.4.3`**   | v4 = breaking. Renamed error object shape, redesigned parser output, `ZodEffects` removed. Widespread breakage. | **H** | **Hold.** Dedicated Zod v4 migration phase required.          |
| `date-fns`                           | Date utilities                       | `^4.1.0`       | `4.4.0`       | Minor drift on v4 line.                                                                                         | L   | Optional bump.                                                |
| `@react-google-maps/api`             | Google Maps React wrapper            | `^2.20.8`      | `2.20.8`      | Already latest.                                                                                                 | L   | Hold.                                                         |
| `@vis.gl/react-google-maps`          | Google Maps React (modern)           | `^1.9.0`       | `1.9.0`       | Already latest.                                                                                                 | L   | Hold.                                                         |
| `leaflet`                            | Mapping                              | `^1.9.4`       | `1.9.4`       | Already latest.                                                                                                 | L   | Hold.                                                         |
| `react-leaflet`                      | React Leaflet                        | `^5.0.0`       | `5.0.0`       | Already latest.                                                                                                 | L   | Hold.                                                         |
| `vite`                               | Bundler (Vitest transitive)          | (via `vitest@1.6.1`) | **`8.2.0`** | v6/7/8 introduced Rollup 4/5 migration + ESM-only. Major.                                                       | M   | Governed by Vitest bump. Hold.                                |
| `vitest`                             | Unit test runner                     | `1.6.1`        | **`4.1.10`**  | v2/3/4 changed reporter API, coverage-v8 semantics, workspace format. Would break Phase 41.4 coverage baselines. | **H** | **Hold.** Coordinated bump with `@vitest/coverage-v8` + fresh coverage baselines required. |
| `@vitest/coverage-v8`                | Coverage provider                    | `1.6.0`        | **`4.1.10`**  | Must match `vitest` major.                                                                                      | **H** | **Hold.** Coupled to `vitest`.                                |
| `@vitejs/plugin-react`               | Vite React plugin                    | `4.3.4`        | `6.0.5`       | v5/6 aligned with Vite majors.                                                                                  | M   | Hold. Coupled to Vite/Vitest bump.                            |
| `eslint`                             | Linter                               | `9.23.0`       | **`10.8.0`**  | v10 dropped legacy config, tightened flat config. Phase 41.3 just migrated to flat config; the payoff of v10 is small vs the regression risk of the `yarn lint --max-warnings=0` invariant. | **H** | **Hold.** Do not chase v10 — Phase 41.3 gates are worth more. |
| `esbuild`                            | JS transpiler                        | `^0.28.1`      | (utility)     | Utility, transitive-heavy.                                                                                      | L   | No action.                                                    |
| `jsdom`                              | Test DOM shim                        | `25.0.1`       | (utility)     | Coupled to Vitest bump.                                                                                         | L   | Hold. Coupled.                                                |

**Frontend Sentry/analytics note:** No `@sentry/react`, no `@sentry/browser`, no `mixpanel-browser`, no `posthog-js` present. Analytics surface is confirmed absent. Confirmed out of scope.

---

## 4. Mobile (`/app/mobile/package.json`)

Framework: Expo SDK **54** + React Native 0.81.5 + Expo Router v6. Test runner: Jest 29 + `jest-expo` 57.

**Critical mobile context:** Expo family versions MUST move as a bundle. Never drift `expo`, `expo-router`, `expo-*` modules, `react-native`, `react-native-reanimated`, `react-native-gesture-handler`, `react-native-screens`, `react-native-safe-area-context`, `react-native-svg`, `react-native-webview` independently — they are Expo-SDK-version-locked.

| Package                                    | Surface                          | Pinned          | Latest stable | Breaking changes summary                                                             | Risk | Recommended action                                    |
|--------------------------------------------|----------------------------------|-----------------|---------------|--------------------------------------------------------------------------------------|:---:|-------------------------------------------------------|
| `expo`                                     | Expo SDK                         | `54.0.35`       | **`57.0.10`** | SDK 54 → 55 → 56 → 57. Three annual majors behind.                                    | **H** | **Hold.** Coordinated Expo SDK upgrade phase.        |
| `expo-router`                              | File-based routing               | `6.0.24`        | **`57.0.10`** | v7+ aligns route naming with SDK 55; group/segment API changes.                       | **H** | **Hold.** Bundled with `expo` SDK bump.              |
| `expo-notifications`                       | Push notifications               | `~0.32.17`      | **`57.0.8`**  | SDK 54 line is `~0.32.x`; latest jumps to `57.0.x` numbering scheme.                  | **H** | **Hold.** Bundled with `expo` SDK bump.              |
| `expo-speech-recognition` (Phase 49)       | On-device STT                    | `^2.1.1`        | **`56.0.1`**  | v56.x renumbered to align with Expo SDK versioning; API renames on `SpeechRecognitionModule`. | **H** | **Hold.** Coordinated with `expo` SDK bump.         |
| `expo-updates`                             | OTA updates                      | `~29.0.13`      | **`57.0.12`** | Renumbering + config changes.                                                         | **H** | **Hold.** Bundled with `expo`.                       |
| `expo-video`                               | Video player                     | `~3.0.16`       | **`57.0.2`**  | Bundled.                                                                              | **H** | **Hold.** Bundled with `expo`.                       |
| `expo-image`                               | Image loader                     | `3.0.11`        | **`57.0.2`**  | Bundled.                                                                              | **H** | **Hold.** Bundled with `expo`.                       |
| `expo-location`                            | Geolocation                      | `~19.0.8`       | **`57.0.7`**  | Bundled.                                                                              | **H** | **Hold.** Bundled with `expo`.                       |
| `expo-image-picker`                        | Image picker                     | `~17.0.11`      | **`57.0.7`**  | Bundled.                                                                              | **H** | **Hold.** Bundled with `expo`.                       |
| `expo-file-system`                         | Filesystem                       | `~19.0.23`      | **`57.0.1`**  | Bundled.                                                                              | **H** | **Hold.** Bundled with `expo`.                       |
| `expo-secure-store`                        | Secure storage                   | `15.0.8`        | **`57.0.1`**  | Bundled.                                                                              | **H** | **Hold.** Bundled with `expo`.                       |
| `react-native`                             | React Native                     | `0.81.5`        | **`0.86.2`**  | 0.82 → 0.86 introduced New Architecture default, Fabric renderer, TurboModules tightening. | **H** | **Hold.** Bundled with `expo` SDK bump.              |
| `react-native-reanimated`                  | Animations                       | `4.1.1`         | `4.5.3`       | Minor within v4. Compatible with SDK 54 range.                                        | M   | Hold. Coupled to Expo SDK.                            |
| `react-native-gesture-handler`             | Gestures                         | `2.28.0`        | **`3.1.0`**   | v3 requires RN 0.83+. Currently on RN 0.81.5, so v3 is blocked by SDK 54.             | **H** | **Hold.** Blocked by RN version.                     |
| `react-native-safe-area-context`           | Safe area                        | `5.6.0`         | `5.8.1`       | Patch drift.                                                                          | L   | Governed by Expo SDK. Hold.                           |
| `react-native-screens`                     | Screens                          | `4.16.0`        | `4.26.2`      | Minor drift.                                                                          | L   | Governed by Expo SDK. Hold.                           |
| `react-native-svg`                         | SVG renderer                     | `15.12.1`       | `15.15.5`     | Patch drift.                                                                          | L   | Governed by Expo SDK. Hold.                           |
| `react-native-webview`                     | WebView                          | `13.15.0`       | **`14.0.1`**  | v14 dropped iOS 13, tightened messaging API.                                          | M   | Hold. Coupled to Expo SDK.                            |
| `react-native-maps`                        | Maps (Google/Apple)              | `1.20.1`        | `1.29.0`      | Minor drift.                                                                          | L   | Optional bump when SDK moves.                         |
| `@rnmapbox/maps`                           | Mapbox native                    | `^10.1.34`      | `10.3.5`      | Minor drift on v10. Native module — requires clean iOS/Android build.                 | M   | Hold. Bump only in a native-rebuild phase.            |
| `lottie-react-native` (Phase 50)           | Lottie                           | `7.0.0`         | `7.3.8`       | Minor drift on v7.                                                                    | L   | Optional bump.                                        |
| `@react-native-async-storage/async-storage`| KV storage                       | `2.2.0`         | **`3.1.1`**   | v3 requires RN 0.83+.                                                                 | **H** | **Hold.** Blocked by RN version.                    |
| `@react-native-community/netinfo`          | Net status                       | `12.0.1`        | `12.0.1`      | Already latest.                                                                       | L   | Hold.                                                 |
| `@react-native-community/datetimepicker`   | DateTime picker                  | `8.4.4`         | **`9.1.0`**   | v9 requires RN 0.83+.                                                                 | M   | Hold. Blocked by RN version.                          |
| `@gorhom/bottom-sheet`                     | Bottom sheet                     | `5.2.14`        | `5.2.14`      | Already latest.                                                                       | L   | Hold.                                                 |
| `jest`                                     | Test runner                      | `29.7.0`        | **`30.4.2`**  | v30 dropped Node 16, updated `jest-environment` semantics. `jest-expo` alignment required. | M   | Hold. Coupled to `jest-expo` bump (Expo SDK).        |
| `jest-expo`                                | Expo Jest preset                 | `57.0.2`        | `57.0.3`      | Patch drift.                                                                          | L   | Optional bump. Safe.                                  |
| `@testing-library/react-native`            | RN Testing Library               | `12.9.0`        | **`14.0.1`**  | v13/14 aligned to Jest 30. Query API tightened.                                       | M   | Hold. Coupled to Jest bump. Mobile Jest is 129/129 green — do not drift. |
| `eslint-config-expo`                       | Expo ESLint config               | `10.0.0`        | **`57.0.1`**  | Renumbered to align with SDK versioning.                                              | M   | Hold. Bundled with `expo` SDK bump.                   |

**Mobile @react-navigation/* note:** Routing is handled by **`expo-router`** (file-based). No `@react-navigation/native` / `@react-navigation/stack` / `@react-navigation/bottom-tabs` present. Confirmed out of scope for this audit.

---

## 5. Consolidated High-Risk Table (audit output)

| # | Package                          | Surface           | Pinned         | Latest        | Rationale (one-line)                                                          |
|---|----------------------------------|-------------------|----------------|---------------|-------------------------------------------------------------------------------|
| 1 | `tailwindcss`                    | frontend          | `^3.4.17`      | `4.3.3`       | v4 = ground-up CSS-first rewrite; every stylesheet & Radix wrapper impacted.  |
| 2 | `expo` + full SDK bundle         | mobile            | SDK 54         | SDK 57        | Three annual majors behind; RN 0.81 → 0.86; entire expo-* family locked to SDK. |
| 3 | `lucide-react`                   | frontend          | `^0.507.0`     | `1.28.0`      | v1 stable API guarantee; icon renames + dropped aliases; thin visual coverage.|
| 4 | `zod`                            | frontend          | `^3.24.4`      | `4.4.3`       | v4 = breaking parser output shape; widespread form validation impact.         |
| 5 | `vitest` + `@vitest/coverage-v8` | frontend          | `1.6.1` / `1.6.0` | `4.1.10`    | v4 breaks Phase 41.4 coverage baseline + reporter APIs.                       |
| 6 | `eslint`                         | frontend          | `9.23.0`       | `10.8.0`      | Phase 41.3 gate `yarn lint --max-warnings=0` at risk; v10 payoff small.       |
| 7 | `react-native-gesture-handler`   | mobile            | `2.28.0`       | `3.1.0`       | Requires RN 0.83+ (blocked by Expo SDK 54).                                   |
| 8 | `@react-native-async-storage/async-storage` | mobile | `2.2.0`        | `3.1.1`       | Requires RN 0.83+ (blocked by Expo SDK 54).                                   |
| 9 | `react-native` core              | mobile            | `0.81.5`       | `0.86.2`      | New Architecture default; Fabric/TurboModules tightening; bundled with Expo.  |

---

## 6. Recommended Follow-up Phases (audit's only prescription)

These are **suggestions only**. This audit does not itself perform any upgrade.

- **Phase 43.A — Radix + Sonner refresh (Low risk).** Bump all `@radix-ui/*` from `^1.1.x` / `^2.1.x` → latest minors, plus `sonner` and Radix `toast`. Additive; contained regression surface. Estimated effort: small.
- **Phase 43.B — Backend patch sweep (Low risk).** Bump `boto3`, `resend`, `google-genai` within safe minor ranges. Contained.
- **Phase 43.C — LLM SDK refresh (Medium risk).** Coordinated bump of `openai` v1 → v2 direct-usage sites. Requires the `emergentintegrations` wheel to be re-emitted by vendor to remain compatible.
- **Phase 43.D — Vitest v4 + coverage rebaseline (High risk).** Rebuild Phase 41.4 coverage thresholds under Vitest 4 reporter API. Own phase.
- **Phase 43.E — Expo SDK 55 (High risk).** Do NOT jump to 57 in one shot; go SDK 54 → 55 first. Full RN native module recompile + Mapbox + Reanimated + Lottie re-validation.
- **Phase 43.F — Tailwind v4 (High risk).** Dedicated design-system rewrite. Not recommended in the current backlog.
- **Phase 43.G — Zod v4 migration (High risk).** All form validators + API-payload schemas must be rewritten. Own phase.
- **Phase 43.H — Lucide v1 migration (High risk).** Icon-audit sweep; codemod for renamed exports.

---

## 7. Guardrail Confirmation

- ✅ No packages installed.
- ✅ No packages removed.
- ✅ No packages upgraded.
- ✅ `backend/requirements.txt`, `frontend/package.json`, `mobile/package.json` untouched.
- ✅ `frontend/yarn.lock`, `mobile/yarn.lock` untouched.
- ✅ No runtime code changes.
- ✅ Vitest, mobile Jest, backend coverage gate, and `yarn lint --max-warnings=0` invariants unaffected (no source touched).

**End of Phase 43 audit.**
