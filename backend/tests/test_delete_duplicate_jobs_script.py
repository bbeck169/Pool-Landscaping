"""Feb-2026 · delete_duplicate_jobs.py — SOFT-DELETE workflow tests.

Covers safety rails (KEEP-row refusal, >100 cap, already-deleted
skip, --confirm gate, --hard path), the plan print, the per-tenant
summary, and the ``mask_mongo_url`` credential scrubber.
"""
from __future__ import annotations

import csv
import io
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from scripts.delete_duplicate_jobs import (
    MAX_DELETES_PER_INVOCATION,
    DELETED_BY,
    SafetyError,
    apply_deletes,
    load_candidates,
    mask_mongo_url,
    main as delete_main,
    validate_input,
)


# ═════════════════════════════════════════════════════════════════
# Fake sync Mongo tuned for update_one + delete_one + update tracking.
# ═════════════════════════════════════════════════════════════════
class _FakeResult:
    def __init__(self, matched: int = 0, modified: int = 0, deleted: int = 0):
        self.matched_count = matched
        self.modified_count = modified
        self.deleted_count = deleted


class _FakeJobs:
    def __init__(self, docs: Optional[List[Dict[str, Any]]] = None):
        self._docs = list(docs or [])
        # Test hooks — record calls so specs can assert shape.
        self.updates: List[Dict[str, Any]] = []
        self.deletes: List[Dict[str, Any]] = []
        # ``fail_ids`` triggers a synthetic exception on the given
        # job ids (mixed success/failure spec).
        self.fail_ids: set = set()

    def insert_many(self, docs): self._docs.extend(docs)

    def _find_one(self, filt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for d in self._docs:
            if all(d.get(k) == v for k, v in filt.items()):
                return d
        return None

    def update_one(self, filt: Dict[str, Any], patch: Dict[str, Any]) -> _FakeResult:
        jid = filt.get("id")
        if jid in self.fail_ids:
            raise RuntimeError("simulated Mongo error")
        self.updates.append({"filter": filt, "patch": patch})
        doc = self._find_one(filt)
        if not doc:
            return _FakeResult(matched=0, modified=0)
        set_block = patch.get("$set") or {}
        for k, v in set_block.items():
            doc[k] = v
        return _FakeResult(matched=1, modified=1)

    def delete_one(self, filt: Dict[str, Any]) -> _FakeResult:
        jid = filt.get("id")
        if jid in self.fail_ids:
            raise RuntimeError("simulated Mongo error")
        self.deletes.append({"filter": filt})
        for i, d in enumerate(self._docs):
            if all(d.get(k) == v for k, v in filt.items()):
                del self._docs[i]
                return _FakeResult(deleted=1)
        return _FakeResult(deleted=0)


class _FakeDB:
    def __init__(self, jobs: Optional[List[Dict[str, Any]]] = None):
        self.jobs = _FakeJobs(jobs)


# ═════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════
def _write_csv(tmp_path, rows: List[Dict[str, Any]]) -> str:
    from scripts.preview_duplicate_jobs import CSV_FIELDS
    out_path = tmp_path / "input.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: "" for k in CSV_FIELDS}, **r})
    return str(out_path)


def _cand(job_id, tenant="t-1", scheduled="2026-02-01", title="Weekly",
          customer_name="Lorena Olivas", deleted_at="") -> Dict[str, str]:
    return {
        "action": "CANDIDATE_DELETE",
        "job_id": job_id,
        "tenant_id": tenant,
        "scheduled_date": scheduled,
        "title": title,
        "customer_name": customer_name,
        "deleted_at": deleted_at,
    }


def _keep(job_id, **kw) -> Dict[str, str]:
    return {**_cand(job_id, **kw), "action": "KEEP"}


# ═════════════════════════════════════════════════════════════════
# 1) mask_mongo_url
# ═════════════════════════════════════════════════════════════════
class TestMaskMongoUrl:
    def test_atlas_url_masked(self):
        url = "mongodb+srv://admin:SECRET@cluster-abc.mongodb.net/prod?retryWrites=true"
        masked = mask_mongo_url(url)
        assert "SECRET" not in masked
        assert "cluster-abc.mongodb.net" in masked
        assert "***:***" in masked

    def test_local_url_untouched_no_creds(self):
        url = "mongodb://localhost:27017"
        masked = mask_mongo_url(url)
        assert masked == "mongodb://localhost:27017"

    def test_none_returns_placeholder(self):
        assert mask_mongo_url(None) == "<no MONGO_URL set>"


# ═════════════════════════════════════════════════════════════════
# 2) validate_input — safety rails
# ═════════════════════════════════════════════════════════════════
class TestValidateInput:
    def test_keep_rows_refused(self):
        with pytest.raises(SafetyError, match="KEEP"):
            validate_input([_keep("j-1"), _cand("j-2")])

    def test_over_cap_refused(self):
        rows = [_cand(f"j-{i}") for i in range(MAX_DELETES_PER_INVOCATION + 1)]
        with pytest.raises(SafetyError, match="cap"):
            validate_input(rows)

    def test_already_deleted_pulled_into_skipped(self):
        to_delete, skipped = validate_input([
            _cand("j-1"),
            _cand("j-2", deleted_at="2026-02-01T00:00:00+00:00"),
        ])
        assert [r["job_id"] for r in to_delete] == ["j-1"]
        assert [r["job_id"] for r in skipped] == ["j-2"]

    def test_empty_input_returns_empty_lists(self):
        to_delete, skipped = validate_input([])
        assert to_delete == []
        assert skipped == []


# ═════════════════════════════════════════════════════════════════
# 3) apply_deletes — soft path
# ═════════════════════════════════════════════════════════════════
class TestApplyDeletesSoft:
    def test_sets_deleted_at_and_deleted_by(self):
        db = _FakeDB([
            {"id": "j-1", "tenant_id": "t-1", "title": "W"},
        ])
        fixed_now = datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc)
        result = apply_deletes(db, [_cand("j-1")], hard=False, now=fixed_now)
        assert result["successes"] == 1
        assert result["failures"] == 0
        # Actual mutation shape.
        assert db.jobs.updates == [{
            "filter": {"id": "j-1", "tenant_id": "t-1"},
            "patch": {"$set": {
                "deleted_at": fixed_now.isoformat(),
                "deleted_by": DELETED_BY,
            }},
        }]
        # Verify the doc actually got patched (fake mirrors the write).
        assert db.jobs._docs[0]["deleted_at"] == fixed_now.isoformat()
        assert db.jobs._docs[0]["deleted_by"] == DELETED_BY

    def test_missing_doc_counted_as_failure(self):
        db = _FakeDB([])
        result = apply_deletes(db, [_cand("j-missing")], hard=False)
        assert result["successes"] == 0
        assert result["failures"] == 1
        assert "no matching document" in result["failure_details"][0]["error"]

    def test_empty_job_id_counted_as_failure(self):
        db = _FakeDB([])
        result = apply_deletes(db, [_cand("")], hard=False)
        assert result["failures"] == 1
        assert "empty job_id" in result["failure_details"][0]["error"]


# ═════════════════════════════════════════════════════════════════
# 4) apply_deletes — hard path
# ═════════════════════════════════════════════════════════════════
class TestApplyDeletesHard:
    def test_delete_one_removes_row(self):
        db = _FakeDB([{"id": "j-1", "tenant_id": "t-1", "title": "W"}])
        result = apply_deletes(db, [_cand("j-1")], hard=True)
        assert result["successes"] == 1
        assert db.jobs._docs == []
        assert db.jobs.deletes == [{"filter": {"id": "j-1", "tenant_id": "t-1"}}]

    def test_missing_doc_hard_delete_counted_as_failure(self):
        db = _FakeDB([])
        result = apply_deletes(db, [_cand("j-x")], hard=True)
        assert result["failures"] == 1


# ═════════════════════════════════════════════════════════════════
# 5) Per-tenant summary — mixed successes + failures
# ═════════════════════════════════════════════════════════════════
def test_per_tenant_summary_mixed_success_and_failure():
    db = _FakeDB([
        {"id": "j-1", "tenant_id": "t-1"},
        {"id": "j-3", "tenant_id": "t-2"},
    ])
    # ``j-2`` is missing in the fake collection → will fail.
    # ``j-4`` will raise a synthetic error.
    db.jobs.fail_ids = {"j-4"}
    rows = [
        _cand("j-1", tenant="t-1"),
        _cand("j-2", tenant="t-1"),
        _cand("j-3", tenant="t-2"),
        _cand("j-4", tenant="t-2"),
    ]
    result = apply_deletes(db, rows, hard=False)
    assert result["successes"] == 2
    assert result["failures"] == 2
    assert result["per_tenant"]["t-1"] == {"success": 1, "failure": 1}
    assert result["per_tenant"]["t-2"] == {"success": 1, "failure": 1}


# ═════════════════════════════════════════════════════════════════
# 6) main() CLI — DRY-RUN + full flows
# ═════════════════════════════════════════════════════════════════
class TestCliMain:
    def test_dry_run_without_confirm_makes_no_writes(self, tmp_path, capsys):
        db = _FakeDB([{"id": "j-1", "tenant_id": "t-1"}])
        path = _write_csv(tmp_path, [_cand("j-1")])
        rc = delete_main(["--input", path], db=db)
        assert rc == 0
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out
        # Not touched.
        assert db.jobs.updates == []
        assert db.jobs.deletes == []

    def test_confirm_soft_delete_applies(self, tmp_path, capsys):
        db = _FakeDB([{"id": "j-1", "tenant_id": "t-1"}])
        path = _write_csv(tmp_path, [_cand("j-1")])
        rc = delete_main(["--input", path, "--confirm"], db=db)
        assert rc == 0
        assert len(db.jobs.updates) == 1
        # Soft-delete → doc still present.
        assert db.jobs._docs[0]["deleted_by"] == DELETED_BY

    def test_confirm_hard_delete_applies(self, tmp_path):
        db = _FakeDB([{"id": "j-1", "tenant_id": "t-1"}])
        path = _write_csv(tmp_path, [_cand("j-1")])
        rc = delete_main(["--input", path, "--confirm", "--hard"], db=db)
        assert rc == 0
        assert db.jobs._docs == []

    def test_keep_row_in_input_refuses_with_exit_2(self, tmp_path, capsys):
        db = _FakeDB([])
        path = _write_csv(tmp_path, [_keep("j-keeper"), _cand("j-1")])
        rc = delete_main(["--input", path, "--confirm"], db=db)
        assert rc == 2
        captured = capsys.readouterr()
        assert "REFUSED" in captured.err
        assert "KEEP" in captured.err

    def test_over_cap_refuses_with_exit_2(self, tmp_path, capsys):
        db = _FakeDB([])
        rows = [_cand(f"j-{i}") for i in range(MAX_DELETES_PER_INVOCATION + 1)]
        path = _write_csv(tmp_path, rows)
        rc = delete_main(["--input", path, "--confirm"], db=db)
        assert rc == 2
        captured = capsys.readouterr()
        assert "cap" in captured.err.lower()

    def test_already_deleted_rows_skipped_with_warning(self, tmp_path, capsys):
        db = _FakeDB([{"id": "j-1", "tenant_id": "t-1"}])
        path = _write_csv(tmp_path, [
            _cand("j-1"),
            _cand("j-old", deleted_at="2026-01-01T00:00:00+00:00"),
        ])
        rc = delete_main(["--input", path, "--confirm"], db=db)
        assert rc == 0
        captured = capsys.readouterr()
        assert "SKIP (already deleted_at=" in captured.out
        # Only the non-skipped row was actually written.
        assert len(db.jobs.updates) == 1

    def test_env_target_printed_masked(self, tmp_path, capsys, monkeypatch):
        # Populate MONGO_URL with a plausible creds shape so we can
        # verify the mask fires.
        monkeypatch.setenv(
            "MONGO_URL",
            "mongodb+srv://admin:SECRET@cluster.mongodb.net/prod",
        )
        db = _FakeDB([{"id": "j-1", "tenant_id": "t-1"}])
        path = _write_csv(tmp_path, [_cand("j-1")])
        rc = delete_main(["--input", path], db=db)
        assert rc == 0
        captured = capsys.readouterr()
        assert "Env target" in captured.out
        assert "SECRET" not in captured.out
        assert "cluster.mongodb.net" in captured.out

    def test_missing_input_file_returns_exit_2(self, tmp_path, capsys):
        rc = delete_main(["--input", str(tmp_path / "nope.csv")], db=_FakeDB())
        assert rc == 2
        assert "not found" in capsys.readouterr().err.lower()

    def test_failure_summary_returns_exit_1(self, tmp_path):
        # No matching doc → failure → exit 1.
        db = _FakeDB([])
        path = _write_csv(tmp_path, [_cand("j-nowhere")])
        rc = delete_main(["--input", path, "--confirm"], db=db)
        assert rc == 1
