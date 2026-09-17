# Pre-existing test failures — checkpoint

**Purpose**: track pre-existing test failures spotted during recent tickets so we don't lose them. This is NOT a work ticket — it's a running log. When a failure is fixed, delete the entry (or move it to a "resolved" section).

**Last updated**: Feb 2026 (during SP2 delivery of the Business Signup + Onboarding Wizard).

---

## 1. `test_service_report.py::test_submit_locks_report`

* **Failing since**: pre-CHEM2 (i.e. before Feb-2026). Not introduced by any recent phase.
* **Reproducible independent of any recent work**: **YES** — reproduced by stashing every CHEM2 change and re-running. Same three tests fail with the identical error.
* **Symptom**: gets 422 where the fixture expected 200. The service-report fixture in this test builds a payload whose water bodies fail the CHEM1 gate.
* **Recommended fix**: audit the test fixture — either (a) fill the Required Four on the primary body of the fixture payload, or (b) mark the test as `@pytest.mark.xfail(strict=False)` with a link back to this file. Option (a) is preferred; roughly a 15-minute change.

## 2. `test_service_report.py::test_empty_tenant_template_falls_back_to_pool_defaults`

* **Failing since**: pre-CHEM2. Not introduced by any recent phase.
* **Reproducible independent of any recent work**: **YES**.
* **Symptom**: fixture looks for a `"chlorine"` key inside a template snapshot, but the current pool default template uses `"free_chlorine"` — the pre-CHEM1 rename was never picked up in the fixture.
* **Recommended fix**: update the fixture's key expectation from `"chlorine"` → `"free_chlorine"` (30-second change). Same rename was applied everywhere else in the codebase during CHEM1.

## 3. `test_service_report.py::test_algae_field_round_trips_alongside_chemistry`

* **Failing since**: pre-CHEM2. Not introduced by any recent phase.
* **Reproducible independent of any recent work**: **YES** — same stash-and-rerun confirmation as #1 and #2.
* **Symptom**: same `"chlorine"` vs `"free_chlorine"` key mismatch as #2, just in a different assertion.
* **Recommended fix**: same as #2 — update the fixture. This trio (`test_submit_locks_report`, `test_empty_tenant_template_falls_back_to_pool_defaults`, `test_algae_field_round_trips_alongside_chemistry`) likely share the same broken fixture builder — a single fix probably clears all three.

## 4. `test_phase_d4_endpoint_and_seeder.py` — test-order flakiness

* **Failing since**: D4 shipping (Feb-2026, pre-D5). Passes when run in isolation OR in most orderings; fails when specific combinations of prior tests leave DB state behind.
* **Reproducible independent of any recent work**: **YES** — reproduced by stashing every D5 change and re-running `test_multi_industry_phase_a.py + test_resolve_row_label_fallback_chain.py + test_phase_d4_endpoint_and_seeder.py` in that order.
* **Symptom**: 7 of the 9 D4 endpoint tests fail when a specific prior test leaves the `industry_checklist_templates` collection in a partially-seeded state.
* **Recommended fix**: add an autouse fixture at the top of `test_phase_d4_endpoint_and_seeder.py` that either (a) rolls the `industry_checklist_templates` and `tenant_checklist_overrides` collections to a known clean state before each test, or (b) uses a unique tenant slug per test so no cross-test collision is possible. Option (b) is safer.

---

## Not a bug — noted for context

* The FastAPI `on_event("startup")` deprecation warning fires on every backend test run. Migrate to lifespan events when we do the FastAPI 1.0 upgrade. Zero functional impact today.
* `pydantic v1 → v2 deprecation warnings` on ~20 models. Same migration ticket, no functional impact.
