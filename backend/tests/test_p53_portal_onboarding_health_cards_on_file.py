"""P53 tail (Feb-2026) — ``active_with_card_on_file`` cohort tests.

Locks the backend contract that supports the customer-stats tile swap
(Never logged in → Cards on file). Coverage:

  1. Response envelope now includes ``active_with_card_on_file``.
  2. Chase-button binding: ``never_logged_in`` count is STILL returned
     — the frontend uses it for
     ``chaseAudienceUpperBound = min(invited, never)``. Removing this
     key would silently break the Chase button's disabled state.
  3. Cards-on-file predicate:
     * counted   → is_active True + saved_payment_methods_count > 0
     * counted   → is_active field absent + card > 0 (legacy default-
                   active semantics, per Phase 34f)
     * NOT count → is_active False (Inactive tab)
     * NOT count → is_muted True (Muted tab — excluded even if
                   card > 0)
     * NOT count → saved_payment_methods_count == 0 / None / absent
  4. Universe scoping — soft-deleted / merged-into / K49b-orphan rows
     are excluded from the cards-on-file count too (same walk as the
     other 4 cohorts).
  5. Cross-tenant isolation — foreign-tenant rows never leak in.
  6. Tile ↔ chip parity — the count matches the customers-list
     ``?is_active=true&has_payment_method=true`` intersection: an
     active-muted row is excluded from BOTH (verified via the
     shared ``_NOT_MUTED`` predicate on the list side).

Uses the same fake-DB fixture pattern as the sister
``test_portal_onboarding_health.py`` file for consistency; every
predicate branch is exercised on a small hand-seeded state so a
regression drops a single assertion.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def __aiter__(self):
        self._it = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, length=None):
        return list(self._rows)


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])

    def find(self, filt=None, projection=None):
        return _Cursor(self._match(filt or {}))

    def _match(self, filt: Dict[str, Any]):
        return [r for r in self.rows if self._doc_matches(r, filt)]

    @staticmethod
    def _doc_matches(doc, filt) -> bool:
        for k, v in (filt or {}).items():
            if k == "$or":
                if not any(_Coll._doc_matches(doc, sub) for sub in v):
                    return False
            elif k == "$and":
                if not all(_Coll._doc_matches(doc, sub) for sub in v):
                    return False
            elif isinstance(v, dict):
                val = doc.get(k)
                if "$exists" in v:
                    if bool(v["$exists"]) != (k in doc):
                        return False
                if "$nin" in v and val in v["$nin"]:
                    return False
                if "$ne" in v and val == v["$ne"]:
                    return False
            else:
                if doc.get(k) != v:
                    return False
        return True


class _DB:
    def __init__(self):
        self.customers = _Coll()


@pytest.fixture()
def fake_db(monkeypatch):
    fake = _DB()
    from routers import profit_report as pr
    monkeypatch.setattr(pr, "db", fake)
    pr._ONBOARDING_CACHE.clear()
    return fake


TID = "t-p53-cards"


def _now():
    return datetime.now(timezone.utc)


def _iso_offset(days: int) -> str:
    return (_now() + timedelta(days=days)).isoformat()


ADMIN = {"id": "u-admin", "role": "admin", "tenant_id": TID}


# ═══════════════════════════════════════════════════════════════════
# 1. Envelope — active_with_card_on_file cohort is present.
# ═══════════════════════════════════════════════════════════════════
def test_response_envelope_includes_active_with_card_on_file(fake_db):
    from routers.profit_report import portal_onboarding_health
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    cohorts = out["cohorts"]
    assert "active_with_card_on_file" in cohorts
    block = cohorts["active_with_card_on_file"]
    assert set(block.keys()) == {"count", "delta_30d"}
    assert block["delta_30d"] is None
    assert isinstance(block["count"], int)


# ═══════════════════════════════════════════════════════════════════
# 2. Chase-button binding — never_logged_in count survives the swap.
# ═══════════════════════════════════════════════════════════════════
def test_never_logged_in_count_retained_for_chase_button(fake_db):
    """Frontend ``PortalOnboardingHealthTile.jsx`` reads
    ``data.cohorts.never_logged_in.count`` to compute the Chase
    button's ``disabled`` state (``min(invited, never)``). This
    assertion locks the P53-tail contract that the cohort count
    stays in the response even after the tile UI stopped
    rendering the Never card.
    """
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-1", "tenant_id": TID, "has_login": True,
          "is_active": True},
        {"id": "c-2", "tenant_id": TID, "has_login": True,
          "is_active": True,
          "portal_first_login_at": _iso_offset(-2)},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    c = out["cohorts"]
    assert "never_logged_in" in c
    # Both c-1 and c-2 lack password_set; c-1 lacks first_login
    # entirely so it's never_logged_in. c-2 has first_login so
    # it moves out of never.
    assert c["never_logged_in"]["count"] == 1


# ═══════════════════════════════════════════════════════════════════
# 3. Cards-on-file predicate branches.
# ═══════════════════════════════════════════════════════════════════
def test_active_true_plus_card_gt_zero_is_counted(fake_db):
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-active-card", "tenant_id": TID,
          "is_active": True, "saved_payment_methods_count": 2},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    assert out["cohorts"]["active_with_card_on_file"]["count"] == 1


def test_active_field_absent_plus_card_gt_zero_is_counted(fake_db):
    """Phase 34f semantics: rows created before the ``is_active``
    field existed default to active. The tile MUST count them.
    """
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-legacy", "tenant_id": TID,
          "saved_payment_methods_count": 1},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    assert out["cohorts"]["active_with_card_on_file"]["count"] == 1


def test_is_active_false_is_excluded_even_with_card(fake_db):
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-inactive", "tenant_id": TID,
          "is_active": False, "saved_payment_methods_count": 3},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    assert out["cohorts"]["active_with_card_on_file"]["count"] == 0


def test_muted_row_is_excluded_even_when_active_and_with_card(fake_db):
    """Feb-2026 · P32 — muted rows live in their own Muted tab and
    are excluded from Active/Inactive counts. The Cards-on-file
    tile mirrors that exclusion so the tile ↔ customers-list
    ``?is_active=true&has_payment_method=true`` intersection
    matches (the list's ``is_active=true`` branch already
    enforces ``_NOT_MUTED``).
    """
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-muted", "tenant_id": TID,
          "is_active": True, "is_muted": True,
          "saved_payment_methods_count": 5},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    assert out["cohorts"]["active_with_card_on_file"]["count"] == 0


@pytest.mark.parametrize("card_field", [
    {"saved_payment_methods_count": 0},
    {"saved_payment_methods_count": None},
    {},                        # field absent
])
def test_card_count_zero_or_missing_is_excluded(fake_db, card_field):
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-no-card", "tenant_id": TID,
          "is_active": True, **card_field},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    assert out["cohorts"]["active_with_card_on_file"]["count"] == 0


# ═══════════════════════════════════════════════════════════════════
# 4. Universe scoping — soft-deleted / merged / orphan rows excluded.
# ═══════════════════════════════════════════════════════════════════
def test_soft_deleted_rows_excluded_from_cards_on_file(fake_db):
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-live", "tenant_id": TID,
          "is_active": True, "saved_payment_methods_count": 1},
        {"id": "c-deleted", "tenant_id": TID,
          "is_active": True, "saved_payment_methods_count": 1,
          "deleted_at": _iso_offset(-1)},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    assert out["cohorts"]["active_with_card_on_file"]["count"] == 1


def test_merged_into_rows_excluded_from_cards_on_file(fake_db):
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-live", "tenant_id": TID,
          "is_active": True, "saved_payment_methods_count": 1},
        {"id": "c-merged", "tenant_id": TID,
          "is_active": True, "saved_payment_methods_count": 1,
          "merged_into": "c-live"},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    assert out["cohorts"]["active_with_card_on_file"]["count"] == 1


def test_id_orphan_rows_excluded_from_cards_on_file(fake_db):
    """K49b — rows missing a top-level ``id`` are excluded from the
    customer universe by ``_valid_customer_id_predicate`` on
    every path (list, count, facet, onboarding tile).
    """
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-live", "tenant_id": TID,
          "is_active": True, "saved_payment_methods_count": 1},
        # No top-level id — filtered out by the predicate.
        {"tenant_id": TID,
          "is_active": True, "saved_payment_methods_count": 1},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    assert out["cohorts"]["active_with_card_on_file"]["count"] == 1


# ═══════════════════════════════════════════════════════════════════
# 5. Cross-tenant isolation.
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_rows_do_not_leak_into_cards_on_file(fake_db):
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-us", "tenant_id": TID,
          "is_active": True, "saved_payment_methods_count": 1},
        {"id": "c-them", "tenant_id": "t-OTHER",
          "is_active": True, "saved_payment_methods_count": 10},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    assert out["cohorts"]["active_with_card_on_file"]["count"] == 1


# ═══════════════════════════════════════════════════════════════════
# 6. Mixed dataset — every branch fires exactly once.
# ═══════════════════════════════════════════════════════════════════
def test_mixed_seed_yields_correct_cards_on_file_and_never_counts(fake_db):
    """Sanity: hand-seed one row per predicate branch and verify the
    two contract numbers (cards_on_file + never_logged_in) match
    the expected shape.

    Seeded rows (all tenant=TID unless noted):
      * c-1  active + card=2 + never   → CARDS + NEVER
      * c-2  active + card=1 + signed  → CARDS
      * c-3  legacy (no is_active) + card=1  → CARDS
      * c-4  active + card=0  → (neither)
      * c-5  inactive + card=3  → (neither)
      * c-6  muted + card=1  → (neither)
      * c-7  deleted + card=1  → (neither, universe)
      * c-8  other-tenant + card=1  → (neither, universe)
    """
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-1", "tenant_id": TID, "is_active": True,
          "saved_payment_methods_count": 2, "has_login": True},
        {"id": "c-2", "tenant_id": TID, "is_active": True,
          "saved_payment_methods_count": 1,
          "portal_first_login_at": _iso_offset(-3)},
        {"id": "c-3", "tenant_id": TID,
          "saved_payment_methods_count": 1},
        {"id": "c-4", "tenant_id": TID, "is_active": True,
          "saved_payment_methods_count": 0},
        {"id": "c-5", "tenant_id": TID, "is_active": False,
          "saved_payment_methods_count": 3},
        {"id": "c-6", "tenant_id": TID, "is_active": True,
          "is_muted": True, "saved_payment_methods_count": 1},
        {"id": "c-7", "tenant_id": TID, "is_active": True,
          "saved_payment_methods_count": 1,
          "deleted_at": _iso_offset(-1)},
        {"id": "c-8", "tenant_id": "t-OTHER", "is_active": True,
          "saved_payment_methods_count": 1},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=ADMIN))
    c = out["cohorts"]
    # cards_on_file = c-1, c-2, c-3 → 3.
    assert c["active_with_card_on_file"]["count"] == 3
    # never_logged_in must still be computed — c-1 (invited via
    # has_login=True, no first_login) counts; c-2 has first_login
    # so it does NOT count; c-3..c-6 have no first_login → count
    # too (they're in the same tenant universe minus the excluded
    # c-7 deleted and c-8 other-tenant).
    #   c-1, c-3, c-4, c-5, c-6 → 5.
    assert c["never_logged_in"]["count"] == 5
