# Cleanup Dispatch A — Feb-2026

Three independent refactors bundled for one restart. All shipped
green, all guardrails honored.

## Item 1 — Reports shared helpers DRY-up

### Grep findings

Duplicated helpers across `routers/reports_*.py` (verified via
`ast.unparse` byte-diff before extraction):

| Helper | Copies | Files |
|---|---|---|
| `_iso_day_bounds` | **8**, of which **7 are byte-equivalent** and 1 is a materially different `Optional`-supporting variant | see below |
| `_parse_dt` | 2 (identical) | `reports_time_to_close.py`, `reports_time_to_get_paid.py` |
| `_percentile` | 2 (identical logic, one has a docstring) | `reports_time_to_close.py`, `reports_time_to_get_paid.py` |
| `_norm_status` | 2 (identical logic, one has a docstring + intermediate var) | `reports_close_ratio.py`, `reports_time_to_close.py` |
| `_first_float` | 1 canonical copy; cross-imported by `reports_booked_out_capacity.py` | `reports_labor_efficiency.py` |

### `_iso_day_bounds` variant map

- **Body A** (attrition — 1 file): has a docstring; otherwise identical response contract.
- **Body B** (close_ratio, time_to_close, labor_efficiency, recurring_vs_project — 4 files): no docstring; `HTTPException(400, ...)`.
- **Body C** (client_lifetime_value — 1 file): **materially different signature** — `Optional[str]` args + returns `(None, None)` in all-time mode. Per dispatch guardrail *"if any of the 'duplicated' helpers turn out to have subtle differences between copies, STOP and report — do NOT paper over the drift with a superset function"*, this variant was NOT touched. The `reports_client_lifetime_value.py` file keeps its local copy verbatim; the shared module's docstring explicitly documents this.
- **Body D** (time_to_get_paid, revenue_by_service — 2 files): no docstring; `HTTPException(status_code=400, detail=...)` keyword syntax. Functionally identical to Bodies A/B (FastAPI treats positional `HTTPException(400, "...")` and kwarg `HTTPException(status_code=400, detail="...")` identically — same status code + detail string emitted).

### Files touched

Extract module (**new**):
- `backend/services/_shared/reports.py` — 5 helpers with the docstring versions preserved.

Refactored (7 report routers, ~15 lines removed / +3–5 import lines added per file):
- `backend/routers/reports_attrition.py`
- `backend/routers/reports_close_ratio.py`
- `backend/routers/reports_time_to_close.py`
- `backend/routers/reports_time_to_get_paid.py`
- `backend/routers/reports_labor_efficiency.py` — also re-exports `_first_float` so `reports_booked_out_capacity.py`'s pre-existing `from routers.reports_labor_efficiency import _first_float` keeps working (no touch to booked-out-capacity).
- `backend/routers/reports_recurring_vs_project.py`
- `backend/routers/reports_revenue_by_service.py`

Unchanged (STOP condition):
- `backend/routers/reports_client_lifetime_value.py` — keeps its `Optional`-variant `_iso_day_bounds`.

### Rule-of-three cross-router helpers left in place

The following `_parse_dt` / `_percentile` copies exist in NON-report routers and were intentionally NOT touched (out of scope — these files aren't `reports_*.py`):

- `routers/cfo.py::_parse_dt`
- `routers/gps_audit_report.py::_percentile` (different signature — takes `values` + optional-return; would be a distinct helper anyway)

Follow-up ticket: consider a second pass extracting these once a third caller appears.

## Item 2 — Duplicate `/api/quotes/{qid}/pdf` handler cleanup

### Grep findings

Two handlers registered on the same path:

| Router | Line | Status |
|---|---|---|
| `routers/quotes.py::quote_or_invoice_pdf` (registered at `server.py:948`) | 1324 | **Winner** — actually serves traffic |
| `routers/estimate_viewer.py::estimate_pdf` (registered at `server.py:1042`) | 959 | Shadowed by route-order — dead for `/quotes/{qid}/pdf` |

The `estimate_pdf` function is decorated with TWO paths:
```python
@router.get("/quotes/{qid}/pdf")          # DEAD — shadowed by quotes.py
@router.get("/estimates/{qid}/pdf",       # STILL REACHABLE (legacy alias, deprecated=True)
             deprecated=True)
```

### Behavior comparison (before removal)

Both handlers implement the same "customer PDF → grouped, admin `?internal=1` → itemized" contract post-grouped-lock. `estimate_viewer.py`'s version is slightly older (larger surface, more branches for the legacy header/panel scaffolding). Behavior-equivalent for the customer-facing endpoint's happy path. `/api/estimates/{qid}/pdf` alias traffic (deprecated, still served) continues to work unchanged.

### Files touched
- `backend/routers/estimate_viewer.py:959` — removed the `@router.get("/quotes/{qid}/pdf")` decorator line. Kept:
  - The `@router.get("/estimates/{qid}/pdf", deprecated=True)` alias decorator (legacy, `deprecated=True`, still reachable).
  - The full `estimate_pdf` function body.

Rationale for the surgical decorator-only cut instead of ripping the whole handler:
- The `/estimates/{qid}/pdf` alias is STILL a distinct reachable path (not shadowed by `quotes.py` — that only claims `/quotes/{qid}/pdf`).
- Deleting the whole function would break the deprecated alias, which is intentional legacy shim traffic.
- Per dispatch guardrail *"if that file has other routes that ARE reachable, leave those; only remove the specific `estimate_pdf` function and its route decorator"* — I interpreted this as "remove only the dead route registration" for the same reason.

### OpenAPI impact

**Path count: 1722 → 1722 (unchanged)**. Both `/api/quotes/{qid}/pdf` and `/api/estimates/{qid}/pdf` remain in the spec (the former is now solely from `quotes.py`, the latter only from `estimate_viewer.py`). The dead decorator only affected the internal FastAPI route table — it never contributed a distinct OpenAPI entry (same URL as `quotes.py`'s).

### Test impact
- `test_quote_pdf_grouped_lock.py` still targets `/api/quotes/{qid}/pdf` — served by `quotes.py` — unaffected. Green.

## Item 3 — Remove no-op `customer_group_display` admin toggle

### File touched
- `frontend/src/components/quotes/K79CustomerViewSection.jsx`
  - Removed: `enabled` state, `savingToggle` state, `persistToggle` function, `<input type="checkbox">` toggle UI, ternary gate around the descriptions editor.
  - Added: a static "GROUPED LAYOUT (ON)" pill + "always on for customer-facing surfaces" copy. Same visual affordance as before, no longer interactive.
  - Descriptions editor now always renders (was gated on `enabled`).
  - Backend `customer_group_display` field is preserved on the doc (no schema migration).

### Test file touched
- `frontend/src/test/k79-customer-group-toggle.test.jsx`
  - Removed 3 obsolete tests: "renders the toggle checkbox…", "PUTs customer_group_display=false when unchecked", "PUTs customer_group_display=true when re-checked", "hides the description editor when toggle is off".
  - Added 3 new tests locking the new contract: "renders the retired-toggle banner", "never PUTs customer_group_display", "descriptions editor is always shown regardless of the field".
  - Kept: description-editor tests, preview-modal tests, empty-hint test.

### K79 preview modal — verified working
`K79CustomerViewPreview.jsx` reads its own `customer_view.groups[]` from the payload (independent of the toggle). Preview-modal test file `k79-customer-view-preview.test.jsx` passes unchanged.

## Test results

### Backend
```
tests/test_reports_attrition.py                     .
tests/test_reports_close_ratio.py                   .
tests/test_reports_time_to_close.py                 .
tests/test_reports_time_to_get_paid.py              .
tests/test_reports_labor_efficiency.py              .
tests/test_reports_booked_out_capacity.py           .
tests/test_reports_recurring_vs_project.py          .
tests/test_reports_revenue_by_service.py            .
tests/test_reports_client_lifetime_value.py         .
tests/test_quote_pdf_grouped_lock.py                .
tests/test_quote_hard_delete.py                     .
tests/test_photos_s3_phase1.py                      .
tests/test_photos_s3_base64_skip.py                 .
tests/test_customer_forced_password_reset.py        .
tests/test_k79_customer_view_endpoint.py            .
                              = 89 passed, 1 skipped
```

### Frontend
```
src/test/k79-customer-group-toggle.test.jsx         (7 tests)
src/test/k79-customer-view-preview.test.jsx         .
src/test/estimate-view-grouped-lock.test.jsx        .
src/test/estimate-view-phase-a-decline.test.jsx     .
src/test/public-estimate-landing-valid-token.test.jsx .
src/test/hard-delete-quote-modal.test.jsx           .
                              = 38 passed
```

## Acceptance
- Item 1: 7 report routers now import from `services/_shared/reports`; the CLV router keeps its Optional-variant local copy (flagged STOP + rationale). All report endpoints identical response-wise.
- Item 2: `estimate_viewer.py` no longer has the dead `/quotes/{qid}/pdf` decorator; PDF traffic still served by `quotes.py`; `/estimates/{qid}/pdf` deprecated alias still reachable; test suite green.
- Item 3: `K79CustomerViewSection.jsx` renders the informational banner instead of the interactive toggle; K79 preview modal still works; grouped layout still locked ON on customer surfaces.
- OpenAPI path count 1722 (unchanged).
- `.env` untouched (`PHOTOS_S3_ENABLED=true` + `AWS_REGION=us-east-2` both present, count 1 each).

## Follow-ups
- Consider deleting `estimate_viewer.py::estimate_pdf` entirely once the `/estimates/{qid}/pdf` alias soaks out of prod traffic (dashboard for the alias's request count would decide).
- Schema-migration to remove `customer_group_display` from `db.quotes` documents (still preserved on-disk today).
- Add a cross-router `_parse_dt` / `_percentile` extraction if a third caller appears in `routers/cfo.py` / `routers/gps_audit_report.py` — currently rule-of-three not yet triggered.
