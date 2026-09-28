"""HARD-DELETE · Sub-phase HD-A · Feb 2026.

Two-step delete tool with a Trash flow and an immutable tombstone
audit collection.

Design overview
---------------
* Users hit ``POST /api/hard-delete/{entity_type}/{id}/soft`` first.
  The doc gets stamped with ``deleted_at`` + ``deleted_by_user_id``
  + a fresh ``cascade_batch_id`` so the whole family (children,
  grand-children) restores atomically as a unit.
* ``POST /api/hard-delete/{entity_type}/{id}/restore`` clears those
  stamps for the entire batch — reversing every side effect of the
  original soft-delete.
* ``POST /api/hard-delete/{entity_type}/{id}/purge`` writes a
  snapshot into ``db.hard_delete_tombstones`` (immutable) THEN
  hard-deletes the doc + its children. Purge is super-admin only.
* The nightly worker ``services.hard_delete.nightly_purge`` walks
  every eligible collection and purges rows whose ``deleted_at``
  is older than ``HARD_DELETE_PURGE_AFTER_DAYS`` (default: 30).

The design is INTENTIONALLY parallel to the pre-existing
per-entity hard-delete surfaces (``DELETE /customers/{cid}?mode=hard``
etc.). Those legacy surfaces stay for backward-compat; new admin
UX + audit compliance flows through ``/api/hard-delete/*``.
"""
