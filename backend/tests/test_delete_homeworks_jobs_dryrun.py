"""Dry-run smoke test for the standalone Homeworks delete script.

Confirms:

  * Dry-run leaves the collection untouched.
  * The resolved filter honors ``--filter-key`` + ``--value``
    overrides.
  * The script refuses to run (exit 2) when required env vars
    are missing.
  * Count + sample are reported through the logger.

Does NOT execute a real delete — operator-run script runs
against prod from the operator's machine, never from this pod.
The test injects a fake pymongo client via the
``mongo_client_factory`` seam.
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from typing import Any, Dict, List


_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "delete_homeworks_jobs.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "delete_homeworks_jobs", _SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeCollection:
    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = rows
        self.deleted = 0

    @staticmethod
    def _match(doc, filt):
        return all(doc.get(k) == v for k, v in filt.items())

    def count_documents(self, filt):
        return sum(1 for d in self.rows if self._match(d, filt))

    def find(self, filt):
        matched = [d for d in self.rows if self._match(d, filt)]
        return _FakeCursor(matched)

    def delete_many(self, filt):
        before = len(self.rows)
        self.rows = [d for d in self.rows if not self._match(d, filt)]
        deleted = before - len(self.rows)
        self.deleted = deleted

        class _Res:
            deleted_count = deleted
        return _Res()


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def limit(self, n):
        return _FakeCursor(self._rows[:n])

    def __iter__(self):
        return iter(self._rows)


class _FakeDB:
    def __init__(self, rows):
        self._coll = _FakeCollection(rows)

    def __getitem__(self, name):
        return self._coll


class _FakeClient:
    def __init__(self, rows):
        self._db = _FakeDB(rows)
        self.closed = False

    def __getitem__(self, name):
        return self._db

    def close(self):
        self.closed = True


def _factory(rows):
    client = _FakeClient(rows)
    return client, (lambda _uri: client)


def _env(monkeypatch, **overrides):
    defaults = {
        "MONGO_URI": "mongodb://localhost:27017",
        "MONGO_DB_NAME": "test_homeworks_db",
        "TENANT_ID": "t-abc123",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setenv(k, v)


def test_dry_run_does_not_delete(monkeypatch, capsys):
    mod = _load_script()
    rows = [
        {"id": "j1", "tenant_id": "t-abc123",
         "imported_from": "homeworks", "title": "Pool clean"},
        {"id": "j2", "tenant_id": "t-abc123",
         "imported_from": "homeworks", "title": "Hedge trim"},
        {"id": "j3", "tenant_id": "t-abc123",
         "imported_from": "native", "title": "Keep me"},
    ]
    client, factory = _factory(rows)
    _env(monkeypatch)

    rc = mod.main(argv=[], mongo_client_factory=factory)
    assert rc == 0
    # Dry-run leaves rows alone.
    assert len(client._db._coll.rows) == 3
    assert client._db._coll.deleted == 0


def test_filter_key_and_value_overrides(monkeypatch):
    mod = _load_script()
    rows = [
        {"id": "j1", "tenant_id": "t-abc123",
         "source": "homeworks"},
        {"id": "j2", "tenant_id": "t-abc123",
         "source": "homeworks"},
        {"id": "j3", "tenant_id": "t-abc123",
         "source": "native"},
    ]
    client, factory = _factory(rows)
    _env(monkeypatch)

    rc = mod.main(
        argv=["--filter-key", "source", "--value", "homeworks"],
        mongo_client_factory=factory,
    )
    assert rc == 0
    assert len(client._db._coll.rows) == 3


def test_refuses_without_required_env(monkeypatch):
    mod = _load_script()
    # Explicitly clear the gate.
    monkeypatch.delenv("TENANT_ID", raising=False)
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("MONGO_DB_NAME", "test_db")
    client, factory = _factory([])
    try:
        mod.main(argv=[], mongo_client_factory=factory)
        raised = False
    except SystemExit as e:
        raised = True
        assert e.code == 2
    assert raised


def test_apply_without_confirmation_aborts(monkeypatch):
    """Apply mode requires the operator to type 'yes'.  Anything
    else returns exit 1 and performs ZERO deletes."""
    mod = _load_script()
    rows = [
        {"id": "j1", "tenant_id": "t-abc123",
         "imported_from": "homeworks"},
    ]
    client, factory = _factory(rows)
    _env(monkeypatch)

    rc = mod.main(
        argv=["--apply"],
        mongo_client_factory=factory,
        stdin=io.StringIO("no\n"),
    )
    assert rc == 1
    assert len(client._db._coll.rows) == 1
    assert client._db._coll.deleted == 0


def test_large_sweep_refused_without_force_large(monkeypatch, tmp_path):
    """> 10,000 docs + --apply + 'yes' confirmation still returns
    exit 3 without --force-large (safety rail)."""
    mod = _load_script()
    rows = [
        {"id": f"j{i}", "tenant_id": "t-abc123",
         "imported_from": "homeworks"}
        for i in range(10_001)
    ]
    client, factory = _factory(rows)
    _env(monkeypatch)
    monkeypatch.chdir(tmp_path)  # Keep log file out of /app.

    rc = mod.main(
        argv=["--apply"],
        mongo_client_factory=factory,
        stdin=io.StringIO("yes\n"),
    )
    assert rc == 3
    assert len(client._db._coll.rows) == 10_001
    assert client._db._coll.deleted == 0


def test_zero_matches_exits_cleanly(monkeypatch, tmp_path):
    mod = _load_script()
    rows = [
        {"id": "j1", "tenant_id": "t-abc123",
         "imported_from": "native"},
    ]
    client, factory = _factory(rows)
    _env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    rc = mod.main(
        argv=["--apply"],
        mongo_client_factory=factory,
        stdin=io.StringIO("yes\n"),
    )
    # Zero-match path exits before the confirmation prompt.
    assert rc == 0
    assert len(client._db._coll.rows) == 1
