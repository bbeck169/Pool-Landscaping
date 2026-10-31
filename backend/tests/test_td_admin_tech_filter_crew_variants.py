"""Feb-2026 · scope_jobs_query admin tech-filter crew-lookup fix.

Pins the single-line repair in ``routers/jobs.py`` admin lane:
    - Before: ``{"$in": _variants or [technician_id]}``
      — ``_variants`` is a ``TechIdVariants`` dataclass instance
      (not a list), so Mongo BSON-encode blows up with ``bson
      .errors.InvalidDocument`` / ``TypeError`` on every admin
      ``?technician_id=`` request.
    - After:  ``{"$in": _variants.all_ids or [technician_id]}``
      — passes the resolver's ``all_ids`` list, which is what the
      ``$in`` operator expects.

Repair applied at ``routers/jobs.py::scope_jobs_query`` admin
elif-lane around L544-548.  Existing XX-widening suite in
``test_td_xx_admin_tech_filter_crew_widening.py`` monkey-patched
the resolver to return a plain tuple ``([tech_id], _or)`` so it
never exercised the dataclass shape — hence the bug slipped
through.  This suite uses the REAL dataclass shape via a
monkey-patched resolver that returns a genuine
``TechIdVariants`` instance.

Harness mirrors ``test_td_xx_admin_tech_filter_crew_widening.py``
with a tiny stub for ``db.crews`` so the admin-lane query shape
can be asserted end-to-end without a live Mongo.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from routers.jobs import scope_jobs_query
from services.tech_id_resolver import TechIdVariants


def _run(coro):
    return asyncio.run(coro)


# ─── mongo-stub harness (shared pattern with XX suite) ─────────────
class _CursorStub:
    def __init__(self, docs): self._docs = docs
    async def to_list(self, _n): return list(self._docs)


class _CollectionStub:
    def __init__(self, docs):
        self._docs = docs
        self.last_filter: Dict[str, Any] | None = None

    def find(self, _filter, _proj=None):
        # Capture the final filter so tests can assert on the
        # exact shape passed to ``$in`` (regression lock on the
        # dataclass-vs-list bug).
        self.last_filter = _filter
        return _CursorStub(self._docs)


class _DbStub:
    def __init__(self, crews):
        self.crews = _CollectionStub(crews)


@pytest.fixture
def patch_db(monkeypatch):
    """Patch ``routers.jobs.db`` + the resolver so the admin lane
    runs end-to-end with the REAL ``TechIdVariants`` dataclass
    shape as the resolver's first return value."""
    import routers.jobs as _jobs
    state: Dict[str, Any] = {"crews": []}
    state["db"] = _DbStub(state["crews"])
    monkeypatch.setattr(_jobs, "db", state["db"])

    async def _real_shape_resolver(tech_id, tenant_id=None):
        # Return a REAL dataclass instance — the shipped resolver
        # does exactly this.  all_ids carries both the raw input
        # and whatever the technicians/users lookups resolved to.
        variants = TechIdVariants(
            input_id=tech_id, tenant_id=tenant_id,
            technicians_id=tech_id,
            users_id=f"user-of-{tech_id}",
            name="PS-D Test Tech",
            source="technicians",
            all_ids=[tech_id, f"user-of-{tech_id}"],
        )
        _or = {"$or": [
            {"technician_id":           {"$in": variants.all_ids}},
            {"assigned_technician_id":  {"$in": variants.all_ids}},
            {"assigned_to":             {"$in": variants.all_ids}},
            {"tech_user_id":            {"$in": variants.all_ids}},
        ]}
        return variants, _or

    import services.tech_id_resolver as _resolver_mod
    monkeypatch.setattr(
        _resolver_mod, "resolve_and_build_filter",
        _real_shape_resolver,
    )
    return state


def _admin_lane(tech_id: str, crews_fixture: List[Dict[str, Any]],
                 state: Dict[str, Any]) -> Dict[str, Any]:
    state["db"].crews._docs = crews_fixture
    user = {"role": "admin", "id": "u-admin", "tenant_id": "tenant-1"}
    tenant = {"id": "tenant-1"}
    return _run(scope_jobs_query(user, tenant, status=None,
                                     technician_id=tech_id))


# ═══════════════════════════════════════════════════════════════════
# Feb-2026 · Bug A — admin tech-filter crew-lookup crew_lookup fix.
# ═══════════════════════════════════════════════════════════════════

# 1. Admin GET /jobs?technician_id=<id> no longer crashes.  The
#    pre-fix code passed a dataclass to Mongo ``$in`` which crashed
#    BSON encoding at runtime.  Post-fix the call shape is valid.
def test_admin_tech_filter_does_not_crash(patch_db):
    q = _admin_lane("tech-1", crews_fixture=[], state=patch_db)
    # Query is a plain dict and did not raise.
    assert isinstance(q, dict)
    # Crew find was invoked with a LIST under ``$in`` (not a dataclass).
    f = patch_db["db"].crews.last_filter
    assert f is not None, "crew find was not invoked"
    tech_ids_in = f["tech_ids"]["$in"]
    assert isinstance(tech_ids_in, list), (
        "`$in` must receive a list — passing the resolver dataclass "
        "crashes BSON encode"
    )
    # List is the resolver's all_ids (not the fallback single-elem).
    assert set(tech_ids_in) == {"tech-1", "user-of-tech-1"}


# 2. Admin filter matches jobs assigned via ANY of the ID variants.
#    The resolver returns both ``technicians.id`` and ``users.id``
#    forms; the final ``$or`` clause must cover every job-field ×
#    every id-variant disjunction (so legacy writes under either
#    form are visible).
def test_admin_tech_filter_covers_all_id_variants(patch_db):
    q = _admin_lane("tech-1", crews_fixture=[], state=patch_db)
    # No crews → $or clause is the tech-only disjunction.
    assert "$or" in q
    or_clauses = q["$or"]
    # Every field × every variant covered.  The real
    # ``build_tech_field_or_clause`` output has 4 field branches,
    # each with the full id-variant list under ``$in``.
    seen_fields = {next(iter(c.keys())) for c in or_clauses}
    assert {"technician_id", "assigned_technician_id",
            "assigned_to", "tech_user_id"}.issubset(seen_fields)
    for c in or_clauses:
        (field, cond), = c.items()
        if "crew_id" in field:
            continue
        assert "$in" in cond and set(cond["$in"]) == {
            "tech-1", "user-of-tech-1",
        }, f"field {field} missing an id variant"


# 3. Admin filter + crew_id widening — the admin lane also unions
#    the crew-membership branch into the final ``$or`` so crew-only
#    jobs (crew_id set, technician_id null) are visible.  This
#    pins the shipped XX-widening behavior under the real resolver
#    shape so the regression lock is complete.
def test_admin_tech_filter_unions_crew_branch(patch_db):
    crews = [{"id": "crew-A"}, {"id": "crew-B"}]
    q = _admin_lane("tech-1", crews_fixture=crews, state=patch_db)
    assert "$or" in q
    crew_branches = [c for c in q["$or"] if "crew_id" in c]
    assert len(crew_branches) == 1, (
        "crew-membership branch must be unioned exactly once"
    )
    assert set(crew_branches[0]["crew_id"]["$in"]) == {
        "crew-A", "crew-B",
    }
