# TD-86 · crew tech_ids cleanup — run log

This file is a cumulative run log for the cleanup script
``backend/scripts/cleanup_crew_cross_tenant_tech_ids.py``.
Each invocation appends a dated block below so the operator has
a single artefact tracking the full dry-run → apply →
idempotency-verify sequence.

Blocks are listed oldest-first.

---

## Block 1 · Pre-apply dry-run (td86-cleanup ship)

- **Timestamp:** 2026-10-19T02:59:40.462257+00:00
- **Mode:** DRY-RUN (read-only)
- **Scope:** every tenant

### Grand totals

- crews_scanned: **2**
- crews_with_drift: **2**
- tech_ids_pruned_orphan: **4**
- tech_ids_pruned_foreign_tenant: **0**
- member_added_at_entries_pruned: **4**
- crews_updated: **0** (no writes — dry-run)
- crews_failed_with_reason: 0

### Per-tenant breakdown

#### `affdfbfa-88b9-4baa-ae45-2ef78531b6e4` (Pool & Landscaping of Vistancia)

- crews_scanned: 2
- crews_with_drift: 2
- tech_ids_pruned_orphan: 4
- tech_ids_pruned_foreign_tenant: 0
- member_added_at_entries_pruned: 4
- crews_updated: 0

Expected drift from TD-86 audit confirmed exactly. Zero cross-
tenant drift on preview. 100% orphan ids (hard-deleted techs).

---

## Block 2 · Apply (operator green-lit, preview-only)

- **Timestamp:** 2026-10-19T03:02:13.639521+00:00
- **Mode:** APPLY (writes)
- **Scope:** every tenant
- **Trigger:** operator "GREEN LIGHT #1 — TD-86 preview `--apply`"
  (prod `--apply` remains operator-executed and gated on a
  separate greenlight).

### Grand totals

- crews_scanned: **2**
- crews_with_drift: **2**
- tech_ids_pruned_orphan: **4**
- tech_ids_pruned_foreign_tenant: **0**
- member_added_at_entries_pruned: **4** (lockstep sister-map)
- crews_updated: **2** (writes applied)
- crews_failed_with_reason: 0

### Per-tenant breakdown

#### `affdfbfa-88b9-4baa-ae45-2ef78531b6e4` (Pool & Landscaping of Vistancia)

- crews_scanned: 2
- crews_with_drift: 2
- tech_ids_pruned_orphan: 4
- tech_ids_pruned_foreign_tenant: 0
- member_added_at_entries_pruned: 4
- crews_updated: 2

Zero failures. Both crews (Blue Crew `10851a3d-...` + Green Crew
`1c1ec59e-...`) now carry a clean, empty ``tech_ids`` array and
a matching empty ``member_added_at`` map.

---

## Block 3 · Post-apply idempotency re-run

- **Timestamp:** 2026-10-19T03:02:25.772791+00:00
- **Mode:** DRY-RUN (read-only)
- **Scope:** every tenant

### Grand totals

- crews_scanned: **2**
- crews_with_drift: **0** ✅ idempotency verified
- tech_ids_pruned_orphan: 0
- tech_ids_pruned_foreign_tenant: 0
- member_added_at_entries_pruned: 0
- crews_updated: 0 (no writes — dry-run)
- crews_failed_with_reason: 0

### Per-tenant breakdown

_No crews with drift found._

Idempotent re-run returns zero drift — the ``--apply`` cycle
rewrote both crews' ``tech_ids`` + ``member_added_at`` to the
clean set, so a subsequent pass finds nothing to prune.

---

## Live-API smoke test (post-apply)

- `PATCH /api/crews/10851a3d-1321-4d9e-99af-0096325a7652`
  (Blue Crew — previously 400'd on edit-save) with
  ``{"tech_ids": []}`` → **200 OK**:
  ```
  {"id": "10851a3d-...", "name": "Blue Crew", "tech_ids": []}
  ```
  Operator-facing bug is resolved: the crew that used to fail
  with the misleading "tech_ids references members not in this
  tenant" 400 now saves cleanly from an admin editor.

---

## Operator note on prod

**Prod `--apply` is NOT run.** Standing dispatch policy:

```
python backend/scripts/cleanup_crew_cross_tenant_tech_ids.py --apply
```

on prod requires a separate operator greenlight. The script is
tenant-safe via ``--tenant <id>`` so the operator can quarantine
a prod run to one tenant at a time if preferred. Idempotent
re-run means a false-positive on prod cannot double-prune.

Prod expectation (unverified until operator runs the diagnostic
there): the script's categorised counters will surface any
``tech_ids_pruned_foreign_tenant`` > 0 cases that preview did
not have — these are the genuine cross-tenant drift rows the
TD-86 audit flagged as possible on prod. The ``--dry-run``
block from a prod invocation should be reviewed before
``--apply`` runs there.
