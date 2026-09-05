# Phase K61 — Mobile Save-draft / Close-job Robustness

**Ship date:** Feb 2026
**Scope:** Three coupled client-side fixes on the mobile Job
Checklist screen (`mobile/app/job/[id]/checklist.tsx`) plus the
underlying `ApiError` structured-throw contract on
`mobile/src/api.ts`.  No backend changes, no dependency changes.
**Status:** 🟢 SHIPPED — K61.a.2 + K61.b.2 + K61.c together.

---

## Field report (context)

Users on the mobile Job Checklist screen reported that neither the
"Save draft" nor "Close job" buttons in the sticky bottom bar
worked.  Diagnosis (K61 7-point report) traced this to THREE
independent failures:

1. **Close-job never surfaced the real reason** — the catch block
   fished for axios-shaped `e.response.data.detail` fields on a
   fetch-based client where they don't exist.  Dead-code branch.
   Every close-job failure fell through to a generic `Alert.alert("Close failed", e?.message)`
   with no visual feedback on which required readings were missing.
2. **Save-draft always claimed success** — `flushSave()` swallowed
   every error in an unrecovered `catch`, so `saveDraft` unconditionally
   showed `Alert.alert("Saved", "Draft saved.")` even when the PATCH
   4xx'd.  Users lost changes silently.
3. **Chemistry-gate affordance never fired** — the pre-K61 code had
   `setHighlightBodies({…})` wiring in place for inline missing-field
   highlighting, but it lived inside the dead axios-shape probe.  So
   techs blocked by the chemistry gate saw a mislabelled "Close failed"
   alert with no visual pointer to which readings were missing.

## Slice K61.a.2 — Structured `ApiError` throw

**File:** `mobile/src/api.ts` (lines ~26-70 + ~140-160).

**New:** `ApiError extends Error` — carries `status: number`,
`detail: unknown` (raw parsed backend `detail`, preserved verbatim),
`kind: "http"`.

**Change:** `request()` now `throw new ApiError(msg, res.status, rawDetail)`
instead of `throw new Error(msg)`.  Humanised `msg` computation
unchanged so every existing catch site that only reads `err.message`
keeps working.

**Contract exposed to callers:**
```typescript
try { await api.post("/jobs/x/service-report/submit", {}); }
catch (e) {
  if (e instanceof ApiError && e.status === 422 &&
      typeof e.detail === "object" && e.detail !== null &&
      (e.detail as any).detail === "chemistry_core_readings_missing") {
    // structured branch — read (e.detail as any).missing_labels etc.
  }
}
```

## Slice K61.b.2 — Truthful `flushSave` return contract

**File:** `mobile/app/job/[id]/checklist.tsx` (lines ~226-315).

**New type:** `FlushSaveResult = { ok: boolean; queued?: boolean; error?: string }`.

**Changed:** `flushSave` return signature `async () => void` →
`async () => Promise<FlushSaveResult>`.  Emits:

| Return shape                        | Path |
|-------------------------------------|------|
| `{ ok: true }`                      | Early short-circuit (`!current` / `submitted_at` / `!dirty`) OR online happy-path PATCH. |
| `{ ok: true, queued: true }`        | Offline path — enqueued to `writeQueue` for reconnect flush. |
| `{ ok: false, error: <string> }`    | HTTP failure (`ApiError`), network error (`ApiNetworkError`), or unexpected exception. |

The pre-K61 catch block's `setSaveState("error"); return;` swallow is
replaced with `return { ok: false, error: String(e?.message || …) };`.
Autosave callers still ignore the return; explicit callers (`saveDraft`
+ `closeJob` pre-flush) now branch on `result.ok`.

## Slice K61.b.2 — `saveDraft` branches on the envelope

**File:** `mobile/app/job/[id]/checklist.tsx` (lines ~381-410).

```
ok && queued  →  Alert "Saved locally · will sync on reconnect"
ok            →  Alert "Saved · Draft saved."
!ok           →  Alert "Save failed · <error>"
```

The pre-K61 `await flushSave(); Alert.alert("Saved", …)` sequence is
gone (a regression assertion locks the pattern out — see
`k61-checklist-contract.test.ts`).

## Slice K61.b.2 — `closeJob` pre-flush short-circuit

**File:** `mobile/app/job/[id]/checklist.tsx` (lines ~446-462).

The Close-job onPress handler now captures the pre-flush's return:

```typescript
const flushed = await flushSave();
if (!flushed.ok) {
  Alert.alert(
    "Save failed",
    `${flushed.error || "Could not save your latest edits."}\n\nJob was not closed — please try again.`,
  );
  setSubmitting(false);
  return;
}
```

Rationale: if the pre-flush PATCH fails, the submit either 4xx's on
stale server state OR silently succeeds with pre-flush data.  Either
outcome is worse than bailing out with a truthful error.

## Slice K61.a.2 + K61.c — Structured chemistry-gate branch

**File:** `mobile/app/job/[id]/checklist.tsx` (lines ~500-560).

The catch block is rewritten around the `ApiError` structural check:

```typescript
} catch (e: any) {
  const isApiErr = e instanceof ApiError;
  const rawDetail: any = isApiErr ? e.detail : null;
  const isChemistryGate =
    isApiErr && e.status === 422 &&
    rawDetail && typeof rawDetail === "object" &&
    (rawDetail as any).detail === "chemistry_core_readings_missing";
  if (isChemistryGate) {
    // 1. Inline highlight — walk waterBodiesRef.current, run
    //    missingRequiredReadings() per pool body, and set
    //    highlightBodies[bodyIndex] = [readingKeys].  The
    //    ChemistryReadings render path (unchanged) reads this map
    //    to draw red-bordered inputs on the missing fields.
    // 2. Alert — expand any short-form label ("CYA" → "Cyanuric
    //    Acid") via the K60 helper and show a single "Missing
    //    required readings" alert listing them.
  } else if (isApiErr) {
    Alert.alert("Close failed", e.message || `Request failed (${e.status})`);
  } else {
    Alert.alert("Close failed", e?.message || "Try again.");
  }
}
```

**K61.c ties in the K60 chemistry-label expander**: the alert copy
runs `missingLabels.map(expandChemistryLabel)` so `"CYA"` becomes
`"Cyanuric Acid"`.  The backend already emits mostly-readable labels
(`"Free Cl"`, `"Total Cl"`) — expander is idempotent on those.

## Preserved behaviour

* Analytics / logging events (`logApi`) on both save + close paths
  unchanged.
* Offline paths preserved — `submitOffline`, `writeQueue.enqueue`,
  and `offlineWrite` orchestration intact.
* No auto-close — Close-job remains an explicit user action gated
  behind the confirmation `Alert.alert("Close job?", …)`.
* Existing `MIN_SAVING_MS` timing, `savingShownAtRef`, and
  `setSaveState` transitions unchanged.
* No new dependencies, no `package.json` changes.

## Files changed

| File                                                           | Lines touched (approx) | Purpose |
|----------------------------------------------------------------|------------------------|---------|
| `mobile/src/api.ts`                                            | +40 (new class), ~10 (throw site) | K61.a.2 — new `ApiError` class + throw site. |
| `mobile/app/job/[id]/checklist.tsx`                            | ~130 (flushSave + saveDraft + closeJob) | K61.b.2 + K61.c wiring. |
| `mobile/__tests__/k61-apiError.test.ts`                        | +145 (new)             | K61.a.2 unit + integration tests. |
| `mobile/__tests__/k61-checklist-contract.test.ts`              | +180 (new)             | K61.b.2 + K61.c contract-lock tests. |
| `memory/auth_testing.md`                                       | +90 (new)              | Auth testing notes for tester agent. |
| `memory/PHASE_K61_MOBILE_SAVE_CLOSE_ROBUSTNESS.md` (this file) | +200 (new)             | Ship report. |

## Test results (unit)

| Suite                                                       | Result | Notes |
|-------------------------------------------------------------|--------|-------|
| `__tests__/k61-apiError.test.ts`                            | **7/7 green** | `ApiError` class + `request()` throws (fetch-mocked, 4 cases). |
| `__tests__/k61-checklist-contract.test.ts`                  | **20/20 green** | flushSave envelope shapes, saveDraft branches, closeJob pre-flush short-circuit, chemistry-gate structural detection, regression guards for pre-K61 dead-code patterns. |
| K57 regression — `__tests__/k50-job-status-color.test.ts`   | **7/7 green** | No regression. |
| K58 regression — `__tests__/k58-jobCoords.test.ts`          | **13/13 green** | No regression. |
| K59.a regression — `__tests__/k59a-stringifyDetail.test.ts` | **15/15 green** | No regression. |
| K60 regression — `__tests__/k60-expandChemistryLabel.test.ts` | **39/39 green** | No regression. |

**TypeScript check**: 521 pre-existing errors across mobile codebase
(tsconfig strictness debt); **ZERO new errors** on lines touched by
K61 (`app/job/[id]/checklist.tsx` and `src/api.ts`).  Confirmed via
`npx tsc --noEmit -p tsconfig.json` — no error rows in the K61 edit
ranges.

## E2E flows to route to the tester agent (Expo preview)

Two candidate flows for tester-agent E2E on the Expo preview build
(NOT required to declare K61 shipped — unit tests cover the
contract, but valuable for confidence):

1. **Save-draft happy path + failure path** (K61.b.2):
   * Log in as `mike@aquaterra.com` (pool tech).
   * Open a scheduled pool job's Checklist.
   * Edit a chemistry reading.
   * Tap "Save draft" — assert `"Saved · Draft saved."` alert.
   * Force a network failure (airplane mode) — tap "Save draft" —
     assert `"Saved locally · will sync when your device reconnects."`
     alert.
   * Force a backend 4xx (e.g. mutate the request body via
     Reactotron) — assert `"Save failed · <reason>"` alert (no false
     success).

2. **Close-job chemistry gate** (K61.a.2 + K61.c):
   * Same setup.
   * Leave FC / TC / TA / pH / CYA readings BLANK.
   * Tap "Close job" → confirmation → tap "Close job" (destructive).
   * Assert `"Missing required readings"` alert (NOT "Close failed").
   * Assert alert body includes `"Free Cl, Total Cl, Alkalinity, pH, Cyanuric Acid"`
     (K60 expander applied to `"CYA"`).
   * Assert the ChemistryReadings section shows red-bordered
     inputs on the 5 missing fields.

**Auth**: `super@aquaterra.com` / `password123` (or the tech-scoped
`mike@aquaterra.com` for the pool-body checklist affordances).
`/api/openapi.json` reachable at `http://127.0.0.1:8001/api/openapi.json`
(1.7 MB), preview URL via `REACT_APP_BACKEND_URL`.

## Revert safety

Three independent commit atoms:

* **K61.a.2** — revert the `ApiError` class + throw site in
  `src/api.ts`.  Every existing catch site still works via
  `err.message`.  Zero downstream code depends on `err.status` or
  `err.detail` outside K61.b.2 + K61.c.
* **K61.b.2** — revert the `flushSave` return contract to `void`
  and the `saveDraft` / `closeJob` result-branching.  Autosave
  callers were already ignoring the return.
* **K61.c** — revert the K60 expander call in the chemistry-gate
  alert.  Labels fall back to backend-emitted strings.

## Follow-ups (out of scope, backlog)

* **K61.d (P2)** — Once `ApiError` is available cluster-wide, migrate
  other 422-sensitive surfaces to structural detection (customer
  merge, invoice validation, marketing post validators).  ~10-15
  call sites across the mobile codebase.
* **K61.e (P3)** — Full RTL behavioural test of `ChecklistScreen`'s
  saveDraft / closeJob flows.  Currently covered by contract +
  static-inspection assertions.  Full render test would exercise
  Alert.alert mock, mock offlineWrite / writeQueue / api.patch, and
  drive the sticky-footer buttons.  Not blocking — the contract
  tests lock in every branch.
* Pre-existing mobile TypeScript debt (~521 tsc errors) — separate
  P2 hygiene ticket.

## No backend touch

`POST /api/jobs/{id}/service-report/submit` and `PATCH /api/jobs/{id}/service-report`
are unchanged.  Verified live via curl this session:
- PATCH `{"notes":"K61 diag"}` → 200 with note persisted.
- POST `{}` on a checklist missing chemistry → 422 with correct
  structured detail body.

Backend behaviour is exactly what the pre-K61 dead-code catch was
designed to consume — K61 finally consumes it correctly.
