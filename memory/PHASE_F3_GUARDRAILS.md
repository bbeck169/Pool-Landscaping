# Phase F3 · Feb-2026 — Prophylactic Guardrails

## Ship summary
Three guardrails so the F1/F2 corruption class never accumulates again:

### Part A — Startup boot-check
- New module `services/startup/integrity_check.py`.
- Runs at the tail of the FastAPI startup event (after all migrations).
- Scans `db.jobs` for dangling `customer_id`, `technician_id`, `crew_id` refs.
- **Fail-fast on `customer_ref` OR `crew_ref` classes** when
  `INTEGRITY_CHECK_ENFORCE` resolves to `true` (default: on in
  production, off elsewhere). Raises `IntegrityCheckFailure` which
  aborts FastAPI startup.
- **`technician_ref` class is CRITICAL-log-only** — softened per
  testing-agent's boot-brick advisory. An admin promoting a tech to
  admin silently removes their id from the live tech space; that's
  a legitimate action, not corruption, and must not brick prod boot.
  Ops still sees the CRITICAL log + can repair via F2.
- Live boot log: `INFO services.startup.integrity_check: [integrity_check] clean — 0 dangling refs (enforce=True)`.

### Part B — Hard-delete cascade/block
Return HTTP 409 with `error_code=has_referencing_jobs` on:

| Surface | Location |
|---|---|
| `DELETE /api/customers/{cid}?mode=hard` | `routers/customers.py` — new block right after the existing unpaid-invoice check |
| `POST /api/customers/bulk` action=delete | `routers/customers.py` — deprecated path, still writeable |
| `DELETE /api/crews/{cid}` | `routers/ops.py` |

Only ACTIVE jobs (`status != 'deleted'` AND `deleted_at` null/absent)
block; soft-deleted jobs cannot orphan an active reference.

No user hard-delete surface exists in the codebase (verified via
grep), so no equivalent block was needed there.

### Part C — Contract tests (permanent locks)
| Test file | Coverage |
|---|---|
| `test_startup_integrity_check.py` | 14 tests — scan classification, enforcement flag, boot-brick guard (technician-only refs never raise, customer/crew do), mixed-class semantics |
| `test_tech_authorization_uses_shared_helper.py` | 1 AST-scan test walking one level of indirection (accepts same-module shim like `_tech_can_touch`) |
| `test_hard_delete_blocks_referencing_jobs.py` | 5 tests — crew (200/409/soft-delete-immune), bulk customer delete (200/409) |
| `test_portal_endpoints_never_trust_body_customer_id.py` | 2 tests — FastAPI route introspection + strict pydantic guard |

### Part D — Runbook + env docs
- `/app/memory/DATA_INTEGRITY_RUNBOOK.md` — full operator recovery
  procedure covering all three phases (F1 auth semantics, F2
  dry-run/apply, F3 boot-check + 409 unblock paths).
- `backend/.env.example` — new `INTEGRITY_CHECK_ENFORCE=false`
  entry with defaults documented.

## F2 clarification (from user's follow-up)
The 2 Sara Nguyen `technician_id` refs from the original audit
turned out to be **NOT dangling**: Sara is alive in `db.technicians`
(`id=3b6ebe3c-fa87-4dec-a5db-7a55a86cfc7c`, `email=sara@aquaterra.com`).
The audit's "2 orphan-tech refs" reading was against a snapshot
where she'd been temporarily deleted; a re-seed restored her before
F2 shipped. F2's scanner is correct at 0 orphan-tech refs today. If
she gets hard-deleted again, F2 catches those 2 jobs — but F3's
hard-delete block on `db.users` doesn't exist because there's no
user-hard-delete surface anywhere in the router space.

## Testing agent findings — all addressed
| Priority | Finding | Status |
|---|---|---|
| CRITICAL code review | Boot-brick risk if admin promotes tech to admin (technician_ref would dangle → fail-fast in prod) | **Fixed** — technician_ref is now log-only. Customer + crew classes remain fail-fast. Tests `test_run_check_technician_class_alone_does_not_fail_fast` + `test_run_check_crew_class_alone_does_fail_fast` + `test_run_check_mixed_classes_fail_fast_on_customer_or_crew` lock the semantics. |
| Advisory | `_live_technician_ids` doesn't filter `db.users` by `deleted_at` — lenient by design | **Fixed** — added explicit docstring note explaining the semantics. |
| Advisory | Check not tenant-scoped | Deferred — low practical risk (id namespaces are UUIDs) + adds cost. TD entry if needed. |
| Cosmetic | Detail-key asymmetry between customers/crews 409 | Deferred — both carry `error_code`; asymmetry is legacy `detail:customer_has_referencing_jobs` on customer path only. Non-breaking. |
| Out-of-scope | `DELETE /api/jobs/{jid}` is a raw hard delete | Noted for future TD. |

## Deferred advisories (logged for the user)
| ID | Description |
|---|---|
| TD-13 | Split `run_id` from `confirm_token` on F2 apply (leaked history entry shouldn't expose apply credential) |
| TD-14 | Paginate `GET /api/admin/data-repair/history` at scale |
| TD-15 (new) | Consider adding tenant-scoping to `integrity_check.scan_dangling_refs` |
| TD-16 (new) | Consider audit-logging `DELETE /api/jobs/{jid}` and/or blocking hard-delete when the job has line items / photos referencing it |

## Test totals
- **F3 unit**: 22/22 pass (14 startup + 1 AST + 5 hard-delete + 2 portal)
- **F3 live**: 10/10 pass (testing agent's `test_f3_guardrails_live_api.py`)
- **Full sweep (F1+F2+F3)**: 56/56 unit + 10 live = 66 tests
- **Testing agent's full pytest sweep**: 90 passed / 1 skipped, 100% success rate

## Files touched
| File | Change |
|---|---|
| `backend/services/startup/__init__.py` | **NEW** — namespace init |
| `backend/services/startup/integrity_check.py` | **NEW** — scan + boot-check (~230 LOC) |
| `backend/server.py` | +18 LOC — startup hook |
| `backend/routers/customers.py` | +54 LOC — 2 hard-delete blocks |
| `backend/routers/ops.py` | +25 LOC — crew hard-delete block |
| `backend/.env.example` | +16 LOC — `INTEGRITY_CHECK_ENFORCE` documented |
| `backend/tests/test_startup_integrity_check.py` | **NEW** — 14 tests |
| `backend/tests/test_tech_authorization_uses_shared_helper.py` | **NEW** — AST contract |
| `backend/tests/test_hard_delete_blocks_referencing_jobs.py` | **NEW** — 5 tests |
| `backend/tests/test_portal_endpoints_never_trust_body_customer_id.py` | **NEW** — 2 tests |
| `memory/DATA_INTEGRITY_RUNBOOK.md` | **NEW** — operator runbook |
