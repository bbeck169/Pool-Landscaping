"""Feb 2026 · Customer Merge · Phase 1 backend engine.

**SUPERSEDED (Feb-2026)** — this module and its five live
endpoints are replaced by the greenfield merge in
:mod:`services.customers.merge` + the new
``POST /api/customers/{winner_id}/merge-from/{loser_id}``
endpoint.  The two surfaces differ on:

  * fuzzy algorithm (Jaro-Winkler ≥ 0.92 vs Levenshtein ≤ 2 /
    substring from the Feb-2026 PDF-import ladder);
  * field reconciliation (``newest_wins`` auto-pick vs
    admin-pick per field);
  * child-record rewire breadth (6 vs 12 collections);
  * pre-flight (none vs 24h recurring block + Stripe
    availability check);
  * audit retention (none vs 90-day ``customer_merge_audit``
    collection with explicit rollback endpoint).

This module stays functional for one release so the existing
FE consumers (``MergeCustomersModal.jsx``,
``CustomerMergeWizard.jsx``, ``CustomersList.jsx``
merge-candidates chip) keep working while the new UI lands.
Decommission tracked by **TD-36** + detector convergence by
**TD-37** in ``memory/TECH_DEBT.md``.

Sub-modules:
    * :mod:`detection` — duplicate candidate discovery.
    * :mod:`executor`  — merge write-path (newest-wins reconciliation
      + related-record FK rewire).
    * :mod:`audit`     — ``customer_merge_audit`` collection writer.

Phase 1 ships the manual path + detection engine. Phase 3 wires the
nightly cron + boot cleanup. Phase 2 ships the frontend UI.
"""
