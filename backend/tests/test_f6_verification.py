"""Phase F6 · INDEPENDENT VERIFICATION suite (T1 testing agent).

Covers F6-A .. F6-E from the review request.  Reuses the fake-Motor
doubles from ``tests.test_integrity_check_diagnostic_dump`` — existing
test files are NOT modified.

  F6-A  dump JSON schema (exact top-level keys, sub-shapes)
  F6-B  single-line stderr ``INTEGRITY_DUMP:`` log-shipper contract
  F6-C  dump-file write (colon-free name, indent=2, full lists) +
        no dump on a clean scan
  F6-D  reminder cadence, self-termination, exception survival,
        cancellation
  F6-E  tenant isolation of dump content
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

import pytest

from services.startup import integrity_check as ic
from tests.test_integrity_check_diagnostic_dump import (  # noqa: F401
    _FakeColl, _Cursor, _FakeDb, _seed_orphans,
)

LOGGER_NAME = "services.startup.integrity_check"


def _run(coro):
    return asyncio.run(coro)


def _multi_tenant_db():
    """tenant-a=5 (3 cust + 1 tech + 1 crew), tenant-b=2, tenant-c=1."""
    jobs = []
    for i in range(3):
        jobs.append({"id": f"a-cust-{i}", "tenant_id": "tenant-a",
                     "customer_id": f"ghost-cust-a{i}",
                     "customer_name": "GhostA"})
    jobs.append({"id": "a-tech-0", "tenant_id": "tenant-a",
                 "customer_id": None, "technician_id": "ghost-tech-a0",
                 "technician_name": "GhostTechA"})
    jobs.append({"id": "a-crew-0", "tenant_id": "tenant-a",
                 "customer_id": None, "crew_id": "ghost-crew-a0"})
    for i in range(2):
        jobs.append({"id": f"b-cust-{i}", "tenant_id": "tenant-b",
                     "customer_id": f"ghost-cust-b{i}",
                     "customer_name": "GhostB"})
    jobs.append({"id": "c-crew-0", "tenant_id": "tenant-c",
                 "customer_id": None, "crew_id": "ghost-crew-c0"})
    return _FakeDb(jobs=jobs)


# ───────────────────────────── F6-A ─────────────────────────────
def test_f6a_dump_json_schema_exact(tmp_path, caplog):
    db = _multi_tenant_db()
    report = _run(ic.scan_dangling_refs(db))
    caplog.set_level(logging.CRITICAL, logger=LOGGER_NAME)

    path = ic.write_diagnostic_dump(report, enforce_mode=False,
                                    dump_dir=tmp_path)
    assert path is not None, "write_diagnostic_dump returned None"
    payload = json.loads(open(path, encoding="utf-8").read())

    assert set(payload.keys()) == {
        "timestamp", "enforce_mode", "totals", "tenant_breakdown",
        "orphans",
    }, f"unexpected top-level keys: {sorted(payload.keys())}"
    assert set(payload["totals"].keys()) == {
        "customer", "technician", "crew", "total"}
    assert set(payload["orphans"].keys()) == {
        "customer_refs", "technician_refs", "crew_refs"}
    for key in ("customer_refs", "technician_refs", "crew_refs"):
        assert isinstance(payload["orphans"][key], list)

    assert payload["enforce_mode"] is False
    assert isinstance(payload["enforce_mode"], bool)
    assert payload["totals"] == {"customer": 5, "technician": 1,
                                 "crew": 2, "total": 8}
    ts = payload["timestamp"]
    assert isinstance(ts, str) and ts.endswith("Z")
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", ts,
    ), f"timestamp not UTC ISO-8601: {ts}"

    # enforce_mode=True must mirror the argument.
    payload_true = ic._build_dump_payload(report, enforce_mode=True)
    assert payload_true["enforce_mode"] is True


# ───────────────────────────── F6-B ─────────────────────────────
def test_f6b_stderr_integrity_dump_single_line(tmp_path, caplog):
    db = _multi_tenant_db()
    report = _run(ic.scan_dangling_refs(db))
    caplog.set_level(logging.CRITICAL, logger=LOGGER_NAME)
    caplog.clear()

    ic.write_diagnostic_dump(report, enforce_mode=False,
                            dump_dir=tmp_path)

    dump_records = [
        r for r in caplog.records
        if r.name == LOGGER_NAME
        and r.getMessage().startswith("INTEGRITY_DUMP: ")
    ]
    assert len(dump_records) == 1, (
        f"expected exactly 1 INTEGRITY_DUMP critical, got "
        f"{len(dump_records)}"
    )
    rec = dump_records[0]
    assert rec.levelno == logging.CRITICAL
    json_part = rec.getMessage().split("INTEGRITY_DUMP: ", 1)[1]
    assert "\n" not in json_part, "JSON portion must be single-line"
    assert "\n" not in rec.getMessage()
    parsed = json.loads(json_part)
    assert isinstance(parsed, dict)
    assert set(parsed.keys()) == {
        "timestamp", "enforce_mode", "totals", "tenant_breakdown",
        "orphans"}
    assert set(parsed["totals"].keys()) == {
        "customer", "technician", "crew", "total"}
    assert set(parsed["orphans"].keys()) == {
        "customer_refs", "technician_refs", "crew_refs"}
    assert parsed["totals"]["total"] == 8


# ───────────────────────────── F6-C ─────────────────────────────
def test_f6c_dump_file_write_full_lists_and_naming(tmp_path):
    db = _seed_orphans(n_customer=26, n_technician=27, n_crew=28)
    report = _run(ic.scan_dangling_refs(db))
    path = ic.write_diagnostic_dump(report, enforce_mode=False,
                                    dump_dir=tmp_path)
    assert path is not None
    files = list(tmp_path.glob("integrity_dump_*.json"))
    assert len(files) == 1
    name = files[0].name
    assert ":" not in name, "colons must be dashes for shell safety"
    assert re.match(
        r"^integrity_dump_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z\.json$",
        name,
    ), f"bad dump filename: {name}"

    raw = files[0].read_text(encoding="utf-8")
    assert "\n  " in raw, "dump file must be pretty-printed (indent=2)"
    payload = json.loads(raw)
    assert json.dumps(payload, indent=2, sort_keys=True,
                      default=str) == raw
    assert set(payload.keys()) == {
        "timestamp", "enforce_mode", "totals", "tenant_breakdown",
        "orphans"}
    assert payload["totals"] == {"customer": 26, "technician": 27,
                                 "crew": 28, "total": 81}
    assert len(payload["orphans"]["customer_refs"]) == 26
    assert len(payload["orphans"]["technician_refs"]) == 27
    assert len(payload["orphans"]["crew_refs"]) == 28


def test_f6c_clean_scan_never_calls_write_dump(tmp_path, monkeypatch):
    calls = []

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    monkeypatch.setattr(ic, "_DEFAULT_DUMP_DIR", tmp_path)
    monkeypatch.setattr(ic, "write_diagnostic_dump", _spy)
    monkeypatch.setenv("INTEGRITY_CHECK_ENFORCE", "false")

    report = _run(ic.run_startup_integrity_check(_FakeDb()))
    assert report["summary"]["total_dangling_refs"] == 0
    assert calls == [], "write_diagnostic_dump called on a clean scan"
    assert list(tmp_path.glob("integrity_dump_*.json")) == []


# ───────────────────────────── F6-D ─────────────────────────────
def test_f6d_reminder_cadence_and_cancellation(caplog):
    db = _seed_orphans(n_customer=3)
    caplog.set_level(logging.CRITICAL, logger=LOGGER_NAME)
    caplog.clear()
    interval = 0.05

    async def _drive():
        task = ic.start_log_only_reminder_task(db, interval_sec=interval)
        assert isinstance(task, asyncio.Task)
        await asyncio.sleep(interval * 2.5)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled() or task.done()
        return task

    task = _run(_drive())
    assert task.done()
    ticks = [r for r in caplog.records
             if "[LOG-ONLY REMINDER" in r.getMessage()]
    assert len(ticks) >= 2, (
        f"expected >=2 reminder ticks within {interval * 2.5}s, "
        f"got {len(ticks)}"
    )


def test_f6d_reminder_selfterminates_when_clean(caplog):
    db = _seed_orphans(n_customer=2)
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    caplog.clear()

    async def _drive():
        task = asyncio.create_task(ic._log_only_reminder_loop(db, 0.05))
        await asyncio.sleep(0.12)          # >=1 dirty tick
        db.jobs._rows = []                 # operator repaired state
        await asyncio.sleep(0.25)          # next tick sees clean
        assert task.done(), "loop did not exit after state went clean"
        await task
        return task

    _run(_drive())
    assert any("[LOG-ONLY REMINDER" in r.getMessage()
               and r.levelno == logging.CRITICAL
               for r in caplog.records), "no dirty tick fired"
    clean = [r for r in caplog.records
             if "state is now clean" in r.getMessage()]
    assert clean, "missing 'state is now clean' log"
    assert clean[0].levelno == logging.INFO


def test_f6d_reminder_survives_tick_exception(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    caplog.clear()
    state = {"n": 0}

    async def _flaky_scan(db):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient db failure")
        return {"summary": {"total_dangling_refs": 0},
                "tenant_breakdown": {}}

    monkeypatch.setattr(ic, "scan_dangling_refs", _flaky_scan)

    async def _drive():
        task = asyncio.create_task(
            ic._log_only_reminder_loop(object(), 0.05))
        await asyncio.sleep(0.4)
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            pytest.fail("loop did not reach the clean-exit tick")
        await task

    _run(_drive())
    assert state["n"] >= 2, "loop died after the failing tick"
    assert any("reminder tick crashed" in r.getMessage()
               for r in caplog.records)
    assert any("state is now clean" in r.getMessage()
               for r in caplog.records)


# ───────────────────────────── F6-E ─────────────────────────────
def test_f6e_tenant_isolation_in_dump(tmp_path):
    db = _multi_tenant_db()
    report = _run(ic.scan_dangling_refs(db))

    tb = report["tenant_breakdown"]
    assert tb == {"tenant-a": 5, "tenant-b": 2, "tenant-c": 1}
    assert list(tb.keys()) == ["tenant-a", "tenant-b", "tenant-c"], \
        "tenant_breakdown must be sorted DESC by count"

    path = ic.write_diagnostic_dump(report, enforce_mode=False,
                                    dump_dir=tmp_path)
    payload = json.loads(open(path, encoding="utf-8").read())

    grouped: dict = {}
    for key in ("customer_refs", "technician_refs", "crew_refs"):
        for row in payload["orphans"][key]:
            assert "tenant_id" in row, f"orphan row missing tenant_id: {row}"
            grouped[row["tenant_id"]] = grouped.get(row["tenant_id"], 0) + 1
    assert grouped == tb, (
        f"dump orphan tenant grouping {grouped} != breakdown {tb}"
    )

    by_class = ic._tenant_class_breakdown(report, "tenant-a")
    assert by_class == {"customer": 3, "technician": 1, "crew": 1}
    assert sum(by_class.values()) == 5

    # No cross-tenant leakage: every tenant-a orphan job id starts 'a-'.
    for key in ("customer_refs", "technician_refs", "crew_refs"):
        for row in payload["orphans"][key]:
            prefix = {"tenant-a": "a-", "tenant-b": "b-",
                      "tenant-c": "c-"}[row["tenant_id"]]
            assert row["job_id"].startswith(prefix), (
                f"orphan {row} attributed to wrong tenant"
            )
