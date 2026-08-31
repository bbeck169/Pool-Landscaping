"""Phase F6 · Feb-2026 — diagnostic dump + operator summary tests.

Verifies:
  1. Clean state (0 dangling refs) writes NO dump file.
  2. Dirty state writes a JSON dump file whose shape matches spec.
  3. Full orphan lists are dumped (NOT the 20-row sample cap).
  4. Log-only mode (enforce=False) does NOT raise + emits the
     ``[LOG-ONLY MODE ACTIVE]`` CRITICAL.
  5. Enforce mode raises but the dump file is STILL written first.
  6. Per-tenant breakdown surfaces the loudest tenant first.
  7. Stderr line prefixed ``INTEGRITY_DUMP:`` is emitted.
  8. Dump filename is colon-free UTC ISO.
"""
from __future__ import annotations

import asyncio
import json
import logging
import pathlib

import pytest

from services.startup import integrity_check as ic


class _FakeColl:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def find(self, q=None, projection=None):
        rows = self._rows
        if q:
            rows = [r for r in rows if _match(r, q)]
        return _Cursor(rows)


class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._i]
        self._i += 1
        return row


def _match(row, q):
    for k, v in q.items():
        if k == "$or":
            if not any(_match(row, s) for s in v):
                return False
            continue
        cell = row.get(k)
        if isinstance(v, dict):
            if "$exists" in v and ((k in row) != v["$exists"]):
                return False
            continue
        if cell != v:
            return False
    return True


class _FakeDb:
    def __init__(self, *, customers=None, technicians=None, users=None,
                  crews=None, jobs=None):
        self.customers = _FakeColl(customers)
        self.technicians = _FakeColl(technicians)
        self.users = _FakeColl(users)
        self.crews = _FakeColl(crews)
        self.jobs = _FakeColl(jobs)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _seed_orphans(n_customer=0, n_technician=0, n_crew=0,
                    tenants=("t-1",)):
    """Seed N orphans of each class, spread across ``tenants``."""
    jobs = []
    for i in range(n_customer):
        jobs.append({
            "id": f"j-cust-{i}",
            "tenant_id": tenants[i % len(tenants)],
            "customer_id": f"missing-cust-{i}",
            "customer_name": "GhostCustomer",
        })
    for i in range(n_technician):
        jobs.append({
            "id": f"j-tech-{i}",
            "tenant_id": tenants[i % len(tenants)],
            "customer_id": None,  # customer intentionally absent
            "technician_id": f"missing-tech-{i}",
            "technician_name": "GhostTech",
        })
    for i in range(n_crew):
        jobs.append({
            "id": f"j-crew-{i}",
            "tenant_id": tenants[i % len(tenants)],
            "customer_id": None,
            "crew_id": f"missing-crew-{i}",
        })
    return _FakeDb(jobs=jobs)


def test_clean_state_writes_no_dump_file(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ic, "_DEFAULT_DUMP_DIR", tmp_path)
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "false")
    db = _FakeDb()   # no jobs → 0 dangling
    caplog.set_level(logging.CRITICAL)
    _run(ic.run_startup_integrity_check(db))
    dumps = list(tmp_path.glob("integrity_dump_*.json"))
    assert dumps == [], f"clean scan wrote unexpected dump(s): {dumps}"
    assert "INTEGRITY_DUMP" not in caplog.text


def test_dirty_state_writes_dump_file_with_full_lists(
        tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ic, "_DEFAULT_DUMP_DIR", tmp_path)
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "false")
    # 25 of each class — MORE than the 20-row sample cap so the
    # test proves the dump carries every row, not just samples.
    db = _seed_orphans(n_customer=25, n_technician=25, n_crew=25)
    caplog.set_level(logging.CRITICAL)
    _run(ic.run_startup_integrity_check(db))
    dumps = list(tmp_path.glob("integrity_dump_*.json"))
    assert len(dumps) == 1
    payload = json.loads(dumps[0].read_text(encoding="utf-8"))
    assert payload["totals"] == {"customer": 25, "technician": 25,
                                    "crew": 25, "total": 75}
    assert len(payload["orphans"]["customer_refs"]) == 25
    assert len(payload["orphans"]["technician_refs"]) == 25
    assert len(payload["orphans"]["crew_refs"]) == 25
    # Ordering of orphan_refs preserved from the scan cursor.
    first = payload["orphans"]["customer_refs"][0]
    assert set(first.keys()) >= {"job_id", "tenant_id", "customer_id",
                                     "customer_name_denorm"}


def test_stderr_dump_line_is_emitted(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ic, "_DEFAULT_DUMP_DIR", tmp_path)
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "false")
    db = _seed_orphans(n_customer=2)
    caplog.set_level(logging.CRITICAL,
                        logger="services.startup.integrity_check")
    _run(ic.run_startup_integrity_check(db))
    assert "INTEGRITY_DUMP:" in caplog.text
    # Extract the JSON payload from the stderr line.
    line = next(r for r in caplog.text.splitlines()
                if "INTEGRITY_DUMP:" in r)
    payload_str = line.split("INTEGRITY_DUMP:", 1)[1].strip()
    payload = json.loads(payload_str)
    assert payload["totals"]["customer"] == 2
    assert payload["enforce_mode"] is False


def test_log_only_mode_active_message_emitted(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ic, "_DEFAULT_DUMP_DIR", tmp_path)
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "false")
    db = _seed_orphans(n_customer=5)
    caplog.set_level(logging.CRITICAL)
    result = _run(ic.run_startup_integrity_check(db))
    assert result["summary"]["total_dangling_refs"] == 5
    # LOG-ONLY MODE ACTIVE marker present.
    assert "[LOG-ONLY MODE ACTIVE]" in caplog.text
    # And the runbook pointer.
    assert "DATA_INTEGRITY_RUNBOOK.md" in caplog.text


def test_enforce_mode_still_writes_dump_before_raising(
        tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ic, "_DEFAULT_DUMP_DIR", tmp_path)
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "true")
    db = _seed_orphans(n_customer=3)
    caplog.set_level(logging.CRITICAL)
    with pytest.raises(ic.IntegrityCheckFailure):
        _run(ic.run_startup_integrity_check(db))
    dumps = list(tmp_path.glob("integrity_dump_*.json"))
    assert len(dumps) == 1, "enforce=True must ALSO write the dump"
    payload = json.loads(dumps[0].read_text(encoding="utf-8"))
    assert payload["enforce_mode"] is True
    assert payload["totals"]["customer"] == 3
    # LOG-ONLY marker must NOT appear in enforce mode.
    assert "[LOG-ONLY MODE ACTIVE]" not in caplog.text


def test_tenant_breakdown_orders_by_loudest_first(
        tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ic, "_DEFAULT_DUMP_DIR", tmp_path)
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "false")
    # 10 orphans on t-loud, 2 on t-quiet.
    jobs = [
        {"id": f"j-loud-{i}", "tenant_id": "t-loud",
         "customer_id": f"missing-{i}"}
        for i in range(10)
    ] + [
        {"id": f"j-quiet-{i}", "tenant_id": "t-quiet",
         "customer_id": f"missing-q-{i}"}
        for i in range(2)
    ]
    db = _FakeDb(jobs=jobs)
    caplog.set_level(logging.CRITICAL)
    _run(ic.run_startup_integrity_check(db))
    dumps = list(tmp_path.glob("integrity_dump_*.json"))
    payload = json.loads(dumps[0].read_text(encoding="utf-8"))
    tb = payload["tenant_breakdown"]
    keys = list(tb.keys())
    assert keys[0] == "t-loud"
    assert tb["t-loud"] == 10
    assert tb["t-quiet"] == 2
    # And the operator-summary log line surfaces the loudest tenant
    # first.
    assert "Tenant t-loud" in caplog.text


def test_dump_filename_is_colon_free_and_utc(tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "_DEFAULT_DUMP_DIR", tmp_path)
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "false")
    db = _seed_orphans(n_customer=1)
    _run(ic.run_startup_integrity_check(db))
    dumps = list(tmp_path.glob("integrity_dump_*.json"))
    assert dumps
    name = dumps[0].name
    assert ":" not in name, "filename must be colon-free"
    assert name.endswith("Z.json")
    assert name.startswith("integrity_dump_")


def test_dump_write_failure_does_not_raise(monkeypatch, caplog):
    """A permission error on the dump dir must NOT brick boot.
    The scan/enforce logic keeps its behaviour; the dump degrades
    to stderr-only."""
    monkeypatch.setattr(ic, "_DEFAULT_DUMP_DIR",
                          pathlib.Path("/dev/null/nope"))
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "false")
    db = _seed_orphans(n_customer=1)
    caplog.set_level(logging.CRITICAL)
    result = _run(ic.run_startup_integrity_check(db))
    assert result["summary"]["total_dangling_refs"] == 1
    # Stderr line still emits even though file write failed.
    assert "INTEGRITY_DUMP:" in caplog.text


def test_dump_payload_has_iso_timestamp_and_enforce_mode(tmp_path):
    """Directly test the pure ``_build_dump_payload`` helper so tests
    don't have to touch disk to validate the shape."""
    report = {
        "summary": {"customer_class": 3, "technician_class": 1,
                     "crew_class": 0, "total_dangling_refs": 4},
        "_all_orphans_customer": [{"job_id": "j-1", "tenant_id": "t-1"}],
        "_all_orphans_technician": [{"job_id": "j-2", "tenant_id": "t-1"}],
        "_all_orphans_crew": [],
        "tenant_breakdown": {"t-1": 4},
    }
    payload = ic._build_dump_payload(report, enforce_mode=True)
    assert payload["enforce_mode"] is True
    assert payload["totals"]["total"] == 4
    assert payload["tenant_breakdown"] == {"t-1": 4}
    assert "T" in payload["timestamp"] and payload["timestamp"].endswith("Z")
