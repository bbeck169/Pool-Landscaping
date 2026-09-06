# Phase R1.c — Financial Suite Proper · PDF Exports + k50-Theming Fix + K73 Security Audit

**Status:** SHIPPED · Feb 2026
**Depends on:** R1.a (backend metrics · SHIPPED), R1.b (frontend Financial tab · SHIPPED)
**Unlocks:** ⚠ **K73 promoted to P0 security fix** (see §5 audit finding)

---

## 1. Scope shipped

### 1.1 Branded PDF exports for every R1 metric
- New module `services/reporting/exports/pdf_export.py`:
  - Uses `reportlab.platypus` (already in `requirements.txt` — no new dep).
  - Two public renderers: `render_scalar_pdf`, `render_rows_pdf`.
  - Shared template — tenant logo (guarded by an allow-list of
    trusted logo hosts to block SSRF via a rogue `logo_url`),
    branded navy title + green hero value, filter-summary
    breadcrumb, LongTable body (paginates across pages for the
    500-row unpaid-invoices export), footer with generated
    timestamp + tenant name + page numbers.
- New endpoint on `routers/reports_kpi.py`:
  - `GET /api/reports/kpi/{metric_key}/export.pdf`
  - Mirrors the `.csv` sibling — same registry lookup, same
    query params (`period`, `start`, `end`, `lens`,
    `service_type`, `tech_id`, `limit`, `offset`,
    `include_prior`).
  - Guarded by the existing `require_report_reader` role gate.
  - Response headers: `Content-Type: application/pdf`,
    `Content-Disposition: attachment;
    filename="{metric-kebab}__{period.key}__{start}_{end}.pdf"`,
    `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`.
- Wired into all 5 Financial-tab subsections as a
  **Download PDF** button alongside the existing Export CSV button:
  - `PnlPanel` → `pnl_line_items/export.pdf` → `pnl-{period}.pdf`
  - `CashFlowPanel` → `cashflow_by_period/export.pdf` → `cash-flow-{period}.pdf`
  - `ArAgingPanel` → `ar_aging_by_customer/export.pdf` (server sorts DESC, deeper drill-down) → `ar-aging-{period}.pdf`
  - `RevenueByServiceTypePanel` → `revenue_by_service_type/export.pdf` → `revenue-by-service-type-{period}-{lens}.pdf`
  - `UnpaidInvoicesPanel` → `unpaid_invoices/export.pdf?limit=500` → `unpaid-invoices-{period}.pdf`
- New frontend helper `components/reports/downloadServerPdf.js`
  — auth-preserving `fetch` → `Blob` → same-tab anchor download.
  Handles 401/403 by throwing an Error with the parsed `detail`
  so callers can surface it via `toast.error`. Returns the
  `Blob` in JSDOM (no `URL.createObjectURL`) for testability.

### 1.2 k50-theming test fix (K64 canonical)
Two quarantined asserts in `test/k50-theming.test.js` are now
back to enforcing shipped behavior:

- `QuickNavRail active state` — enforces
  `background: isActive ? colors.nav.bgActiveNavy : "transparent"`
  in `AppLayout.jsx`, plus a **regression guard** that the K52
  `colors.gradient.css` pattern MUST NOT reappear on this
  surface.
- `CategoryDropdown triggers` — enforces
  `background: active ? colors.nav.bgActiveNavy : undefined`
  in `AdminTopBar.jsx`, plus the same K52-gradient regression
  guard.

The `.skip` markers and TODO comments are gone. K64 is now the
canonical, test-locked design for the admin nav active state.

---

## 2. Files changed

New (6):
- `backend/services/reporting/exports/pdf_export.py`
- `backend/tests/test_r1_c_pdf_exports.py`
- `frontend/src/components/reports/downloadServerPdf.js`
- `frontend/src/test/reports-pdf-download-buttons.test.jsx`
- `memory/PHASE_R1_C_PDF_EXPORTS.md` (this file)

Modified:
- `backend/routers/reports_kpi.py` — new PDF export endpoint + logo resolver.
- `backend/services/reporting/exports/__init__.py` — re-export PDF renderers.
- `frontend/src/components/reports/PnlPanel.jsx` — Download PDF button.
- `frontend/src/components/reports/CashFlowPanel.jsx` — Download PDF button.
- `frontend/src/components/reports/ArAgingPanel.jsx` — Download PDF button.
- `frontend/src/components/reports/RevenueByServiceTypePanel.jsx` — Download PDF button.
- `frontend/src/components/reports/UnpaidInvoicesPanel.jsx` — Download PDF button.
- `frontend/src/test/k50-theming.test.js` — 2 quarantined asserts restored under K64 canonical shape.

---

## 3. Acceptance criteria vs shipped

| # | Criterion | Status |
|---|-----------|--------|
| 1 | All 5 PDF endpoints return well-formed PDFs (Content-Type + Content-Disposition correct) | ✅ (7 metric keys · all 200 + `application/pdf` + `%PDF-1.4` magic + locked filename shape) |
| 2 | Each PDF contains: tenant logo, title, period, filter summary, tabular data, timestamp footer | ✅ (rendered via shared template — logo fetched from allow-listed hosts, title/subtitle/filter breadcrumb/LongTable body/footer with timestamp + page number) |
| 3 | Download PDF buttons on Financial tab work end-to-end | ✅ (5 subsection buttons wired to `downloadServerPdf` — vitest-verified for path + filename) |
| 4a | Backend tests: 200 + PDF magic bytes + expected filename shape + role gate | ✅ (13 pytest cases in `test_r1_c_pdf_exports.py`) |
| 4b | Frontend tests: button click → correct endpoint + filename | ✅ (5 parametric vitest cases in `reports-pdf-download-buttons.test.jsx`) |
| 5 | Existing k50-theming tests updated to match K64 design and green | ✅ (23/23 pass in `k50-theming.test.js` — quarantines cleared) |
| 6 | All R1.a + R1.b tests still green | ✅ (118/118 backend pytest, 162/162 frontend vitest) |

---

## 4. Test summary

### Backend (pytest)
| Suite | Tests | Result |
|-------|-------|--------|
| `test_r1_paid_date_helper.py` | 12 | PASS |
| `test_r1_backend_metrics.py` | 25 | PASS |
| `test_r1_indexes_migration.py` | 11 | PASS |
| `test_r1_csv_exports.py` | 8 | PASS |
| `test_r1_b_send_reminder_audit.py` | 2 | PASS |
| `test_r1_c_pdf_exports.py` (new) | 13 | PASS |
| `test_r0_reports_kpi.py` (regression) | 15 | PASS |
| `test_r01_plus_prior_period_delta.py` (regression) | 20 | PASS |
| `test_r01_revenue_grouped.py` (regression) | 12 | PASS |
| **TOTAL** | **118** | **PASS** |

### Frontend (vitest)
- 25 files, **162 pass, 0 fail, 0 skipped** across R1.a/R1.b/R1.c
  panels + reminder button + tile flip + k50-theming (K64
  canonical) + K67 gradient + K70.a tile theming + adjacent flakes.

Reproduce:
```
# Backend
cd /app/backend && python -m pytest \
  tests/test_r1_paid_date_helper.py \
  tests/test_r1_backend_metrics.py \
  tests/test_r1_indexes_migration.py \
  tests/test_r1_csv_exports.py \
  tests/test_r1_b_send_reminder_audit.py \
  tests/test_r1_c_pdf_exports.py \
  tests/test_r0_reports_kpi.py \
  tests/test_r01_plus_prior_period_delta.py \
  tests/test_r01_revenue_grouped.py -q

# Frontend
cd /app/frontend && yarn vitest run \
  'src/test/reports-*' 'src/test/k50-theming*' 'src/test/k70a-*' \
  'src/test/k67-*' 'src/test/phase27-mute-control*' \
  'src/test/portal-login-hides-demo-tiles*'
```

### PDF sample rendering (live preview, super-admin)
Files land in `/tmp/r1c-*.pdf`:

| File | Size | Magic |
|------|-------|-------|
| `/tmp/r1c-pnl_by_period.pdf`         | 716,920 | `%PDF-1.4` |
| `/tmp/r1c-pnl_line_items.pdf`        | 717,440 | `%PDF-1.4` |
| `/tmp/r1c-cashflow_by_period.pdf`    | 716,995 | `%PDF-1.4` |
| `/tmp/r1c-ar_aging.pdf`              | 717,057 | `%PDF-1.4` |
| `/tmp/r1c-revenue_by_service_type.pdf` | 717,001 | `%PDF-1.4` |
| `/tmp/r1c-unpaid_invoices.pdf`       | 718,148 | `%PDF-1.4` |

Size lands in the ~715-720 KB band because every PDF embeds the
tenant logo (`https://app.plofv.com/logo-full.png`, ~700 KB).
Sanity floor test (`bytes > 5 KB`) catches empty-template
regressions. Ceiling (`bytes < 5 MB`) catches accidental
image-per-page duplications.

---

## 5. ⚠ K73 Security Audit — READ-ONLY FINDING

**Result: PII LEAK CONFIRMED. K73 is now P0 security.**

### Method
Logged in as `mike@aquaterra.com` (technician role), issued
`GET /api/jobs?limit=200`. Compared each returned job's
`tech_id` / `assigned_tech_id` / `technician_id` against the
authenticated user id.

### Finding
```
total: 36  mine_or_unassigned: 1  OTHER_TECHS: 35
SAMPLE_LEAK:
  {id: '08af77d0-…', tech_id: 'b8a68119-…',
   customer: 'Jennifer Carson', address: '12 Vistancia Blvd, Peoria, AZ'}
  {id: '2c74826c-…', tech_id: 'b8a68119-…',
   customer: 'Jennifer Carson', address: '12 Vistancia Blvd, Peoria, AZ'}
  {id: '1dce28fd-…', tech_id: 'b8a68119-…',
   customer: 'Jennifer Carson', address: '12 Vistancia Blvd, Peoria, AZ'}
```

- **35 of 36 returned jobs belong to a DIFFERENT tech.**
- Each leaked row exposes `customer` name and full physical
  `address`.
- Tenant scoping is correct (all jobs from `aquaterra`) — the
  missing enforcement is **tech-scoped filtering**.

### Impact
- Standard technician login can enumerate the ENTIRE tenant's
  service schedule with customer PII (name + address).
- Downstream: the same tech token likely leaks through the
  Schedule map endpoints too — recommend K73 also audit
  `/api/schedule/*` and any calendar API before shipping.
- Regulatory: this is a plausible CCPA/GDPR customer-data
  incident depending on tenant geography.

### Recommendation
Per the user's Step-0 directive: **K73 is promoted P0 and moves
ahead of R2** in the queue. Fix should:
1. Add a tenant + tech scope filter to `GET /api/jobs`
   (`tech_id == current_user.id` OR admin-role bypass).
2. Add the same filter to the schedule/map endpoints.
3. Include a contract test asserting a tech token cannot see
   another tech's jobs (mirroring the R1.b send-reminder audit
   test shape).
4. Consider a post-fix data-audit query to size the actual leak
   surface pre-shipping.

I did **NOT** ship any K73 code changes in this phase — the
audit is READ-ONLY as instructed.

---

## 6. Locked assumptions (inherited from R1.a/R1.b, unchanged)

- Default net terms 30 days.
- Calendar-month bookkeeping.
- AR Aging = past-due only (Option A · R1.a).
- Revenue lens default = `invoiced`.
- CSV column orders locked per subsection (R1.b).
- Tenant logo resolution order = `tenant.logo_url` >
  `tenant.settings.business_card.logo_url` > brand fallback
  (`https://app.plofv.com/logo-full.png`) — mirrors
  `services.auto_visit_email` / `services.price_increase_email`.
- Logo host allow-list = `app.plofv.com`, `plofv.com`,
  `cdn.plofv.com`, `images.unsplash.com`. Untrusted URLs
  silently fall back to a text wordmark (SSRF guard).

---

## 7. Deferred (out of R1.c)

- **K73 P0 security fix** — jobs+schedule tenancy scope. Bumped
  ahead of R2 per §5 audit finding.
- Reminder cadence R1.b+ — deferred post-R7 per user direction.
- R2 → R7 Financial Suites (sequential, one phase each).
- P&L "OpEx from `checks` collection" and Depreciation line —
  R2 / accounting integration.
- Column sort on the Financial-tab tables (server already sorts
  by canonical columns; client sort deferred).

---

## 8. Ship gate

- [x] All 13 new R1.c backend tests green
- [x] All 5 new R1.c frontend tests green
- [x] All 118 backend tests green (R0 → R1.c)
- [x] All 162 frontend tests green (R0.1 panels + R1.b panels + R1.c PDF buttons + tile flip + reminder + K50/K64/K67/K70.a theming)
- [x] Live smoke: 6 metric endpoints return branded `application/pdf` bodies to super-admin, `403` to tech + anon
- [x] Live smoke: PDFs open cleanly (verified by `%PDF-1.4` header + 5-700 KB size envelope)
- [x] k50-theming quarantines resolved under K64 canonical
- [x] K73 READ-ONLY security audit posted (**PII LEAK confirmed — K73 now P0**)
- [x] Phase doc written (this file)
- [ ] K73 P0 fix kickoff — **awaiting user green-light**
