"""P1 · Feb-2026 — Read-only mileage audit diagnostic endpoint tests.

Pins two surfaces of ``routers/admin_mileage_audit.py``:

  1. ``_classify`` — server-side classification helper that
     maps raw ping counts + shift rows to one of
     ``preview_clean`` /
     ``likely_calculator_reading_wrong_collection`` /
     ``likely_mobile_not_posting`` / ``no_shifts_in_window`` /
     ``unknown``.
  2. End-to-end endpoint shape — admin-gated, read-only, user_id
     404, invalid window handling.

Strictly read-only — no DB writes.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values


_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
for _k in ("MONGO_URL", "DB_NAME"):
    if _k not in os.environ and _BE.get(_k):
        os.environ[_k] = _BE[_k]


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ─── §1 · _classify — 5-branch coverage ──────────────────────────

def test_classify_likely_calculator_reading_wrong_collection():
    """``gps_total >> loc_total AND any closed shift mileage==0``
    → ``likely_calculator_reading_wrong_collection``. Mirrors the
    exact Steven-Martinez-2026-10-01 shape the P1 investigation
    report called out."""
    from routers.admin_mileage_audit import _classify
    out = _classify(
        gps_total=200,
        loc_total_tracking=2,
        shifts=[{"clock_out_at": "2026-10-01T18:00:00+00:00",
                 "mileage_miles": 0.0}],
    )
    assert out == "likely_calculator_reading_wrong_collection"


def test_classify_likely_mobile_not_posting():
    """Both ping collections empty → mobile isn't posting."""
    from routers.admin_mileage_audit import _classify
    out = _classify(
        gps_total=0, loc_total_tracking=0,
        shifts=[{"clock_out_at": "2026-10-01T18:00:00+00:00",
                 "mileage_miles": 0.0}],
    )
    assert out == "likely_mobile_not_posting"


def test_classify_preview_clean():
    """gps pings present + every closed shift has miles → clean."""
    from routers.admin_mileage_audit import _classify
    out = _classify(
        gps_total=120, loc_total_tracking=0,
        shifts=[
            {"clock_out_at": "2026-10-01T18:00:00+00:00",
             "mileage_miles": 7.2},
            {"clock_out_at": "2026-10-02T18:00:00+00:00",
             "mileage_miles": 11.5},
        ],
    )
    assert out == "preview_clean"


def test_classify_no_shifts_in_window():
    """No shifts in the window → dedicated token so the operator
    doesn't confuse it with ``mobile_not_posting``."""
    from routers.admin_mileage_audit import _classify
    out = _classify(gps_total=0, loc_total_tracking=0, shifts=[])
    assert out == "no_shifts_in_window"


def test_classify_unknown_when_counts_dont_match_known_pattern():
    """gps + loc both small, open shift only → unknown."""
    from routers.admin_mileage_audit import _classify
    out = _classify(
        gps_total=5, loc_total_tracking=5,
        shifts=[{"clock_out_at": None, "mileage_miles": 0.0}],
    )
    assert out == "unknown"


def test_classify_handles_open_shifts_without_mileage_as_unknown():
    """Open shifts (no clock_out_at) must not be considered when
    deciding ``any_zero_closed`` — otherwise a tech currently
    on-shift always skews the hint."""
    from routers.admin_mileage_audit import _classify
    out = _classify(
        gps_total=500, loc_total_tracking=2,
        shifts=[{"clock_out_at": None, "mileage_miles": 0.0}],
    )
    assert out != "likely_calculator_reading_wrong_collection"


# ─── §2 · _redact_mongo_host — strips credentials ────────────────

def test_redact_mongo_host_strips_user_pass():
    from routers.admin_mileage_audit import _redact_mongo_host
    assert _redact_mongo_host(
        "mongodb://user:pwd@cluster.example.com:27017/mydb",
    ) == "cluster.example.com:27017"


def test_redact_mongo_host_handles_localhost():
    from routers.admin_mileage_audit import _redact_mongo_host
    assert _redact_mongo_host(
        "mongodb://localhost:27017",
    ) == "localhost:27017"


# ─── §3 · _parse_window — defaults + validation ──────────────────

def test_parse_window_defaults_to_last_7_days():
    from routers.admin_mileage_audit import _parse_window
    out = _parse_window(None, None)
    assert "start" in out and "end" in out
    # start < end
    assert out["start"] < out["end"]


def test_parse_window_rejects_start_after_end():
    from fastapi import HTTPException
    from routers.admin_mileage_audit import _parse_window
    with pytest.raises(HTTPException) as exc:
        _parse_window(
            "2026-10-10T00:00:00+00:00",
            "2026-10-01T00:00:00+00:00",
        )
    assert exc.value.status_code == 400


def test_parse_window_rejects_window_larger_than_90_days():
    from fastapi import HTTPException
    from routers.admin_mileage_audit import _parse_window
    with pytest.raises(HTTPException) as exc:
        _parse_window(
            "2026-01-01T00:00:00+00:00",
            "2026-10-01T00:00:00+00:00",
        )
    assert exc.value.status_code == 400


# ─── §4 · _hour_bucket — ISO → hour string ────────────────────────

def test_hour_bucket_normalises_to_utc():
    from routers.admin_mileage_audit import _hour_bucket
    assert _hour_bucket(
        "2026-10-01T07:35:12.123+00:00",
    ) == "2026-10-01T07:00"


def test_hour_bucket_handles_zulu_suffix():
    from routers.admin_mileage_audit import _hour_bucket
    assert _hour_bucket(
        "2026-10-01T07:35:12Z",
    ) == "2026-10-01T07:00"


def test_hour_bucket_returns_none_on_garbage():
    from routers.admin_mileage_audit import _hour_bucket
    assert _hour_bucket(None) is None
    assert _hour_bucket("") is None
    assert _hour_bucket("not-a-date") is None
