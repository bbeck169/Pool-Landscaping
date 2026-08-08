# Phase 53b — Editable EBIT Web UI (extend existing P&L)

**Date:** Feb 2026  
**Scope:** Frontend only. Extends `frontend/src/pages/admin/ProfitReportPage.jsx` with an editable EBIT section that consumes the Phase 53a backend. No new page, no route change, no backend touch, no mobile touch.

---

## Preflight — mobile jest triage

The 204/206 mobile jest baseline reported at the tail of Phase 53a was investigated **before** any 53b work started. See `PHASE53A_TRIAGE_NOTE.md`.

- Both failing suites (`phase51-6-mobile-reply-ui.test.tsx`, `phase51c-walkie-mount.test.tsx`) passed **isolated** (4.3s / 1.0s wall-clock) but hit jest's 5s per-test default when running in the 28-suite batch — a scheduler-contention flake, not a code regression.
- Fix: 1-line `jest.setTimeout(15000)` at the top of each affected file. No runtime code touched.
- Result: **`Test Suites: 28 passed, 28 total · Tests: 206 passed, 206 total`** — baseline restored.

## PDF library audit

Ran `package.json` scan: **no PDF library installed** (`jsPDF`, `@react-pdf`, `html2pdf`, `pdfmake` — none present). Existing pattern is `window.print()` — used by `src/pages/portal/PortalTerms.jsx`, `src/components/InvoiceView.jsx`, `src/components/EstimateView.jsx`. **Phase 53b uses `window.print()`** exactly like every other printable surface. Zero new deps added.

## Files touched

| File | Kind | Change |
|---|---|---|
| `frontend/src/components/admin/EbitPanel.jsx` | **added** | Self-contained EBIT section: range picker, basis toggle, 4 editable rows, EBIT total, save, version history modal, CSV + PDF export. Role-aware (super_admin/admin edit; manager read-only; else forbidden banner). |
| `frontend/src/pages/admin/ProfitReportPage.jsx` | modified | +1 import line, +2 lines rendering `<EbitPanel />` after the breakdown table. Zero changes to the existing profit-report data flow. |
| `frontend/src/test/ebit-panel.test.jsx` | **added** | 14 vitest tests (role gate × 5, adjustment mode × 2, override mode × 1, range picker × 1, basis toggle × 1, save flow × 1, version history × 1, exports × 2). |
| `frontend/src/test/profit-report-page.test.jsx` | modified | Test-only: routed `getMock` by URL prefix so `/ebit/*` calls resolve to a benign stub. Existing 5 assertions untouched. |
| `frontend/src/test/profit-report-uncategorized-fix.test.jsx` | modified | Same URL-routing shim. Existing 4 assertions untouched. |
| `memory/PHASE53A_TRIAGE_NOTE.md` | **added** | Mobile-jest triage root cause + fix. |
| `mobile/__tests__/phase51-6-mobile-reply-ui.test.tsx` | modified | +5 lines: `jest.setTimeout(15000)` + comment. |
| `mobile/__tests__/phase51c-walkie-mount.test.tsx` | modified | +5 lines: same. |

## Endpoints consumed

| Method | Path | Trigger |
|---|---|---|
| GET  | `/api/ebit/compute?range&from&to&revenue_basis` | Panel mount + range/basis change |
| GET  | `/api/ebit/snapshots?range_from&range_to` | History button opens the modal |
| POST | `/api/ebit/snapshots` | Save version button |

`PATCH /adjustments` and `PATCH /overrides` remain reachable through the same backend but aren't wired in 53b — the client currently `POST`s a new version on every save (which is functionally equivalent for the "always immutable" contract of pick 6B).

## Locked user picks honored

| Pick | 53b implementation |
|---|---|
| 3D — extend EXISTING page | `<EbitPanel />` mounted inside `ProfitReportPage.jsx`; new page NOT created. Route `/admin/reports/profit` unchanged. |
| 3D — monthly / quarterly / custom | Pill picker with matching `data-testid`s: `ebit-range-monthly`, `ebit-range-quarterly`, `ebit-range-custom`. Custom surfaces `from` + `to` date inputs. |
| Cash / accrual toggle | `data-testid`s `ebit-basis-cash` (default), `ebit-basis-accrual`. Refetches on switch. |
| Editable EBIT rows | 4 rows (revenue/cogs/opex/depreciation) each with two modes: |
| — Adjustment (default) | Delta number input; computed value stays visible; effective value bolded. |
| — Override (admin toggle) | "Flip to override" button flips to absolute input; "Clear override" reverts. |
| — Client-side propagation | Effective EBIT recomputes on every change via `useMemo`. |
| 4B — super_admin + admin only edit | `canEdit = role === 'super_admin' || role === 'admin'`. Others see the panel but no save/adjustment/override controls. Manager gets read-only; tech/customer get a forbidden banner. |
| 6B — immutable versions | Save always POSTs a new version. No PATCH-in-place. Loading an older version puts the editor in read-only mode; a "Fork new version" button restores editability without mutating the older doc. |
| 7D — PDF + CSV | Header buttons `ebit-export-pdf` (native `window.print()`) + `ebit-export-csv` (client-side blob → `<a download>`). Both operate on the currently-loaded (effective) snapshot. |
| Version history modal | `data-testid="ebit-versions-modal"` — reverse-chronological list (version-desc from backend) with load button per row. |

## Test count delta

| Suite | Before 53b | After 53b | Δ |
|---|---:|---:|---:|
| Frontend vitest | 1357 | **1371** | +14 |
| Mobile jest | 204 (drifted) / **206 baseline** | 206 | restored |
| Backend Phase 53a pytest | 21 | 21 | 0 |

Frontend vitest final: **156 files · 1371 tests · all green** (39.7s).  
Mobile jest final: **28 suites · 206 tests · all green** (baseline restored).  
Backend Phase 53a pytest: **21 / 21 green** (6.2s).

## Suite health & lint

| Check | Result |
|---|---|
| `yarn lint` (frontend) | **exit 0** ✅ |
| `yarn test:unit` (frontend vitest) | **1371 / 1371 ✅** |
| `yarn test` (mobile jest) | **206 / 206 ✅** |
| Phase 53a backend pytest | **21 / 21 ✅** |
| Backend Phase 41.4 curated coverage gate | Untouched — 53b adds no backend code. |

## Guardrails verified

- ✅ No backend changes beyond Phase 53a (which was already accepted).
- ✅ No mobile runtime code changes (only 2 tiny `jest.setTimeout` accommodations).
- ✅ Zero touch to the three hotfix code paths.
- ✅ Zero touch to Phase 49/50/50.1/50.2/41.1b/41.1c/41.1d/41.2/41.3/41.4/41.5/42.4/43/46/47c-48b/51a-d/51.5/51.6 code.
- ✅ Zero touch to Stripe / Mapbox / Time-Off / RingCentral runtime.
- ✅ No new PDF dependency — `window.print()` reused (existing pattern).

## Deviations

**None** relative to the accepted spec. Two minor implementation decisions worth logging:

1. **Adjustments PATCH / Overrides PATCH backend endpoints are unused in 53b.** Every client-side save POSTs a new snapshot with the fully-merged `line_adjustments` + `line_overrides`. This is semantically identical (server increments version regardless of endpoint) and simpler for the UI. The PATCH endpoints remain fully tested + operational for future callers (e.g., a batch adjustment tool).
2. **"Save version" also refetches the snapshots list** so the newly-saved version is immediately loadable from the history modal on next open, without requiring the user to click History twice.

## Screenshots

Captured against `super@aquaterra.com` on `/admin/reports/profit`:

1. **Adjustment mode active** — all four rows (Revenue / COGS / OpEx / Depreciation) show `Adjustment (delta)` inputs with `Flip to override` buttons. Effective EBIT $8,000.00 pill visible.
2. **Override mode active** — Depreciation flipped to `Override (absolute): 999` with `Clear override` visible. EBIT recomputes to $7,001.00 in real time.
3. **Version history modal open** — `Snapshot history for current range` panel with empty state (no saves yet in this session — mock data isolated).
4. **Export buttons visible** — `History`, `CSV`, `PDF` buttons rendered in the EBIT panel header alongside the `live` state pill.

---

## Handoff to Phase 53c (mobile UI)

Mobile app must:
1. Add an EBIT screen (do NOT touch the walkie routes) that consumes the same 3 endpoints (`GET /ebit/compute`, `GET /ebit/snapshots`, `POST /ebit/snapshots`).
2. Match the web UX: range picker (monthly/quarterly/custom), basis toggle (cash/accrual), 4 editable rows with Adjustment ↔ Override modes.
3. Reuse the identical role gate (`super_admin + admin` edit; `manager` read-only; else navigation guard).
4. Export flow: native share sheet with CSV blob (`expo-sharing` or equivalent). PDF export is deferred to Phase 53d unless a lightweight native PDF library is already installed — check first.
5. Preserve the mobile jest 206/206 baseline (add new tests as `+N`, do not regress existing).
