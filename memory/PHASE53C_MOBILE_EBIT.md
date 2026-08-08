# Phase 53c — Mobile EBIT parity + demo-manager seed drift repair

**Date:** Feb 2026  
**Scope:** Mobile parity for the Phase 53b editable EBIT panel + a small backend seed-drift repair for the demo manager role. Web (53b) code is not modified beyond zero.

---

## 0 · Seed-drift fix (done first)

**Symptom (surfaced during Phase 53b E2E):** `manager@aquaterra.com` was resolving to `role=admin`, so the manager read-only branch could not be exercised end-to-end.

**Root cause:** The Phase 5A `seed_manager_user()` helper only inserts if the email is absent — never re-syncs the role. An unrelated migration had promoted the row to admin, and no subsequent seed pass could heal it.

**Fix:** New `seed_demo_manager()` in `backend/seed.py` — idempotent, no `SEED_DEMO_USERS` gate, enforces the invariant:

```
manager@aquaterra.com  ⇒  role == "manager"
                          active == True
                          tenant == aquaterra
```

Wired into the startup chain right after `seed_manager_user`. Runs on every boot; no-op when the row is already correct. Log line on first repair: `[phase53c] demo-manager role-drift repair applied: {'role': 'manager'}`.

**Verified via `/api/auth/me`:**

```
$ curl /api/auth/me → email=manager@aquaterra.com, role=manager, active=True
```

**Regression pytest** at `backend/tests/test_phase53c_seed_manager.py` locks the invariant. Passes.

**Credentials note** at `/app/memory/test_credentials.md` updated to reflect live behavior (manager row corrected; the prior `admin` alias-line on `manager@aquaterra.com` was misleading).

---

## 1 · Mobile parity screen

**Found at:** `/app/mobile/app/profit-report.tsx` (route `/profit-report`).

- Already imports `ADMIN_ROLES = ["admin", "super_admin", "manager"]` at the top, so the parent-level role gate matches spec: tech + customer cannot navigate to the screen; manager can.
- Extended in-place (no duplicate page created): one import line added, one `<EbitPanel />` mount just before the final `</ScrollView>`.

## 2 · Files touched

| File | Kind | Notes |
|---|---|---|
| `backend/seed.py` | modified | Added `seed_demo_manager()` — idempotent role-drift repair. |
| `backend/server.py` | modified | Wired new step after `seed_manager_user`. |
| `backend/tests/test_phase53c_seed_manager.py` | **added** | 1 regression test — `/api/auth/me` returns `role=manager`. |
| `memory/test_credentials.md` | modified | Corrected the manager row + added 53c drift-fix note. |
| `mobile/src/components/admin/EbitPanel.tsx` | **added** | Full editable EBIT panel (parity with 53b web). |
| `mobile/app/profit-report.tsx` | modified | +1 import, +1 mount line (nothing else touched). |
| `mobile/__tests__/phase53c-mobile-ebit-panel.test.tsx` | **added** | 13 jest tests — role gate ×5, adjustment ×1, override ×1, range/basis ×2, save ×1, versions ×1, CSV export ×1, PDF export ×1. |
| `mobile/__tests__/phase51d-walkie-parity.test.ts` | modified | +5 new EBIT parity assertions (mount check, row testids, panel testids, endpoints, role gate); walkie parity assertions untouched. |

## 3 · Mobile PDF lib finding

**Reused existing.** No new mobile PDF dependency added.

- `expo-print` — **already installed** (used by `src/utils/exportEstimatePdf.ts`, `src/utils/exportInvoicePdf.ts`). Used for the EBIT PDF export via `Print.printToFileAsync({ html })`.
- `expo-sharing` — **already installed**. Used for both CSV and PDF via `SharingModule.shareAsync(uri, { mimeType })`.
- `expo-file-system/legacy` — used for the CSV blob write to the cache dir, matching the existing pattern in `PortalChatAttachments.tsx`.

`@react-native-community/datetimepicker` is also present, but the current phase uses a lightweight `TextInput` "YYYY-MM-DD" custom-range picker rather than the native modal (matches the compact web UX and keeps the panel embeddable inside `ProfitReportPage`'s ScrollView without keyboard-avoiding contortions). The native picker can be swapped in as a later polish pass without behavioral change.

## 4 · Endpoints consumed

Identical to Phase 53b — the mobile client is a straight parity consumer:

- `GET /api/ebit/compute?range&from&to&revenue_basis`
- `GET /api/ebit/snapshots?range_from&range_to`
- `POST /api/ebit/snapshots`

`PATCH /adjustments` + `PATCH /overrides` remain fully tested backend surfaces but the mobile client (like web) POSTs a fresh version on every save (semantically equivalent under the immutable-versions contract 6B).

## 5 · Screenshots

**Live Expo web preview is blocked by a pre-existing bundling error** unrelated to Phase 53c:

```
node_modules/lottie-react-native/lib/module/LottieView/index.web.js
  → import "@dotlottie/react-player"   ← module not found
```

Chain: `app/ai-employees.tsx` → `AIAvatar.tsx` → `lottie-react-native` → `@dotlottie/react-player` (missing). This is baseline breakage on the Expo web bundler in this env; verified by removing all Phase 53c files and re-running Metro — same error. My files never import lottie.

**Visual-behavior verification is provided instead by the jest suite**, which mounts the actual React Native tree via `@testing-library/react-native` and drives every user flow:

| State | Verified by |
|---|---|
| **Adjustment mode active** (all 4 rows show `Adjustment: [delta] [Override]`) | `test 'entering a delta updates effective + EBIT total'` — asserts `ebit-row-*-adjustment-mode` rendered, effective + total update from 1500→1550, EBIT 100→150. |
| **Override mode active** (Depreciation flipped, `Override: 999 [Clear]`) | `test 'flipping to override replaces computed; clearing reverts'` — asserts `ebit-row-depreciation-override-mode` rendered, EBIT 100 → -699, then reverts on Clear. |
| **Version history bottom-sheet open** | `test 'History opens modal; loading a version puts editor read-only + fork restores'` — asserts `ebit-versions-modal` visible, `ebit-versions-row-s1` + `ebit-versions-row-s0` rendered, loading places `ebit-panel-loaded-version` at `v2` + `ebit-fork-btn` visible. |
| **CSV export share sheet** | `test 'writes a CSV string then invokes SharingModule.shareAsync'` — asserts `writeAsStringAsync` called with `.csv` extension + `mimeType: text/csv`, then `shareAsync(path, { mimeType: 'text/csv' })`. |
| **PDF export share sheet** | `test 'uses expo-print then shares the produced file'` — asserts `printToFileAsync({ html })` called with HTML containing `EBIT`, then `shareAsync(uri, { mimeType: 'application/pdf' })`. |

## 6 · Test count delta

| Suite | Before | After | Δ |
|---|---:|---:|---:|
| Mobile jest total | 206 | **224** | **+18** |
| — new `phase53c-mobile-ebit-panel.test.tsx` | 0 | 13 | +13 |
| — extended `phase51d-walkie-parity.test.ts` | 17 | 22 | +5 |
| Frontend vitest | 1371 | 1371 | 0 (untouched) |
| Backend Phase 53a pytest | 21 | 21 | 0 |
| — new `test_phase53c_seed_manager.py` | 0 | 1 | +1 |

## 7 · Suite verification (all green)

| Check | Result |
|---|---|
| `yarn lint` (frontend) | **exit 0** ✅ |
| `yarn test:unit` (frontend vitest) | **156 files · 1371 / 1371 green** ✅ |
| `yarn test` (mobile jest) | **29 suites · 224 / 224 green** ✅ |
| Backend Phase 53a + 53c pytest | **22 / 22 green** ✅ |
| `yarn lint` (mobile) | Baseline unchanged. Pre-existing 232 problems (67 err + 165 warn) verified as baseline by removing 53c files and re-running — same count. **Zero-delta introduced by Phase 53c.** |
| Backend Phase 41.4 curated coverage gate | Untouched by 53c (only additive surface). |
| `jest.setTimeout(15000)` from 53b triage | Preserved (both files still contain the setup). |

## 8 · Guardrails verified

- ✅ No duplicate mobile parity page — extended `mobile/app/profit-report.tsx`.
- ✅ No touch to Phase 53b web EBIT code (`EbitPanel.jsx`, `ProfitReportPage.jsx`).
- ✅ No touch to the three hotfix code paths.
- ✅ No touch to Phase 49/50/50.1/50.2/41.1b/41.1c/41.1d/41.2/41.3/41.4/41.5/42.4/43/46/47c-48b/51a-d/51.5/51.6/53a/53b runtime code.
- ✅ No touch to Stripe / Mapbox / Time-Off / RingCentral runtime.
- ✅ No new mobile PDF library — reused `expo-print` + `expo-sharing`.

## 9 · Deviations

Two minor items worth logging (neither changes the spec):

1. **Custom-range date picker uses lightweight `TextInput` (YYYY-MM-DD)** rather than the native `@react-native-community/datetimepicker` modal. Rationale: keeps the panel embeddable inside `ProfitReportPage`'s ScrollView without keyboard-avoiding contortions, matches the compact web UX. The native picker library is present and can be dropped in as a later polish pass without behavioral change.
2. **Mobile screenshots not captured live** because Expo web has a pre-existing bundler error (`@dotlottie/react-player` missing via `lottie-react-native`). Not caused by 53c; verified by removing all 53c files — same error persists. Behavioral verification is fully covered by the 13-test jest suite that mounts the actual RN tree and drives every user flow, plus the 5 parity assertions that lock testid + endpoint + gate consistency to the web build.

---

## Handoff to Phase 53d

Phase 53d is the ideal moment to:

- Swap the mobile custom-range `TextInput` for the native `@react-native-community/datetimepicker` modal (single-file change; behavior identical).
- Fix the pre-existing lottie bundler error (`@dotlottie/react-player` missing) so live web previews of mobile screens work again.
- Wire the two backend PATCH endpoints (`/adjustments`, `/overrides`) into a "quick edit" UX for existing snapshots on both surfaces if the immutable-POST-every-time model produces too many versions in real usage.
