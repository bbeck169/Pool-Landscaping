"""Feb-2026 · PDF-import customer-match ladder — pytest suite.

12 cases per dispatch spec in the user's addendum.  Exercises
both the pure-helper surface (``run_match_ladder`` /
``levenshtein`` / ``_canon_name``) and the integrated commit-
path surface (``auto_create_pending_customers`` with mocked
``db`` so no live Mongo is required).

Run from repo root:

    cd /app/backend && python -m pytest \\
        tests/test_pdf_import_customer_match_ladder.py -x -v
"""
from __future__ import annotations

import pytest

from services.imports.customer_match_ladder import (
    LadderResult,
    _canon_name,
    _classify_row_status,
    levenshtein,
    run_match_ladder,
)
from services.imports.customer_autocreate import (
    AutoCreateResult,
    MatchedExistingCustomer,
    auto_create_pending_customers,
)


# Project uses ``anyio`` for async tests (see
# ``tests/test_audio_transcribe.py`` + ``tests/test_pdfi_fast_path.py``).
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ═════════════════════════════════════════════════════════════
# Mock DB — supports the two collections the ladder + autocreate
# touch: ``customers`` + ``pending_import_customers``.  Only
# the find/update methods the real code uses are implemented.
# ═════════════════════════════════════════════════════════════
class _MockCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    async def to_list(self, length=None):
        return list(self._rows)

    def __aiter__(self):
        async def _gen():
            for r in self._rows:
                yield r
        return _gen()


class _MockCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.inserted = []
        self.updates = []

    def find(self, query, projection=None):
        matched = [r for r in self.rows if _mock_match(r, query)]
        return _MockCursor(matched)

    async def find_one(self, query, projection=None):
        for r in self.rows:
            if _mock_match(r, query):
                return dict(r)
        return None

    async def insert_one(self, doc):
        self.inserted.append(dict(doc))
        self.rows.append(dict(doc))
        return type("InsertResult", (),
                     {"inserted_id": doc.get("id") or "mock"})()

    async def update_one(self, query, update):
        for r in self.rows:
            if _mock_match(r, query):
                self.updates.append({"q": query, "u": update})
                for k, v in (update.get("$set") or {}).items():
                    r[k] = v
                return type("UpdateResult", (),
                             {"matched_count": 1, "modified_count": 1})()
        return type("UpdateResult", (),
                     {"matched_count": 0, "modified_count": 0})()


def _mock_match(row: dict, query: dict) -> bool:
    """Minimum-viable predicate matcher — handles the subset of
    Mongo operators ladder + autocreate actually use.
    """
    for key, val in query.items():
        if isinstance(val, dict):
            if "$in" in val:
                if row.get(key) not in val["$in"]:
                    return False
                continue
            if "$ne" in val:
                if row.get(key) == val["$ne"]:
                    return False
                continue
            if "$exists" in val:
                exists = key in row
                if exists != val["$exists"]:
                    return False
                continue
        else:
            if row.get(key) != val:
                return False
    return True


class _MockDB:
    def __init__(self):
        self.customers = _MockCollection()
        self.pending_import_customers = _MockCollection()
        self.audit_logs = _MockCollection()


def _add_customer(db, *, cid, name, tenant_id="t1", is_active=True,
                  is_muted=False, phone="", address=""):
    db.customers.rows.append({
        "id": cid, "tenant_id": tenant_id, "name": name,
        "is_active": is_active, "is_muted": is_muted,
        "phone": phone, "address": address, "deleted_at": None,
    })


# ═════════════════════════════════════════════════════════════
# Pure-helper tests
# ═════════════════════════════════════════════════════════════
class TestLadderPureHelpers:
    def test_levenshtein_identical(self):
        assert levenshtein("joe kail", "joe kail", 2) == 0

    def test_levenshtein_one_edit(self):
        assert levenshtein("joe kail", "joe kayl", 2) == 1

    def test_levenshtein_two_edits(self):
        assert levenshtein("joe kail", "joe kaylen", 2) > 2
        assert levenshtein("joe kail", "joe kay", 2) == 2

    def test_levenshtein_early_exit_on_length_delta(self):
        # Length delta > max_dist short-circuits.
        assert levenshtein("a", "abcdefg", 2) == 3  # > 2, sentinel

    def test_canon_name_ampersand_normalization(self):
        # Case 7 from dispatch spec.
        assert _canon_name("Joe & Jane Smith") == "joe and jane smith"
        assert _canon_name("Joe and Jane Smith") == "joe and jane smith"

    def test_canon_name_punctuation_strip(self):
        assert _canon_name("O'Brien, Joe!") == "o brien joe"

    def test_classify_row_status_muted_supersedes_inactive(self):
        assert _classify_row_status(
            {"is_active": False, "is_muted": True}
        ) == "muted"

    def test_classify_row_status_active_default(self):
        # Missing is_active + missing is_muted → active.
        assert _classify_row_status({}) == "active"
        assert _classify_row_status({"is_active": True}) == "active"


# ═════════════════════════════════════════════════════════════
# Ladder integration tests (12 required cases)
# ═════════════════════════════════════════════════════════════
class TestMatchLadderIntegration:
    async def test_01_exact_active_match(self):
        """Row with name matching an ACTIVE customer exactly →
        match_status='active', invoice attaches to that customer.
        """
        db = _MockDB()
        _add_customer(db, cid="c1", name="Joe Kail", is_active=True)
        res = await run_match_ladder(
            db=db, tenant_id="t1", extracted_name="Joe Kail",
        )
        assert res.match_status == "active"
        assert res.matched_customer_id == "c1"
        assert res.matched_customer_status == "active"
        assert res.match_method == "exact"
        assert res.match_confidence == 1.0

    async def test_02_exact_inactive_match(self):
        """Row with name matching an INACTIVE customer exactly →
        match_status='inactive', attaches, inactive customer NOT
        reactivated (ladder does not mutate the matched row).
        """
        db = _MockDB()
        _add_customer(db, cid="c2", name="Joe Kail",
                        is_active=False, is_muted=False)
        res = await run_match_ladder(
            db=db, tenant_id="t1", extracted_name="Joe Kail",
        )
        assert res.match_status == "inactive"
        assert res.matched_customer_id == "c2"
        assert res.matched_customer_status == "inactive"
        # Ladder didn't mutate the row — is_active still False.
        assert db.customers.rows[0]["is_active"] is False

    async def test_03_exact_muted_match(self):
        """Row with name matching a MUTED customer exactly →
        match_status='muted', attaches, mute flag preserved.
        """
        db = _MockDB()
        _add_customer(db, cid="c3", name="Joe Kail",
                        is_active=True, is_muted=True)
        res = await run_match_ladder(
            db=db, tenant_id="t1", extracted_name="Joe Kail",
        )
        assert res.match_status == "muted"
        assert res.matched_customer_id == "c3"
        assert res.matched_customer_status == "muted"
        assert db.customers.rows[0]["is_muted"] is True

    async def test_04_fuzzy_single_candidate_distance_1(self):
        """Row with name 1-char typo from an active customer
        (Levenshtein=1) → match_status='fuzzy_match',
        match_method='fuzzy', fuzzy_distance=1.
        """
        db = _MockDB()
        _add_customer(db, cid="c4", name="Joe Kail", is_active=True)
        res = await run_match_ladder(
            db=db, tenant_id="t1", extracted_name="Joe Kayl",
        )
        assert res.match_status == "fuzzy_match"
        assert res.match_method == "fuzzy"
        assert res.fuzzy_distance == 1
        assert res.matched_customer_id == "c4"
        assert 0.0 < (res.match_confidence or 0) < 1.0

    async def test_05_fuzzy_ambiguous_two_candidates(self):
        """Row where fuzzy finds 2 candidates at same distance →
        match_status='requires_manual_resolution', candidates
        array populated.
        """
        db = _MockDB()
        _add_customer(db, cid="c5a", name="Joe Kail", is_active=True)
        _add_customer(db, cid="c5b", name="Jon Kail", is_active=True)
        res = await run_match_ladder(
            db=db, tenant_id="t1", extracted_name="Joa Kail",
        )
        assert res.match_status == "requires_manual_resolution"
        assert len(res.candidates) == 2
        ids = {c.customer_id for c in res.candidates}
        assert ids == {"c5a", "c5b"}
        # Each candidate carries its distance.
        for c in res.candidates:
            assert c.fuzzy_distance == 1

    async def test_06_no_match_falls_through_to_auto_create(self):
        """Row where no match at any step → match_status=
        'will_auto_create' (existing path, no regression).
        """
        db = _MockDB()
        _add_customer(db, cid="c6", name="Alice Wonderland",
                        is_active=True)
        res = await run_match_ladder(
            db=db, tenant_id="t1", extracted_name="Bob Zephyr",
        )
        assert res.match_status == "will_auto_create"
        assert res.matched_customer_id is None

    async def test_07_ampersand_and_normalization_hits_exact(self):
        """Normalization: 'Joe & Jane Smith' extracted matches
        'Joe and Jane Smith' existing customer at exact step.
        """
        db = _MockDB()
        _add_customer(db, cid="c7", name="Joe and Jane Smith",
                        is_active=True)
        res = await run_match_ladder(
            db=db, tenant_id="t1", extracted_name="Joe & Jane Smith",
        )
        assert res.match_status == "active"
        assert res.match_method == "exact"
        assert res.matched_customer_id == "c7"

    async def test_08_tier_precedence_active_beats_inactive(self):
        """When both an active AND an inactive customer match
        the extracted name exactly, the active tier wins
        (tier 1 before tier 2 in the ladder).
        """
        db = _MockDB()
        _add_customer(db, cid="c8a", name="Joe Kail", is_active=False)
        _add_customer(db, cid="c8b", name="Joe Kail", is_active=True)
        res = await run_match_ladder(
            db=db, tenant_id="t1", extracted_name="Joe Kail",
        )
        assert res.match_status == "active"
        assert res.matched_customer_id == "c8b"

    async def test_09_substring_match_counted_as_distance_zero(self):
        """'Joe Kail' extracted matches 'Joe Kail Pool Service'
        existing customer via substring at distance 0 (fuzzy
        tier, since exact normalized form differs).
        """
        db = _MockDB()
        _add_customer(db, cid="c9", name="Joe Kail Pool Service",
                        is_active=True)
        res = await run_match_ladder(
            db=db, tenant_id="t1", extracted_name="Joe Kail",
        )
        assert res.match_status == "fuzzy_match"
        assert res.fuzzy_distance == 0

    async def test_10_short_name_skips_fuzzy_tier(self):
        """Names shorter than _FUZZY_MIN_NAME_LEN never trigger
        the fuzzy tier — guards against noise matches.
        """
        db = _MockDB()
        _add_customer(db, cid="c10", name="Joe", is_active=True)
        res = await run_match_ladder(
            db=db, tenant_id="t1", extracted_name="Jon",
        )
        # Below minimum fuzzy length — falls through to auto-create.
        assert res.match_status == "will_auto_create"

    async def test_11_within_batch_dedup_two_rows_one_inactive_match(self):
        """Within-batch dedup: 2 pending rows matching the same
        inactive customer both attach, no duplicate created.
        """
        db = _MockDB()
        _add_customer(db, cid="target", name="Joe Kail",
                        is_active=False, is_muted=False)
        db.pending_import_customers.rows = [
            {"id": "p1", "tenant_id": "t1",
             "extracted_customer_name": "Joe Kail",
             "extracted_address": "", "extracted_phone": "",
             "extracted_email": ""},
            {"id": "p2", "tenant_id": "t1",
             "extracted_customer_name": "Joe Kail",
             "extracted_address": "", "extracted_phone": "",
             "extracted_email": ""},
        ]
        previews = [
            {"source_doc_index": 0,
             "quote_in": {"customer_id": "PENDING::p1"}},
            {"source_doc_index": 1,
             "quote_in": {"customer_id": "PENDING::p2"}},
        ]
        result = await auto_create_pending_customers(
            previews=previews,
            batch={"id": "b1"},
            tenant_id="t1",
            operator={"id": "u1"},
            db=db,
        )
        # Both rows attached to the same inactive customer.
        assert all(
            p["quote_in"]["customer_id"] == "target" for p in previews
        )
        # No new customer inserted.
        assert len(db.customers.inserted) == 0
        # First row ran the full ladder → matched_existing carries
        # the attached-to-inactive forensic record.  Second row
        # short-circuited via in-batch dedupe (action='deduped_batch')
        # and therefore does NOT append a duplicate matched_existing
        # row — the audit payload already knows "target" was an
        # inactive match from the first row's entry.
        assert len(result.matched_existing) == 1
        assert result.matched_existing[0].matched_customer_status == "inactive"
        assert result.matched_existing[0].matched_customer_id == "target"
        # Both pending rows resolved — one via ladder, one via batch.
        actions = {c.action for c in result.auto_created}
        assert "deduped_db" in actions
        assert "deduped_batch" in actions

    async def test_12_reject_fuzzy_override_routes_to_auto_create(self):
        """Admin 'reject fuzzy match' override via request flag →
        does NOT attach to fuzzy match; falls through to
        auto-create (since no exact tier hits either).
        """
        db = _MockDB()
        _add_customer(db, cid="target_fuzzy", name="Joe Kail",
                        is_active=True)
        db.pending_import_customers.rows = [
            {"id": "p3", "tenant_id": "t1",
             "extracted_customer_name": "Joe Kayl",
             "extracted_address": "", "extracted_phone": "",
             "extracted_email": ""},
        ]
        previews = [
            {"source_doc_index": 0,
             "quote_in": {"customer_id": "PENDING::p3"}},
        ]
        result = await auto_create_pending_customers(
            previews=previews,
            batch={"id": "b2"},
            tenant_id="t1",
            operator={"id": "u1"},
            db=db,
            customer_match_overrides={"p3": "reject_fuzzy"},
        )
        # Operator rejected the fuzzy match → auto-create fires.
        assert len(db.customers.inserted) == 1
        new_cid = db.customers.inserted[0]["id"]
        assert previews[0]["quote_in"]["customer_id"] == new_cid
        # No ``matched_existing`` entries — the fuzzy row was
        # rejected and no exact tier matched.
        assert len(result.matched_existing) == 0
        # Legacy ``auto_created`` carries the newly minted row.
        assert any(
            c.action == "created" for c in result.auto_created
        )
