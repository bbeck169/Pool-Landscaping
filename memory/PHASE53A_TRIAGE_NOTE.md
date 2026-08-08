# Phase 53a Triage Note — mobile jest 204/206 → 206/206

**Date:** Feb 2026 (during Phase 53a acceptance)  
**Trigger:** Post-53a run showed mobile jest at 204/206 vs. the
Phase 51.6 handoff baseline of 206/206.

## Failing suites

| Suite | Isolated result | Batch result (pre-fix) |
|---|---|---|
| `__tests__/phase51-6-mobile-reply-ui.test.tsx` | ✅ PASS (4.3s wall, 2.15s per-test) | ❌ FAIL — "Exceeded timeout of 5000 ms" on first test |
| `__tests__/phase51c-walkie-mount.test.tsx` | ✅ PASS (1.0s wall, 251ms per-test) | ❌ FAIL — "Exceeded timeout of 5000 ms" on first test |

## Root cause

**Batch-order scheduling flake — NOT a code regression.**

Both failing tests are the FIRST test in their file. When jest runs all
28 suites in a single batch, the scheduler contention (React Native
tests share the `react-test-renderer` heavy setup + async mock
resolution) pushes the wall-clock of the very first test past jest's
default 5000ms per-test timeout, even though the CPU time is well
below 1s (as proven by isolated runs passing in 2.15s and 251ms).

Every subsequent test in the same file passes because the suite is
already warm — the timeout only bites on the file's first `it(...)`.

## Why this drifted between Phase 51.6 handoff and Phase 53a

The 28-suite batch has grown organically. Every RN-heavy suite added
after Phase 51.6 (file-upload-components, PortalChatAttachments,
f2c1-booking-photos, invoice-attachments) increases scheduler
contention on the shared node process. There was no code change in
walkie mobile code between 51.6 and 53a — a `git log` on
`/app/mobile/app/walkie/` and `/app/mobile/__tests__/phase51*` confirms
the last touch was the 51.6 delivery itself.

## Not caused by Phase 53a

Phase 53a is strictly backend (`/app/backend/services/finance/`,
`/app/backend/routers/ebit.py`, `/app/backend/tests/…`). Zero mobile
code touched. Root-cause confirmed to pre-date this session.

## Fix applied (deterministic, 1-line each)

Both files get a top-of-file:
```ts
jest.setTimeout(15000);
```

Rationale: 15s is well above the observed 5s wall-clock ceiling in
batch runs, cheap, non-invasive, and does NOT touch runtime code or
snapshot expectations. Any future timing drift up to 3× current
levels would still be caught.

## Result post-fix

`yarn test` (batch, 28 suites): **Test Suites: 28 passed, 28 total ·
Tests: 206 passed, 206 total** — baseline restored.

## Files touched (triage only)

| File | Change |
|---|---|
| `/app/mobile/__tests__/phase51-6-mobile-reply-ui.test.tsx` | +5 lines (`jest.setTimeout(15000)` + comment) |
| `/app/mobile/__tests__/phase51c-walkie-mount.test.tsx` | +5 lines (same) |

No walkie runtime code, no shared helper, no snapshot updates.
