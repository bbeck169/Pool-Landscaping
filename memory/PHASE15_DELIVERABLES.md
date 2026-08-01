# Phase 15 · Feb-2026 — B4/B5 Lumino paid_at Backfill + Stripe env cleanup gate

## Sub-item 1 · Investigation Micro-Report (14 lines)

1. **`db.payment_events` total**: 8 rows.
2. **Breakdown by `event_type`**: `payment.created` = 5, `invoice.link_created` = 3. `status` and `kind` are all `None`.
3. **Success signal**: `event_type == "payment.created"` is the only usable success marker. Inner `raw.data.status` is `"succeeded"` when present.
4. **Invoice-id reference field**: top-level `invoice_id`.
5. **All 5 `payment.created` events carry `invoice_id=None`** (LZ4-era smoke-test payloads).
6. **True backfill candidates** (successful event AND matching `db.quotes` invoice AND not already paid AND no `paid_at`): **0 rows**.
7. **Duplicates**: 5 events share `invoice_id=None` — collapse to 1 no-op group.
8. **Alt collections**: `lumino_events`, `lumino_payment_events`, `payments`, `invoice_payments`, `zapier_events` — all empty.
9. **Gate decision**: Zero true candidates today. Per spec: *"If zero → note that in the report, mark Sub-item 1 as no-op, and proceed to Sub-item 2."*
10. **Decision made**: Still shipped the idempotent script + 10-case test suite (using synthetic seed data) so the code is production-ready the moment real Lumino events start landing (or Zapier is un-parked).
11. Sample event ids: `smoke_test_evt_001`, `invoice_link_b3264b5fd6077e0b` (link event, not success).
12. Top-level event keys: `['_id', 'correlation_id', 'event_type', 'id', 'invoice_id', 'lumino_customer_ref', 'lumino_event_id', 'lumino_payment_ref', 'lumino_payment_url', 'occurred_at', 'processed', 'raw', 'received_at', 'resolution_source', 'source', 'type']`.
13. **Timestamp preference**: `occurred_at` → `received_at` → `datetime.now(utc)` fallback (safe order for earliest-of-duplicates picker).
14. No writes performed against production data — the real-run reported `scanned:0 backfilled:0` and left the DB untouched.

## Files added / changed

### Backend
- **NEW** `backend/scripts/backfill_lumino_paid_at.py` — idempotent migration with `--dry-run` flag. Exports `backfill(db, dry_run)` for in-process pytest.
- **NEW** `backend/tests/test_backfill_lumino_paid_at.py` — 10 pytest cases, all passing.
- **EDIT** `backend/routers/invoice_reconciliation.py` — optional `action` query param on the log endpoint; notes updated to reference the new backfill entry type; response gained a `filter` field (backwards compatible when unset).
- **EDIT** `backend/tests/test_invoice_collection_unification.py::test_reconciliation_log_role_guard` — assertion updated to accept either the original "Historical Lumino paid_at drift" text OR the Phase 15 `backfill_lumino_paid_at` reference (schema evolution — the note text was rewritten now that the follow-up phase has been delivered).

### Docs
- **EDIT** `/app/CHANGELOG.md` — one Phase 15 entry covering both sub-items (Added / Changed / Not touched / Sub-item 2 gate / Security).
- **NEW** `/app/memory/PHASE15_DELIVERABLES.md` (this file).

### Frontend / env
- **No changes.** Sub-item 2 STOP condition triggered (see below).

## Backfill script stdout (real DB — production data untouched)

```
=== DRY RUN ===
scanned: 0
backfilled: 0
already_paid: 0
invoice_not_found: 0
dry_run: True

=== REAL RUN ===
scanned: 0
backfilled: 0
already_paid: 0
invoice_not_found: 0
dry_run: False

=== IDEMPOTENT SECOND RUN ===
scanned: 0
backfilled: 0
already_paid: 0
invoice_not_found: 0
dry_run: False
```

## curl — reconciliation log filtered by `action=backfill_lumino_paid_at`

```
$ curl "$API/api/admin/invoice-reconciliation-log?action=backfill_lumino_paid_at&limit=5" -H "Authorization: Bearer $TOKEN"
{
    "items": [],
    "count": 0,
    "filter": {"action": "backfill_lumino_paid_at"},
    "notes": [
        "Phase 11 refactor unified db.invoices → db.quotes (doc_type=invoice).",
        "This log lists drift found during the migration script — duplicate rows present in BOTH collections at migration time.",
        "Phase 15 adds action=backfill_lumino_paid_at rows for historical Lumino paid_at drift (bugs B4/B5) surfaced via db.payment_events."
    ]
}
```

Backwards-compat check — no filter:

```
$ curl "$API/api/admin/invoice-reconciliation-log?limit=5" -H "Authorization: Bearer $TOKEN"
# count: 0, filter: {}, notes[-1]: Phase 15 adds …
```

## Sub-item 2 · STOP condition (grep proof)

```
$ grep -rn "REACT_APP_STRIPE_PUBLISHABLE_KEY\b" /app/frontend/src
frontend/src/pages/portal/PortalPaymentMethods.jsx:28:      process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY ||
frontend/src/pages/portal/PortalPaymentMethods.jsx:34:    process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY ||
frontend/src/components/customers/AdminCardCapturePanel.jsx:25:      process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY ||
frontend/src/components/customers/AdminCardCapturePanel.jsx:31:    process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY ||

4 active references remain (all in Phase 14a code that Phase 15 is
forbidden from touching). Cleanup NOT performed — spec's STOP
condition triggered.
```

`frontend/.env` line 7 (unchanged):
```
REACT_APP_STRIPE_PUBLISHABLE_KEY=pk_live_51NE9yg…RwKZ
```

Extra note flagged in the CHANGELOG: the spec's stated premise — *"Phase 14a wired publishable-key delivery through /setup-intent"* — is **not currently accurate**. `create_setup_intent` returns `{client_secret, setup_intent_id, stripe_customer_id, mode}` but no publishable key. The frontend still needs an env-based key at page load. A future phase should either (a) add publishable-key delivery to the setup-intent response, or (b) explicitly authorize editing the three Phase 14a files.

## Test counts

- **Pytest** across Phase 15 + adjacent regressions: **53 passed · 3 skipped · 0 failed** (10 new Phase 15 + 43 phase 14a/14b/11/13).
- **Vitest baseline**: **524 passed · 12 failed · 1 skipped** across 112 files. Inside the 11-14 tolerance band (previously 13 → 12 now — noise inside band, no touched files near flaking tests).
- **`/api/openapi.json`**: HTTP 200.
- **Phase 11 grep-lint**: green — `test_grep_lint_no_writes_to_db_invoices` in the new suite confirms zero writes to `db.invoices` in the backfill script.

## Design notes

### Earliest-event wins on duplicates
The `_pick_event_ts()` helper returns the best-available string in the order `occurred_at → received_at → utcnow()`. Because both timestamps in the payload are ISO-8601 strings with UTC offsets, plain string comparison correctly orders them without a full datetime parse. The reconciliation log row records the exact `source_event_id` used so an auditor can trace which of the N duplicate events supplied the `paid_at`.

### Partial-payment preservation
The script stamps `amount_paid=total` **only** when the current `amount_paid` is 0. Any invoice already carrying a partial payment (e.g., a customer credited $25 against a $100 invoice, then paid the balance externally) keeps its existing `amount_paid` value. Phase 14b's `already_paid` / `zero_balance` eligibility logic sees the correct picture after backfill.

### Defensive parsing
Real-world `db.payment_events` rows are known to sometimes carry non-dict `raw` payloads (older Zapier retries). The `_is_successful_event()` guard now falls back to `{}` when `raw` or `raw.data` isn't a dict, so a malformed row is silently ignored rather than crashing the whole backfill sweep.

### No-op-today safety
Because the current DB has zero true candidates, the real run against production writes zero rows. The 10 pytest cases all use synthetic `TEST_p15_*` seed data with an `autouse` cleanup fixture — no test data survives across runs.

## Out of scope (as specified)
- Any change to Lumino/Zapier flow itself.
- Any change to the Phase 11 reconciliation-log endpoint schema beyond the optional `action` filter.
- Any change to Phase 14a/14b Stripe code.
- Any new features.
