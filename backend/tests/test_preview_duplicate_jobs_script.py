"""Feb-2026 · preview_duplicate_jobs.py — READ-ONLY dedup preview tests.

Covers detection precedence (A > B > C), CSV shape, CLI filtering,
multi-tenant safety, and summary math.  In-process against a plain
sync ``_FakeCollection`` — the preview script uses pymongo (sync),
NOT motor, so no asyncio plumbing is needed here.
"""
from __future__ import annotations

import csv
from typing import Any, Dict, List, Optional

import pytest

from scripts.preview_duplicate_jobs import (
    identify_duplicate_groups,
    build_csv_rows,
    load_customers,
    load_jobs_for_customer,
    main as preview_main,
)


# ═════════════════════════════════════════════════════════════════
# Fake sync Mongo — mirrors the ``_FakeCollection`` naming used
# elsewhere in the test suite, but sync (matches pymongo).  Adds
# the ``.distinct()`` shim from the earlier test-hygiene work.
# ═════════════════════════════════════════════════════════════════
class _FakeCollection:
    """Tiny in-memory collection.  Supports:
        * ``find(query)`` → list-like iterator (order-preserving).
        * ``distinct(field)`` — set of distinct values (earlier
          test-hygiene work added this shim; mirrored here so the
          script stays swap-compatible with existing test infra).
        * ``insert_many(docs)`` / ``insert_one(doc)`` for setup.
    ``query`` supports ``{field: value}`` equality only + a
    lightweight ``$or`` array of equality clauses — enough for the
    two queries the preview script issues.
    """
    def __init__(self, docs: Optional[List[Dict[str, Any]]] = None):
        self._docs: List[Dict[str, Any]] = list(docs or [])

    def insert_many(self, docs): self._docs.extend(docs)
    def insert_one(self, doc): self._docs.append(doc)

    def _match(self, doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
        for k, v in query.items():
            if k == "$or":
                if not any(self._match(doc, clause) for clause in v):
                    return False
                continue
            if isinstance(v, dict) and "$regex" in v:
                # Case-insensitive substring test.  Enough for the
                # ``load_customers`` regex the script builds.
                import re as _re
                flags = _re.IGNORECASE if "i" in (v.get("$options") or "") else 0
                if not _re.search(v["$regex"], str(doc.get(k) or ""), flags):
                    return False
                continue
            if doc.get(k) != v:
                return False
        return True

    def find(self, query: Optional[Dict[str, Any]] = None):
        query = query or {}
        return [d for d in self._docs if self._match(d, query)]

    def distinct(self, field: str) -> List[Any]:
        seen: set = set()
        out: List[Any] = []
        for d in self._docs:
            v = d.get(field)
            key = repr(v)
            if key not in seen:
                seen.add(key)
                out.append(v)
        return out


class _FakeDB:
    def __init__(self, customers: List[Dict[str, Any]],
                 jobs: List[Dict[str, Any]]):
        self.customers = _FakeCollection(customers)
        self.jobs = _FakeCollection(jobs)


# ═════════════════════════════════════════════════════════════════
# Fixture helpers
# ═════════════════════════════════════════════════════════════════
def _cust(id_="c-1", tenant="t-1", name="Lorena Olivas",
          first="Lorena", last="Olivas") -> Dict[str, Any]:
    return {"id": id_, "tenant_id": tenant, "name": name,
            "first_name": first, "last_name": last}


def _job(id_, tenant="t-1", cust="c-1", title="Weekly pool",
         sched="2026-02-01", created="2026-02-01T09:00:00+00:00",
         tpl=None, status="scheduled", deleted=None) -> Dict[str, Any]:
    return {
        "id": id_, "tenant_id": tenant, "customer_id": cust,
        "title": title, "scheduled_date": sched, "created_at": created,
        "recurring_template_id": tpl, "status": status,
        "deleted_at": deleted,
    }


# ═════════════════════════════════════════════════════════════════
# 1) Detection pipeline
# ═════════════════════════════════════════════════════════════════
class TestDetectionPipeline:
    def test_empty_jobs_returns_empty(self):
        assert identify_duplicate_groups([]) == []

    def test_single_job_returns_empty(self):
        assert identify_duplicate_groups([_job("j-1")]) == []

    def test_group_a_recurring_template_id(self):
        jobs = [
            _job("j-1", tpl="tpl-A", created="2026-02-01T00:00:00+00:00"),
            _job("j-2", tpl="tpl-A", created="2026-02-08T00:00:00+00:00"),
            _job("j-3", tpl="tpl-A", created="2026-02-15T00:00:00+00:00"),
        ]
        out = identify_duplicate_groups(jobs)
        assert len(out) == 1
        gid, gtype, group = out[0]
        assert gtype == "A"
        assert len(group) == 3

    def test_group_b_exact_sched_and_title(self):
        jobs = [
            _job("j-1", sched="2026-02-01T09:00:00", title="Weekly pool",
                 created="2026-02-01T00:00:00+00:00"),
            _job("j-2", sched="2026-02-01T09:00:00", title="Weekly pool",
                 created="2026-02-02T00:00:00+00:00"),
        ]
        out = identify_duplicate_groups(jobs)
        assert len(out) == 1
        assert out[0][1] == "B"

    def test_group_c_near_adjacent_within_five_minutes(self):
        jobs = [
            _job("j-1", sched="2026-02-01T09:00:00+00:00", title="Weekly pool",
                 created="2026-02-01T00:00:00+00:00"),
            _job("j-2", sched="2026-02-01T09:04:00+00:00", title="Weekly pool",
                 created="2026-02-02T00:00:00+00:00"),
        ]
        out = identify_duplicate_groups(jobs)
        assert len(out) == 1
        assert out[0][1] == "C"

    def test_group_c_beyond_five_minutes_not_grouped(self):
        jobs = [
            _job("j-1", sched="2026-02-01T09:00:00+00:00", title="Weekly pool"),
            _job("j-2", sched="2026-02-01T09:06:00+00:00", title="Weekly pool"),
        ]
        # 6 min gap > 5 min window → NOT clustered.
        assert identify_duplicate_groups(jobs) == []

    def test_precedence_A_over_B(self):
        """A job in Group A must NOT also surface in Group B."""
        jobs = [
            _job("j-1", tpl="tpl-A", sched="2026-02-01T09:00:00",
                 title="Weekly", created="2026-02-01T00:00:00+00:00"),
            _job("j-2", tpl="tpl-A", sched="2026-02-01T09:00:00",
                 title="Weekly", created="2026-02-02T00:00:00+00:00"),
        ]
        out = identify_duplicate_groups(jobs)
        assert len(out) == 1
        assert out[0][1] == "A"

    def test_precedence_B_over_C(self):
        jobs = [
            _job("j-1", sched="2026-02-01T09:00:00", title="Weekly pool"),
            _job("j-2", sched="2026-02-01T09:00:00", title="Weekly pool"),
        ]
        out = identify_duplicate_groups(jobs)
        assert len(out) == 1
        assert out[0][1] == "B"

    def test_mixed_groups_all_categorised(self):
        jobs = [
            # A cluster
            _job("j-a1", tpl="tpl-A"),
            _job("j-a2", tpl="tpl-A"),
            # B cluster (different template)
            _job("j-b1", sched="2026-02-05T10:00:00", title="Vac", tpl=None),
            _job("j-b2", sched="2026-02-05T10:00:00", title="Vac", tpl=None),
            # C cluster
            _job("j-c1", sched="2026-02-10T11:00:00+00:00", title="Chem",
                 tpl=None),
            _job("j-c2", sched="2026-02-10T11:03:00+00:00", title="Chem",
                 tpl=None),
            # Standalone
            _job("j-s1", sched="2026-02-20T14:00:00", title="Solo", tpl=None),
        ]
        out = identify_duplicate_groups(jobs)
        types = sorted([g[1] for g in out])
        assert types == ["A", "B", "C"]


# ═════════════════════════════════════════════════════════════════
# 2) KEEP row selection
# ═════════════════════════════════════════════════════════════════
class TestKeepSelection:
    def test_earliest_created_at_is_keep(self):
        c = _cust()
        jobs = [
            _job("j-old",   tpl="tpl-K", created="2026-01-01T00:00:00+00:00"),
            _job("j-mid",   tpl="tpl-K", created="2026-02-01T00:00:00+00:00"),
            _job("j-newer", tpl="tpl-K", created="2026-03-01T00:00:00+00:00"),
        ]
        groups = identify_duplicate_groups(jobs)
        rows = build_csv_rows(c, groups)
        keep = [r for r in rows if r["action"] == "KEEP"]
        delete = [r for r in rows if r["action"] == "CANDIDATE_DELETE"]
        assert len(keep) == 1
        assert keep[0]["job_id"] == "j-old"
        assert sorted([r["job_id"] for r in delete]) == ["j-mid", "j-newer"]


# ═════════════════════════════════════════════════════════════════
# 3) CLI + CSV shape via main()
# ═════════════════════════════════════════════════════════════════
class TestCliMain:
    def test_no_matches_writes_empty_csv_and_reports_zero(self, tmp_path,
                                                            capsys):
        out_csv = tmp_path / "empty.csv"
        db = _FakeDB([], [])
        rc = preview_main(["--output", str(out_csv)], db=db)
        assert rc == 0
        captured = capsys.readouterr()
        assert "0 candidate deletes" in captured.out
        # Empty CSV — header only.
        with open(out_csv) as f:
            content = f.read()
        header_line = content.splitlines()[0]
        assert "group_id,group_type,action" in header_line
        assert len(content.splitlines()) == 1  # header only

    def test_customer_name_filter_narrows_scope(self, tmp_path, capsys):
        db = _FakeDB(
            customers=[
                _cust("c-lore", tenant="t-1", name="Lorena Olivas"),
                _cust("c-neil", tenant="t-1", name="Neil King",
                      first="Neil", last="King"),
            ],
            jobs=[
                _job("j-1", cust="c-lore", tpl="tpl-1"),
                _job("j-2", cust="c-lore", tpl="tpl-1"),
                # Neil's dupes should be excluded by the name filter.
                _job("j-3", cust="c-neil", tpl="tpl-2"),
                _job("j-4", cust="c-neil", tpl="tpl-2"),
            ],
        )
        out_csv = tmp_path / "lorena.csv"
        rc = preview_main(
            ["--customer-name", "Lorena", "--output", str(out_csv)],
            db=db,
        )
        assert rc == 0
        # 1 KEEP + 1 CANDIDATE = 2 rows.
        with open(out_csv) as f:
            reader = list(csv.DictReader(f))
        assert len(reader) == 2
        job_ids = {r["job_id"] for r in reader}
        assert job_ids == {"j-1", "j-2"}
        # Summary math.
        captured = capsys.readouterr()
        assert "1 customer(s)" in captured.out
        assert "2 jobs total" in captured.out
        assert "1 candidate deletes" in captured.out

    def test_tenant_id_filter_narrows_scope(self, tmp_path):
        db = _FakeDB(
            customers=[
                _cust("c-t1", tenant="t-1", name="Alpha Beta"),
                _cust("c-t2", tenant="t-2", name="Alpha Beta"),
            ],
            jobs=[
                _job("j-1", tenant="t-1", cust="c-t1", tpl="tpl-1"),
                _job("j-2", tenant="t-1", cust="c-t1", tpl="tpl-1"),
                _job("j-3", tenant="t-2", cust="c-t2", tpl="tpl-2"),
                _job("j-4", tenant="t-2", cust="c-t2", tpl="tpl-2"),
            ],
        )
        out_csv = tmp_path / "t1.csv"
        rc = preview_main(["--tenant-id", "t-1", "--output", str(out_csv)], db=db)
        assert rc == 0
        with open(out_csv) as f:
            rows = list(csv.DictReader(f))
        # Only t-1 rows should surface.
        assert all(r["tenant_id"] == "t-1" for r in rows)
        assert len(rows) == 2

    def test_multi_tenant_groups_stay_separate(self, tmp_path):
        """A customer that exists in TWO tenants must NOT have
        their per-tenant jobs cross-clustered."""
        db = _FakeDB(
            customers=[
                _cust("c-t1", tenant="t-1", name="Lorena Olivas"),
                _cust("c-t2", tenant="t-2", name="Lorena Olivas"),
            ],
            jobs=[
                # Same recurring_template_id in BOTH tenants — must
                # NOT bleed across because ``load_jobs_for_customer``
                # scopes by tenant_id.
                _job("j-t1a", tenant="t-1", cust="c-t1", tpl="tpl-X"),
                _job("j-t1b", tenant="t-1", cust="c-t1", tpl="tpl-X"),
                _job("j-t2a", tenant="t-2", cust="c-t2", tpl="tpl-X"),
                _job("j-t2b", tenant="t-2", cust="c-t2", tpl="tpl-X"),
            ],
        )
        out_csv = tmp_path / "multi.csv"
        rc = preview_main(["--output", str(out_csv)], db=db)
        assert rc == 0
        with open(out_csv) as f:
            rows = list(csv.DictReader(f))
        # Two independent groups, one per tenant → 4 rows total.
        assert len(rows) == 4
        # Every row's group_id + tenant_id combo is unique to its
        # tenant (no cross-tenant leakage into a single group).
        group_tenants: Dict[str, set] = {}
        for r in rows:
            group_tenants.setdefault(r["group_id"], set()).add(r["tenant_id"])
        for gid, tenants in group_tenants.items():
            assert len(tenants) == 1, (
                f"Group {gid} bled across tenants: {tenants}"
            )


# ═════════════════════════════════════════════════════════════════
# 4) Reasoning text + group precedence in CSV output
# ═════════════════════════════════════════════════════════════════
def test_reasoning_column_reflects_group_type():
    c = _cust()
    jobs = [
        _job("j-a1", tpl="tpl-A"),
        _job("j-a2", tpl="tpl-A"),
        _job("j-b1", sched="2026-03-01T10:00:00", title="Vac"),
        _job("j-b2", sched="2026-03-01T10:00:00", title="Vac"),
    ]
    groups = identify_duplicate_groups(jobs)
    rows = build_csv_rows(c, groups)
    a_rows = [r for r in rows if r["group_type"] == "A"]
    b_rows = [r for r in rows if r["group_type"] == "B"]
    assert any("recurring occurrence" in r["reasoning"] for r in a_rows)
    assert any("exact scheduled_date" in r["reasoning"] for r in b_rows)
