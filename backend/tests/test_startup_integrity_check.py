"""Feb-2026 · Phase F3 · Contract test — boot-check gate.

Locks the F3 invariant: the ``run_startup_integrity_check``
function
  * returns cleanly when 0 dangling refs exist,
  * raises ``IntegrityCheckFailure`` when dangling refs exist AND
    ``INTEGRITY_CHECK_ENFORCE`` resolves to true,
  * logs CRITICAL but does NOT raise when enforcement is off.

Detection classes: orphan customer, orphan technician, orphan crew.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

import pytest

from services.startup.integrity_check import (
    IntegrityCheckFailure,
    run_startup_integrity_check,
    scan_dangling_refs,
)


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])

    def find(self, query=None, projection=None):  # noqa: ARG002
        outer = self
        q = query or {}

        class _Cursor:
            def __init__(self):
                self._rows = [dict(r) for r in outer.rows if _match(r, q)]

            def __aiter__(self):
                self._it = iter(self._rows)
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:
                    raise StopAsyncIteration

            async def to_list(self, _n=None):
                return list(self._rows)

        return _Cursor()


def _match(row, query):
    for k, v in query.items():
        if k == "$or":
            if not any(_match(row, sub) for sub in v):
                return False
            continue
        if isinstance(v, dict) and "$exists" in v:
            if v["$exists"] != (k in row):
                return False
            continue
        if isinstance(v, dict):
            return False
        if row.get(k) != v:
            return False
    return True


class _DB:
    def __init__(self, jobs=None, customers=None, technicians=None,
                 users=None, crews=None):
        self.jobs = _Coll(jobs)
        self.customers = _Coll(customers)
        self.technicians = _Coll(technicians)
        self.users = _Coll(users)
        self.crews = _Coll(crews)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════
def test_scan_returns_zero_when_all_refs_live():
    fake = _DB(
        jobs=[{"id": "j1", "customer_id": "c1", "technician_id": "t1",
               "crew_id": "cr1", "status": "scheduled"}],
        customers=[{"id": "c1"}],
        technicians=[{"id": "t1"}],
        crews=[{"id": "cr1"}],
    )
    report = _run(scan_dangling_refs(fake))
    assert report["summary"]["total_dangling_refs"] == 0
    assert report["orphan_customer_total"] == 0
    assert report["orphan_technician_total"] == 0
    assert report["orphan_crew_total"] == 0


def test_scan_flags_orphan_customer():
    fake = _DB(
        jobs=[{"id": "j1", "customer_id": "GHOST",
               "customer_name": "TestX", "status": "scheduled"}],
        customers=[],
    )
    report = _run(scan_dangling_refs(fake))
    assert report["orphan_customer_total"] == 1
    assert report["orphan_customer"][0]["customer_id"] == "GHOST"


def test_scan_flags_orphan_technician():
    fake = _DB(
        jobs=[{"id": "j1", "technician_id": "GHOST",
               "technician_name": "Sara", "status": "pending"}],
    )
    report = _run(scan_dangling_refs(fake))
    assert report["orphan_technician_total"] == 1
    assert report["orphan_technician"][0]["technician_id"] == "GHOST"


def test_scan_accepts_tech_via_users_or_technicians():
    """Same id-space semantics as
    ``services.authz.is_tech_authorized_on_job``: a technician_id
    that resolves via db.users (role=technician) is NOT dangling
    even if db.technicians has no matching row."""
    fake = _DB(
        jobs=[{"id": "j1", "technician_id": "user-b",
               "status": "scheduled"}],
        users=[{"id": "user-b", "role": "technician"}],
    )
    report = _run(scan_dangling_refs(fake))
    assert report["orphan_technician_total"] == 0


def test_scan_flags_orphan_crew():
    fake = _DB(
        jobs=[{"id": "j1", "crew_id": "GHOST", "status": "scheduled"}],
    )
    report = _run(scan_dangling_refs(fake))
    assert report["orphan_crew_total"] == 1


def test_scan_ignores_soft_deleted_jobs():
    """A soft-deleted job with a dangling ref does NOT count —
    F2 deliberately moves orphans there."""
    fake = _DB(
        jobs=[{"id": "j1", "customer_id": "GHOST",
               "status": "deleted", "deleted_at": "2026-08-01"}],
    )
    report = _run(scan_dangling_refs(fake))
    assert report["summary"]["total_dangling_refs"] == 0


def test_run_check_clean_state_returns_without_raising():
    """Zero dangling refs → returns the report cleanly regardless
    of the enforcement flag."""
    fake = _DB(jobs=[])
    # Enforcement on OR off — clean state never raises.
    result_a = _run(run_startup_integrity_check(fake))
    assert result_a["summary"]["total_dangling_refs"] == 0
    result_b = _run(run_startup_integrity_check(fake))
    assert result_b["summary"]["total_dangling_refs"] == 0


def test_run_check_raises_when_enforce_true(monkeypatch, caplog):
    """Dangling refs on an ENFORCED class (customer or crew) +
    enforcement on → IntegrityCheckFailure with the report
    attached."""
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "true")

    fake = _DB(
        jobs=[{"id": "j1", "customer_id": "GHOST",
               "customer_name": "X", "status": "scheduled"}],
    )
    with caplog.at_level(logging.CRITICAL,
                          logger="services.startup.integrity_check"):
        with pytest.raises(IntegrityCheckFailure) as exc:
            _run(run_startup_integrity_check(fake))
    assert exc.value.report["summary"]["total_dangling_refs"] == 1
    # And a CRITICAL log line was emitted with the actionable path.
    critical_msgs = [r for r in caplog.records
                     if r.levelno == logging.CRITICAL]
    assert critical_msgs
    assert any("data-repair" in r.getMessage() for r in critical_msgs)


def test_run_check_technician_class_alone_does_not_fail_fast(
    monkeypatch, caplog,
):
    """P0 boot-brick guard — an admin promoting a tech to admin
    silently removes their id from the live tech space. That's a
    legitimate action, not corruption. The technician_ref class
    logs CRITICAL but must NOT raise, even when enforcement is on.
    """
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "true")

    fake = _DB(
        jobs=[{"id": "j1", "technician_id": "PROMOTED-TECH",
               "technician_name": "Ex-Tech Now Admin",
               "status": "pending"}],
    )
    with caplog.at_level(logging.CRITICAL,
                          logger="services.startup.integrity_check"):
        # MUST NOT raise — technician-only orphans don't brick boot.
        report = _run(run_startup_integrity_check(fake))
    assert report["summary"]["technician_class"] == 1
    assert report["summary"]["customer_class"] == 0
    assert report["summary"]["crew_class"] == 0
    # But the operator DID see the CRITICAL log.
    assert [r for r in caplog.records if r.levelno == logging.CRITICAL]


def test_run_check_crew_class_alone_does_fail_fast(monkeypatch):
    """Crew orphans DO brick boot (F3 hard-delete block now
    prevents new ones; pre-existing state must be repaired)."""
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "true")

    fake = _DB(
        jobs=[{"id": "j1", "crew_id": "GHOST-CREW",
               "status": "scheduled"}],
    )
    with pytest.raises(IntegrityCheckFailure):
        _run(run_startup_integrity_check(fake))


def test_run_check_mixed_classes_fail_fast_on_customer_or_crew(monkeypatch):
    """When BOTH technician AND customer refs are dangling, the
    customer class alone drives the fail-fast."""
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "true")

    fake = _DB(
        jobs=[
            {"id": "j1", "customer_id": "GHOST-CUST", "status": "scheduled"},
            {"id": "j2", "technician_id": "GHOST-TECH", "status": "pending"},
        ],
    )
    with pytest.raises(IntegrityCheckFailure) as exc:
        _run(run_startup_integrity_check(fake))
    # Report still surfaces BOTH classes.
    assert exc.value.report["summary"]["customer_class"] == 1
    assert exc.value.report["summary"]["technician_class"] == 1


def test_run_check_logs_but_does_not_raise_when_enforce_false(
    monkeypatch, caplog,
):
    """Dangling refs + enforcement off → CRITICAL log only."""
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "false")

    fake = _DB(
        jobs=[{"id": "j1", "customer_id": "GHOST",
               "customer_name": "X", "status": "scheduled"}],
    )
    with caplog.at_level(logging.CRITICAL,
                          logger="services.startup.integrity_check"):
        # Must NOT raise.
        report = _run(run_startup_integrity_check(fake))
    assert report["summary"]["total_dangling_refs"] == 1
    critical_msgs = [r for r in caplog.records
                     if r.levelno == logging.CRITICAL]
    assert critical_msgs


def test_enforce_flag_defaults_to_production_only(monkeypatch):
    """Default enforcement mirrors ``APP_ENV=production`` when
    ``INTEGRITY_CHECK_ENFORCE`` is unset. Blocks fail-fast from
    firing on every dev-machine reload."""
    from services.startup.integrity_check import _enforce_flag_from_env

    monkeypatch.delenv("INTEGRITY_CHECK_ENFORCE", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    assert _enforce_flag_from_env() is True

    monkeypatch.setenv("APP_ENV", "preview")
    assert _enforce_flag_from_env() is False

    monkeypatch.setenv("APP_ENV", "development")
    assert _enforce_flag_from_env() is False


def test_explicit_env_override_wins(monkeypatch):
    """Explicit ``INTEGRITY_CHECK_ENFORCE`` beats the APP_ENV
    default — matches the doc contract."""
    from services.startup.integrity_check import _enforce_flag_from_env

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "false")
    assert _enforce_flag_from_env() is False

    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "true")
    assert _enforce_flag_from_env() is True
