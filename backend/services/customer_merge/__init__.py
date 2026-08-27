"""Feb 2026 · Customer Merge · Phase 1 backend engine.

Sub-modules:
    * :mod:`detection` — duplicate candidate discovery.
    * :mod:`executor`  — merge write-path (newest-wins reconciliation
      + related-record FK rewire).
    * :mod:`audit`     — ``customer_merge_audit`` collection writer.

Phase 1 ships the manual path + detection engine. Phase 3 wires the
nightly cron + boot cleanup. Phase 2 ships the frontend UI.
"""
