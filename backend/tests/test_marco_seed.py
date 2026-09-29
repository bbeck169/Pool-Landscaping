"""Feb-2026 · MARCO orchestrator seed · tests.

Locks the Sub-phase A contracts for the additive MARCO rebrand
(Option Z · Hybrid):

  1. Static shape — MARCO exists in ``DEFAULT_EMPLOYEES`` exactly
     once, with key=``marco_executive``, orchestrator=True,
     audience=``admin``, non-empty avatar_url + system_prompt.
  2. Static shape — every OTHER default persona is either missing
     the ``orchestrator`` field or has it set to ``False``.  No
     accidental co-orchestrators.
  3. Static shape — the BRIAN acronym expansion + specialist
     roster hint text are present in MARCO's system_prompt so the
     LLM has the delegation vocabulary.
  4. Guard rail source-lint — ``patch_employee`` refuses an
     orchestrator=True flip for non-super_admin callers.
  5. Migration idempotency — sentinel-gated ``run(db)`` short-
     circuits on second call.
  6. Migration backfill — first run stamps missing
     ``orchestrator`` fields on legacy ai_employees rows.
  7. Migration MARCO repair — a legacy MARCO row with
     ``orchestrator=False`` is repaired to ``True``.
  8. Seed idempotency — running ``seed_ai_employees_for_tenant``
     twice against a MagicMock DB yields one MARCO insert only.

Loop / DB hygiene
─────────────────
Tests 1-4 are pure source-lints.  Tests 5-8 use ``MagicMock`` +
``AsyncMock`` in the same style as
``test_phase50_ai_activation.py`` — no live Mongo.  Zero cross-
loop concerns; runs cleanly in any pytest ordering.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from tests._asyncio_loop_isolation import make_isolated_loop

# Feb-2026 · Test Hygiene Phase 2 — isolated event loop so
# cross-module ``asyncio.get_event_loop()`` poisoning from unrelated
# tests cannot break this seed under ``pytest -k``.  This module
# only uses MagicMock DBs, so we don't need the ``bind_config_db``
# fixture — the ``_run`` helper here just drives coroutines against
# the isolated loop.
_LOOP, _run = make_isolated_loop()


# ═══════════════════════════════════════════════════════════════════
# 1) MARCO exists in DEFAULT_EMPLOYEES exactly once with the right
#    posture (key, orchestrator, audience, avatar_url, prompt).
# ═══════════════════════════════════════════════════════════════════
def test_marco_in_default_employees_with_orchestrator_true():
    from routers.ai_employees import DEFAULT_EMPLOYEES

    marcos = [e for e in DEFAULT_EMPLOYEES
                if e.get("key") == "marco_executive"]
    assert len(marcos) == 1, (
        f"expected exactly one MARCO entry in DEFAULT_EMPLOYEES,"
        f" got {len(marcos)}"
    )
    m = marcos[0]
    assert m.get("orchestrator") is True, (
        "MARCO must ship with orchestrator=True — the delegate_task"
        " guard in Sub-phase B relies on this seed posture"
    )
    assert m.get("audience") == "admin", (
        "MARCO is an admin-audience persona"
    )
    assert m.get("name") == "MARCO: Executive Assistant AI"
    assert isinstance(m.get("system_prompt"), str) and m[
        "system_prompt"
    ].strip(), "MARCO system_prompt must be a non-empty string"
    assert m.get("avatar_url"), (
        "MARCO must ship with a portrait URL — the admin dock"
        " renders the avatar in the employees roster"
    )


# ═══════════════════════════════════════════════════════════════════
# 2) MARCO is the ONLY orchestrator in the seed.  Every other
#    persona is either omitting the flag or shipping ``False``.
# ═══════════════════════════════════════════════════════════════════
def test_marco_is_sole_orchestrator_in_default_seed():
    from routers.ai_employees import DEFAULT_EMPLOYEES

    orchestrators = [
        e for e in DEFAULT_EMPLOYEES if e.get("orchestrator") is True
    ]
    assert len(orchestrators) == 1
    assert orchestrators[0]["key"] == "marco_executive"

    # Every other persona is either False OR omits the field —
    # both are treated as ``False`` by the seed's
    # ``bool(e.get("orchestrator", False))`` coercion.
    for e in DEFAULT_EMPLOYEES:
        if e["key"] == "marco_executive":
            continue
        flag = e.get("orchestrator")
        assert flag in (False, None), (
            f"persona {e['key']!r} ships with"
            f" orchestrator={flag!r} — only MARCO may carry"
            f" orchestrator=True"
        )


# ═══════════════════════════════════════════════════════════════════
# 3) System prompt contains the BRIAN charter expansion + the
#    specialist roster hints MARCO uses to route delegations.
# ═══════════════════════════════════════════════════════════════════
def test_marco_system_prompt_ships_brian_charter_and_roster():
    from routers.ai_employees import DEFAULT_EMPLOYEES

    m = next(e for e in DEFAULT_EMPLOYEES
              if e["key"] == "marco_executive")
    prompt = m["system_prompt"]

    # BRIAN charter expansion — the four significant words are
    # asserted individually so a future prompt reshuffle that
    # rearranges the wording still passes as long as the concept
    # ships.
    for token in ("Business Response", "Intelligent",
                    "Appointment", "Navigation"):
        assert token in prompt, (
            f"MARCO system_prompt missing BRIAN charter token"
            f" {token!r}"
        )

    # Roster hints — MARCO must know the names of the specialists
    # it can delegate to.  A subset check keeps this future-proof
    # against roster expansions.
    for specialist in ("Casey", "Emmie", "Buddy", "Vizzy", "Dexter",
                         "Soshie", "Scouty", "Commet"):
        assert specialist in prompt, (
            f"MARCO system_prompt missing specialist name"
            f" {specialist!r} — needed for delegate_task routing"
        )

    # Delegation vocabulary — the prompt must mention the tool
    # name so the LLM knows to call it (and NOT to attempt the
    # specialist's work directly).
    assert "delegate_task" in prompt


# ═══════════════════════════════════════════════════════════════════
# 4) patch_employee guard-rail source-lint — flipping to
#    orchestrator=True is super_admin-only.
# ═══════════════════════════════════════════════════════════════════
def test_patch_employee_gates_orchestrator_true_flip_to_super_admin():
    from routers import ai_employees

    src = inspect.getsource(ai_employees.patch_employee)
    # The exact guard shape: check that the handler compares
    # ``updates.get("orchestrator") is True`` against a
    # super_admin role gate.  Loose lint — accepts stylistic
    # variation so long as both anchors are present.
    assert 'updates.get("orchestrator")' in src, (
        "patch_employee must inspect the orchestrator key on the"
        " update payload"
    )
    assert 'super_admin' in src, (
        "patch_employee must reference super_admin in the guard"
    )
    # And the EmployeePatch model must expose the field so a
    # patch attempt is even possible for super_admin.
    patch_src = inspect.getsource(ai_employees.EmployeePatch)
    assert "orchestrator" in patch_src, (
        "EmployeePatch must declare an orchestrator field"
    )


# ═══════════════════════════════════════════════════════════════════
# 5) Migration idempotency — sentinel short-circuit.
# ═══════════════════════════════════════════════════════════════════
def test_marco_migration_short_circuits_when_sentinel_exists():
    from migrations.marco_orchestrator_seed_v1 import run, MIGRATION_KEY

    migration_status = MagicMock()
    migration_status.find_one = AsyncMock(return_value={
        "key": MIGRATION_KEY,
        "completed_at": "2026-02-13T00:00:00+00:00",
    })
    ai_employees = MagicMock()
    tenants = MagicMock()

    db = MagicMock(
        migration_status=migration_status,
        ai_employees=ai_employees,
        tenants=tenants,
    )

    res = _run(run(db))
    assert res == {
        "ok": True, "skipped": True, "reason": "already_ran",
    }
    # No downstream reads / writes happened.
    tenants.find.assert_not_called()
    ai_employees.update_many.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# 6) Migration backfill — first run stamps missing orchestrator on
#    every legacy row + records a completion sentinel.
# ═══════════════════════════════════════════════════════════════════
def test_marco_migration_backfills_orchestrator_on_legacy_rows(
    monkeypatch,
):
    from migrations import marco_orchestrator_seed_v1 as mig

    # No sentinel yet.
    migration_status = MagicMock()
    migration_status.find_one = AsyncMock(return_value=None)
    migration_status.update_one = AsyncMock()

    # Tenants cursor — one tenant.
    class _Cursor:
        def __init__(self, rows):
            self._rows = rows
            self._i = 0
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self._i >= len(self._rows):
                raise StopAsyncIteration
            row = self._rows[self._i]
            self._i += 1
            return row

    tenants = MagicMock()
    tenants.find = MagicMock(
        return_value=_Cursor([{"id": "t-1"}]),
    )

    # ai_employees.update_many for the backfill passes.
    ai_employees = MagicMock()
    # find_one for the "MARCO already exists?" pre/post snapshots.
    ai_employees.find_one = AsyncMock(side_effect=[
        None,                          # pre-seed snapshot for t-1
        {"id": "marco-row-t1"},        # post-seed snapshot for t-1
    ])
    ai_employees.update_many = AsyncMock(
        side_effect=[
            SimpleNamespace(modified_count=7),   # orchestrator field add
            SimpleNamespace(modified_count=0),   # MARCO repair no-op
        ],
    )

    db = MagicMock(
        migration_status=migration_status,
        ai_employees=ai_employees,
        tenants=tenants,
    )

    # Stub the seed function so we don't need a live import chain.
    async def _fake_seed(_tid):
        return 1
    monkeypatch.setattr(
        "routers.ai_employees.seed_ai_employees_for_tenant",
        _fake_seed,
    )

    res = _run(mig.run(db))

    assert res["ok"] is True
    assert res["skipped"] is False
    assert res["tenants_scanned"] == 1
    assert res["marco_inserted"] == 1
    assert res["orchestrator_field_added"] == 7
    assert res["marco_orchestrator_repaired"] == 0

    # Sentinel stamped.
    migration_status.update_one.assert_awaited_once()
    _args, _kwargs = migration_status.update_one.await_args
    assert _args[0] == {"key": mig.MIGRATION_KEY}


# ═══════════════════════════════════════════════════════════════════
# 7) Migration MARCO repair — legacy MARCO row with
#    orchestrator=False is repaired to True.
# ═══════════════════════════════════════════════════════════════════
def test_marco_migration_repairs_legacy_marco_orchestrator_false(
    monkeypatch,
):
    from migrations import marco_orchestrator_seed_v1 as mig

    migration_status = MagicMock()
    migration_status.find_one = AsyncMock(return_value=None)
    migration_status.update_one = AsyncMock()

    class _EmptyCursor:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration

    tenants = MagicMock()
    tenants.find = MagicMock(return_value=_EmptyCursor())

    ai_employees = MagicMock()
    ai_employees.find_one = AsyncMock(return_value=None)
    ai_employees.update_many = AsyncMock(
        side_effect=[
            SimpleNamespace(modified_count=0),   # legacy backfill
            SimpleNamespace(modified_count=2),   # MARCO repair — 2 rows
        ],
    )

    db = MagicMock(
        migration_status=migration_status,
        ai_employees=ai_employees,
        tenants=tenants,
    )

    async def _fake_seed(_tid):
        return 0
    monkeypatch.setattr(
        "routers.ai_employees.seed_ai_employees_for_tenant",
        _fake_seed,
    )

    res = _run(mig.run(db))

    assert res["marco_orchestrator_repaired"] == 2

    # The 2nd update_many call targets legacy MARCO rows —
    # verify the filter shape locks the key + the "False or None"
    # $or clause.
    second_call_filter = (
        ai_employees.update_many.await_args_list[1].args[0]
    )
    assert second_call_filter["key"] == "marco_executive"
    assert "$or" in second_call_filter


# ═══════════════════════════════════════════════════════════════════
# 8) Seed idempotency — running seed_ai_employees_for_tenant twice
#    inserts MARCO exactly once (MagicMock-simulated DB).
# ═══════════════════════════════════════════════════════════════════
def test_seed_ai_employees_for_tenant_idempotent_for_marco():
    """Idempotency lock — the seed function's ``if exists: continue``
    branch must be hit for MARCO on the second run.  Uses a
    MagicMock DB that returns the inserted-doc snapshot on the
    second ``find_one`` so the guard fires.
    """
    from routers import ai_employees as mod

    # State machine — first find_one for each key returns None
    # (row missing), second call returns the doc snapshot.
    inserted: dict = {}

    async def _find_one(query, _projection=None):
        key = query.get("key")
        row = inserted.get(key)
        # Return a shape the seed inspects (id + audience +
        # read_access_scope + orchestrator).
        if row is None:
            return None
        return dict(row)

    async def _insert_one(doc):
        # Cache by key so the second find_one hits it.
        inserted[doc["key"]] = doc
        return SimpleNamespace(inserted_id="mock-id")

    async def _update_one(_q, _u):
        # Legacy-row backfills — no-op for this test since we
        # only exercise the fresh insert + hit-existing path.
        return SimpleNamespace(modified_count=0)

    fake_db = MagicMock()
    fake_db.ai_employees.find_one = _find_one
    fake_db.ai_employees.insert_one = _insert_one
    fake_db.ai_employees.update_one = _update_one

    # Rebind the module-level ``db`` to our fake for the duration.
    original_db = mod.db
    mod.db = fake_db
    try:
        n1 = _run(
            mod.seed_ai_employees_for_tenant("t-idem-1"),
        )
        n2 = _run(
            mod.seed_ai_employees_for_tenant("t-idem-1"),
        )
    finally:
        mod.db = original_db

    # First run inserts every DEFAULT_EMPLOYEE (>= 11 including
    # MARCO).  Second run inserts zero.
    assert n1 >= 11, f"expected >=11 seeds on first run, got {n1}"
    assert n2 == 0, (
        f"seed_ai_employees_for_tenant not idempotent — second run"
        f" inserted {n2} rows"
    )
    # MARCO ships exactly once with orchestrator=True.
    marco_row = inserted.get("marco_executive")
    assert marco_row is not None
    assert marco_row.get("orchestrator") is True
    assert marco_row.get("audience") == "admin"
