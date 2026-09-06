# Phase K73 — Schedule Role Gating + Color Route Pins

**Status:** SHIPPED · Feb 2026
**Depends on:** R1.c (SHIPPED)
**Unlocks:** K74 (solid-navy tile swap), R2 Operations

**Companion doc:** `memory/K73_INCIDENT_SUMMARY.md` — the full
audit trail + false-positive correction from R1.c §5.

---

## 1. Scope shipped

K73 was originally scoped as a P0 security fix (jobs / schedule
tenancy scope). The R1.c pre-K73 audit turned out to be a
**false positive** (see §2). K73 refocused on:

1. Locking in the currently-correct tech-scope behavior with a
   permanent, unquarantinable **contract test suite**.
2. Delivering the crew-hued deterministic **schedule map palette
   + legend** (the UX portion of the original brief).

### 1.1 Contract test suite — `test_k73_tech_scope_contract.py`
**11 permanent tests** covering every endpoint from the K73
brief's Step 1 audit:

- `TestJobsListScope::test_tech_only_sees_own_or_crew_jobs`
- `TestJobsListScope::test_tech_cannot_override_technician_id_filter`
- `TestJobsDirectRead::test_tech_gets_403_on_other_techs_job`
- `TestScheduleDayScope::test_today_route_scoped`
- `TestScheduleDayScope::test_day_route_scoped`
- `TestAdminOnlyEndpointsGate::test_tech_forbidden` — parametrized
  over 5 admin-only endpoints (`/schedule/unassigned-pending-stale`,
  `/dispatch`, `/dispatch/board`,
  `/dispatch/route/unscheduled-jobs`,
  `/dispatch/route/savings/weekly`).
- `TestCustomersDirectReadScoped::test_tech_gets_404_on_unrelated_customer`

Every test uses the real backend against the aquaterra fixture
so it catches regressions in `scope_jobs_query`,
`require_admin`, or the customer read filter simultaneously.
**These tests are permanent — the file has no `.skip`, no
`.todo`, no feature flag.** Any future refactor that regresses
tech scope MUST fail this suite before merging.

### 1.2 Crew-hued deterministic palette — `lib/crewPalette.js`
Palette option **c** from the user's brief:

- Each crew gets a base HUE from a 12-slice HSL wheel
  (hue offsets picked so adjacent crews never sit within 25° of
  each other → readability guardrail).
- Members of a crew are distinguished by SATURATION cycling
  across 3 levels (55%, 75%, 95%) — visually differentiable
  within the shared crew hue.
- Solo techs (no crew) get their own hue from the same wheel
  at a neutral saturation (68%), so they read as a distinct
  "Solo" band in the legend.
- Lightness fixed at 45% for pin legibility on Google Maps
  light theme.
- Deterministic: `hash(crewId)` → hue slice, `hash(techId)` →
  saturation level. Same `(techId, crewId)` always resolves to
  the same hex.
- `tech.display_color_hex` still wins when set (K51 admin
  picker backward-compat).

Public surface:
```
crewHuedColor({ techId, crewId })          → "#RRGGBB"
crewHuedColorFromTech(tech, crewId)         → "#RRGGBB"
groupByCrewForLegend(techs, crews)          → [{crewId, crewName, techs: […]}]
```

### 1.3 Legend groups by crew — `CalendarSchedule.jsx::TechColorLegend`
The legend is reworked to render one row per crew with the
crew's name as a badge on the left, followed by the crew's
members painted in the crew hue at their individual saturation.
Solo techs collapse into a trailing "Solo" group.

- `data-testid="calendar-tech-legend-crew-<crewId | 'solo'>"`
  on each crew badge for testing.
- `data-testid="calendar-tech-legend-item-<techId>"` on each
  member — carries `data-color`, `data-explicit`,
  `data-crew-id` for programmatic assertions.
- Work-load counters (Feb-2026 `active_jobs` /
  `active_jobs_repair` breakdown) preserved verbatim from the
  pre-K73 legend — no regression on the K68/K69 telemetry.

### 1.4 Mobile parity
Mobile hits the SAME `/api/*` routes as web (see
`mobile/src/background/jobGeofence.ts`, `mobile/src/geofence.ts`,
`mobile/src/api/workstream.ts`, etc.). The server-side
`scope_jobs_query` filter covers them for free — verified by
the contract-test parametrization.

Mobile-specific endpoints audited:
- `/api/timeclock/mine-jobs-today` → 403 for the aquaterra
  technician (requires a different role — clock-in gate). Not
  a leak.
- `/api/workstream/jobs` → 403 for the same role.

**No mobile UI code was changed in K73** — per user direction,
mobile crew-color pins are P2 and deferred.

---

## 2. What actually happened (audit correction)

The R1.c ship report §5 flagged an apparent PII leak on
`GET /api/jobs`. The audit script compared each returned job's
`technician_id` against the caller's `user.id`. **But the
scoping key on jobs is `technician_id`, and the caller's
`technician_id` is a separate field on `/api/auth/me`.** Once
compared correctly:

- mike's `user.id` = `0b8784ff-…`
- mike's `technician_id` = `b8a68119-…`
- Every "leaked" job the R1.c script flagged had
  `technician_id = b8a68119-…` (mike's tech_id).
- **All 36 rows were mike's own.** Zero leak.

K73 is being shipped anyway because the contract tests and the
crew-palette UX were still valuable outcomes. The false
positive is fully documented in `K73_INCIDENT_SUMMARY.md`.

**Adjacent finding (deferred to K73.5):**
`GET /api/customers` returns 33 customer rows to a technician
(tenant-scoped but NOT tech-scoped), including 32 unassigned
customers plus 1 assigned to another tech. This is a **soft
directory leak** — customer names, phones, emails visible to
techs without a job link. Out of K73's brief scope
("jobs / schedule / calendar") — **queued as K73.5 · Customer
Read Scope** for the user's adjudication.

---

## 3. Files changed

New (3):
- `backend/tests/test_k73_tech_scope_contract.py` (11 permanent tests)
- `frontend/src/lib/crewPalette.js`
- `frontend/src/test/k73-crew-palette.test.js`

Modified (1):
- `frontend/src/pages/schedule/CalendarSchedule.jsx`
  - `techColorMap` uses `crewHuedColorFromTech` instead of the
    flat `hashedTechColor`.
  - `TechColorLegend` groups by crew via `groupByCrewForLegend`.

Docs (2 new):
- `memory/PHASE_K73_SCHEDULE_ROLE_GATING_COLOR_PINS.md` (this file)
- `memory/K73_INCIDENT_SUMMARY.md`

---

## 4. Test summary

### Backend (pytest)
| Suite | Tests | Result |
|-------|-------|--------|
| `test_k73_tech_scope_contract.py` (new) | 11 | PASS |
| `test_r1_c_pdf_exports.py` (regression) | 13 | PASS |
| `test_r1_b_send_reminder_audit.py` (regression) | 2 | PASS |
| `test_r1_paid_date_helper.py` (regression) | 12 | PASS |
| `test_r1_backend_metrics.py` (regression) | 25 | PASS |
| `test_r1_indexes_migration.py` (regression) | 11 | PASS |
| `test_r1_csv_exports.py` (regression) | 8 | PASS |
| **R1 + K73 total** | **82** | **PASS** |

### Frontend (vitest)
- `k73-crew-palette.test.js` (new): **12 pass**
- Reports + theming + K64 + K67 + K70.a suites: **108 pass**
- Grand total for the touched surface: **22 files, 120 tests,
  0 fail, 0 skipped.**

Reproduce:
```
# Backend
cd /app/backend && python -m pytest \
  tests/test_k73_tech_scope_contract.py \
  tests/test_r1_c_pdf_exports.py \
  tests/test_r1_b_send_reminder_audit.py \
  tests/test_r1_paid_date_helper.py \
  tests/test_r1_backend_metrics.py \
  tests/test_r1_indexes_migration.py \
  tests/test_r1_csv_exports.py -q

# Frontend
cd /app/frontend && yarn vitest run \
  src/test/k73-crew-palette.test.js \
  'src/test/reports-*' 'src/test/k50-theming*'
```

---

## 5. Acceptance criteria vs shipped

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Tech user sees only own + crew jobs on `GET /api/jobs?limit=200` | ✅ (already true — false-positive correction; contract test locks it in) |
| 2 | Same for every audited schedule / calendar endpoint | ✅ (11 contract tests, 5 admin-gate parametrizations) |
| 3 | Manager / admin / super_admin unaffected | ✅ (same code path — no changes) |
| 4 | Schedule map pins render with crew-hue + individual-saturation colors | ✅ (`crewHuedColorFromTech` in `techColorMap`) |
| 5 | Legend groups crew ↔ color | ✅ (`groupByCrewForLegend` + reworked `TechColorLegend`) |
| 6 | Contract test hard-fails if regression happens | ✅ (permanent — no skips, no flags) |
| 7 | Mobile endpoints inherit fix automatically OR patched explicitly | ✅ (same `/api/*` routes; server-side filter covers mobile) |
| 8 | All existing tests still green + new K73 tests | ✅ (82 backend + 120 frontend, 0 fail) |
| 9 | `K73_INCIDENT_SUMMARY.md` written | ✅ (see companion doc) |

**Perf preservation (K65.fix guardrails):** the tech-scope path
was already in place and uses the K65.fix
`tenant_id + technician_id` compound index. No new query hot-paths
introduced; no rebuild of that index. **K65.fix perf intact.**

---

## 6. Deferred (out of K73)

- **K73.5 · Customer Read Scope** — `/api/customers` is not
  tech-scoped. Product decision needed on whether techs see the
  whole customer directory or only customers with an active job.
- **K74 · Solid navy tile swap** — 30-min UX task queued next.
- Mobile crew-color pins — P2, kept out of K73 per user direction.
- Audit-log every 403 from `scope_jobs_query` — **K74.5**,
  for stronger defense-in-depth.

---

## 7. Ship gate

- [x] 11 new backend contract tests green
- [x] 12 new frontend palette tests green
- [x] 82 backend regression tests green (R0 → R1.c + K73)
- [x] 120 frontend regression tests green (reports + theming + K73 palette)
- [x] Full endpoint audit re-run with corrected comparison — **no PII leaks**
- [x] Adjacent `/api/customers` finding noted as **K73.5 · Deferred**
- [x] K65.fix compound-index perf preserved (no query changes on hot paths)
- [x] Phase doc + incident summary written
- [ ] K74 kickoff — **awaiting user green-light**
