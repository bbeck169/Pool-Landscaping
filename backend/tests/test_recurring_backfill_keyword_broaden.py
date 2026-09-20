"""Phase Feb-2026 · Recurring-jobs backfill · keyword broaden tests.

Covers the 6 keyword patterns, priority order, structural-wins fallback,
and idempotency for keyword-matched clusters.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


from routers.recurring_jobs_backfill import (
    _KEYWORD_FREQ_PATTERNS,
    _infer_frequency,
    _is_recurring_row,
    _keyword_frequency,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"


def _login_super() -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "super@aquaterra.com", "password": "password123"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _tenant_id_of(token: str) -> str:
    r = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    return r.json()["tenant_id"]


def _seed_customer(tid: str) -> str:
    cid = f"p0rec-kw-c-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": f"TEST_p0rec_kw_{cid[-6:]}",
    })
    return cid


def _seed_title_only_jobs(*, tid, cid, title, service_type, n=3,
                          gap_days=7, start=date(2026, 1, 5)):
    """Seed jobs with title/description keyword hints only — no
    ``is_recurring`` / ``recurring_template_id`` / structural cadence
    fields. The keyword-broaden path must still pull these in."""
    for i in range(n):
        d = (start + timedelta(days=gap_days * i)).isoformat()
        _sync.jobs.insert_one({
            "id": f"p0rec-kw-j-{uuid.uuid4().hex[:8]}",
            "tenant_id": tid, "customer_id": cid,
            "customer_name": f"TEST_p0rec_kw_{cid[-6:]}",
            "title": title,
            "service_type": service_type,
            "scheduled_date": d, "price": 99.0,
            "status": "scheduled",
        })


def _cleanup(tid: str, cid: str):
    _sync.jobs.delete_many({"tenant_id": tid, "customer_id": cid})
    _sync.recurring_job_templates.delete_many(
        {"tenant_id": tid, "customer_id": cid},
    )
    _sync.customers.delete_many({"id": cid})


# ═══════════════════════ pure helper tests ═══════════════════════════
class TestKeywordFrequency:
    @pytest.mark.parametrize("title,expected", [
        ("Weekly Pool Service",         "weekly"),
        ("Bi-weekly Landscape",         "biweekly"),
        ("biweekly service call",       "biweekly"),
        ("bi weekly maintenance",       "biweekly"),
        ("Monthly Filter Clean",        "monthly"),
        ("Quarterly deep clean",        "quarterly"),
        ("Semi-annual audit",           "semi_annual"),
        ("semiannual review",           "semi_annual"),
        ("Annual inspection",           "custom"),
        ("yearly checkup",              "custom"),
    ])
    def test_pattern_hits(self, title, expected):
        assert _keyword_frequency({"title": title}) == expected

    def test_biweekly_wins_over_weekly(self):
        # "biweekly" contains "weekly" — biweekly must fire first per
        # most-specific-first ordering in _KEYWORD_FREQ_PATTERNS.
        assert _keyword_frequency({"title": "biweekly service"}) == "biweekly"

    def test_semiannual_wins_over_annual(self):
        assert _keyword_frequency({"title": "semi-annual inspection"}) == "semi_annual"

    def test_no_match_returns_none(self):
        assert _keyword_frequency({"title": "One-off deep clean"}) is None
        assert _keyword_frequency({"title": ""}) is None
        assert _keyword_frequency({}) is None

    def test_description_field_checked(self):
        assert _keyword_frequency({
            "title": "Pool service",
            "description": "Monthly cadence, recurring",
        }) == "monthly"

    def test_word_boundary_no_substring_match(self):
        # "weeklyish" shouldn't match \bweekly\b.
        assert _keyword_frequency({"title": "weeklyish care"}) is None
        # "informal annual-ish" — the word "annual" isn't standalone.
        assert _keyword_frequency({"title": "annually-ish"}) is None

    def test_ordering_matches_spec(self):
        expected = ["biweekly", "weekly", "monthly", "quarterly",
                    "semi_annual", "custom"]
        assert [freq for freq, _pat in _KEYWORD_FREQ_PATTERNS] == expected


class TestIsRecurringRowBroaden:
    def test_keyword_only_row_now_counts_as_recurring(self):
        assert _is_recurring_row({"title": "Weekly Pool Service"}) is True

    def test_structural_still_wins(self):
        assert _is_recurring_row({"is_recurring": True}) is True
        assert _is_recurring_row({"recurring": True}) is True
        assert _is_recurring_row({"cadence": "weekly"}) is True

    def test_no_hint_still_false(self):
        assert _is_recurring_row({"title": "One-off deep clean"}) is False

    def test_structural_wins_on_infer_frequency(self):
        # Structural frequency field must beat a keyword in the title.
        job = {"title": "Weekly Pool", "frequency": "monthly"}
        assert _infer_frequency(job) == "monthly"
        # The keyword helper still returns weekly but we call
        # _infer_frequency first in the scanner, so structural wins.
        assert _keyword_frequency(job) == "weekly"


# ═══════════════════════ endpoint smoke ═════════════════════════════
class TestBackfillKeywordEndToEnd:
    def test_weekly_title_only_becomes_template(self):
        tok = _login_super()
        tid = _tenant_id_of(tok)
        cid = _seed_customer(tid)
        try:
            _seed_title_only_jobs(
                tid=tid, cid=cid,
                title="TEST_p0rec_kw Weekly Pool Service",
                service_type="TEST_p0rec_kw_Weekly",
            )
            # Scan sees the cluster.
            r = requests.get(
                f"{API}/recurring-jobs/orphans",
                headers={"Authorization": f"Bearer {tok}"}, timeout=10,
            )
            assert r.status_code == 200
            ours = [x for x in r.json()["orphans"]
                    if x.get("customer_id") == cid]
            assert len(ours) == 1
            assert ours[0]["frequency"] == "weekly"
            assert ours[0]["backfill_source"] == "keyword_match"

            # Backfill materialises the template with source stamp.
            b = requests.post(
                f"{API}/recurring-jobs/backfill-orphans",
                headers={"Authorization": f"Bearer {tok}"}, timeout=15,
            )
            assert b.status_code == 200

            tpl = _sync.recurring_job_templates.find_one(
                {"tenant_id": tid, "customer_id": cid,
                 "service_type": "TEST_p0rec_kw_Weekly"},
                {"_id": 0},
            )
            assert tpl is not None
            assert tpl["frequency"] == "weekly"
            assert tpl["active"] is True
            assert tpl["backfill_source"] == "keyword_match"
            assert tpl["created_by_backfill"] is True

            # Idempotency — second run must not double-create.
            requests.post(
                f"{API}/recurring-jobs/backfill-orphans",
                headers={"Authorization": f"Bearer {tok}"}, timeout=15,
            )
            n = _sync.recurring_job_templates.count_documents(
                {"tenant_id": tid, "customer_id": cid,
                 "service_type": "TEST_p0rec_kw_Weekly"},
            )
            assert n == 1
        finally:
            _cleanup(tid, cid)

    def test_biweekly_title_only_becomes_template(self):
        tok = _login_super()
        tid = _tenant_id_of(tok)
        cid = _seed_customer(tid)
        try:
            _seed_title_only_jobs(
                tid=tid, cid=cid,
                title="TEST_p0rec_kw Bi-weekly Landscape",
                service_type="TEST_p0rec_kw_Bi",
                gap_days=14,
            )
            requests.post(
                f"{API}/recurring-jobs/backfill-orphans",
                headers={"Authorization": f"Bearer {tok}"}, timeout=15,
            )
            tpl = _sync.recurring_job_templates.find_one(
                {"tenant_id": tid, "customer_id": cid,
                 "service_type": "TEST_p0rec_kw_Bi"},
                {"_id": 0},
            )
            assert tpl is not None
            assert tpl["frequency"] == "biweekly"
            assert tpl["backfill_source"] == "keyword_match"
        finally:
            _cleanup(tid, cid)

    def test_no_hint_no_template(self):
        tok = _login_super()
        tid = _tenant_id_of(tok)
        cid = _seed_customer(tid)
        try:
            # No is_recurring flag, no cadence field, no keyword in title.
            _seed_title_only_jobs(
                tid=tid, cid=cid,
                title="TEST_p0rec_kw one-off deep clean",
                service_type="TEST_p0rec_kw_None",
            )
            r = requests.get(
                f"{API}/recurring-jobs/orphans",
                headers={"Authorization": f"Bearer {tok}"}, timeout=10,
            )
            ours = [x for x in r.json()["orphans"]
                    if x.get("customer_id") == cid]
            assert len(ours) == 0
            # And the backfill run must not mint a template for it.
            requests.post(
                f"{API}/recurring-jobs/backfill-orphans",
                headers={"Authorization": f"Bearer {tok}"}, timeout=15,
            )
            n = _sync.recurring_job_templates.count_documents(
                {"tenant_id": tid, "customer_id": cid,
                 "service_type": "TEST_p0rec_kw_None"},
            )
            assert n == 0
        finally:
            _cleanup(tid, cid)

    def test_structural_frequency_not_overridden_by_keyword(self):
        """A job whose title says 'Weekly' but has an explicit
        ``frequency='monthly'`` structural field must NOT be
        keyword-overridden."""
        tok = _login_super()
        tid = _tenant_id_of(tok)
        cid = _seed_customer(tid)
        try:
            for i in range(3):
                d = (date(2026, 2, 1) + timedelta(days=30 * i)).isoformat()
                _sync.jobs.insert_one({
                    "id": f"p0rec-kw-j-{uuid.uuid4().hex[:8]}",
                    "tenant_id": tid, "customer_id": cid,
                    "customer_name": f"TEST_p0rec_kw_{cid[-6:]}",
                    "title": "TEST_p0rec_kw Weekly-titled monthly job",
                    "service_type": "TEST_p0rec_kw_Mix",
                    "frequency": "monthly",       # structural wins
                    "is_recurring": True,
                    "scheduled_date": d, "price": 100.0,
                })
            requests.post(
                f"{API}/recurring-jobs/backfill-orphans",
                headers={"Authorization": f"Bearer {tok}"}, timeout=15,
            )
            tpl = _sync.recurring_job_templates.find_one(
                {"tenant_id": tid, "customer_id": cid,
                 "service_type": "TEST_p0rec_kw_Mix"},
                {"_id": 0},
            )
            assert tpl is not None
            # Structural frequency wins — NOT weekly.
            assert tpl["frequency"] == "monthly"
            assert tpl["backfill_source"] == "structural"
        finally:
            _cleanup(tid, cid)
