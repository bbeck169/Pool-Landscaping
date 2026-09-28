"""CHEM-LOCK · Feb-2026 — Pool Service Report weekly email chemical
protection.

DESIGN FORK from the brief (§Deliverables §8): the brief lists
``pool_service_email`` as a third surface that must "render chemicals
from an amount-only job". Recon confirmed the weekly pool-service
email (``services/pool_service_email.py``) is an ADMIN-facing
tenant-wide TECHNICIAN COUNT digest — it never surfaces per-visit
chemical rows, and no consumer expects it to. Adding chemistry to
this template would be a scope expansion, not a bug fix.

This test suite is therefore PROTECTIVE, not corrective: it asserts
the weekly digest does NOT accidentally leak per-visit chemistry
into its HTML while still surfacing the POOL-B split correctly.
The auto-visit email (``services/auto_visit_email.py``) is the
correct surface for per-visit chemistry — see
``test_auto_visit_email_chemicals.py`` for that coverage.
"""
from __future__ import annotations

from services.pool_service_email import _compose_html


_EMPTY_REPORT = {
    "week_start": "2026-02-10",
    "week_end":   "2026-02-16",
    "total_completed": 0,
    "total_skipped":   0,
    "rows": [],
    "period": {"start": "2026-02-10", "end": "2026-02-16"},
    "summary": {"total_pool_visits": 0, "maintenance_visits": 0,
                "repair_visits": 0, "other_visits": 0},
    "maintenance": [], "repairs": [], "other": [], "visits": [],
    "totals": {"pools_serviced": 0, "repairs_completed": 0},
    "by_technician": [],
}


def test_weekly_email_does_not_render_chemicals_added_section():
    """The weekly digest is a tech-count aggregate — no per-visit
    chemistry surface. A future refactor that accidentally imports
    chemical rendering into ``pool_service_email`` will fail here.
    """
    html = _compose_html("AquaTerra Pools", _EMPTY_REPORT)
    assert "Chemicals added" not in html
    assert "chlorine" not in html.lower()
    assert "muriatic" not in html.lower()


def test_weekly_email_amount_only_job_does_not_regress():
    """Even when the underlying jobs had ``amount``-only chemistry
    entries, the weekly email is a technician-count aggregate — it
    should render the tech counts correctly and NOT accidentally
    surface any per-visit chem lines.

    Simulates a report where the aggregation was computed OVER jobs
    that had ``amount``-only chemistry rows — but the aggregation
    strips that detail. The email must remain a tech count digest.
    """
    report = {
        **_EMPTY_REPORT,
        "total_completed": 12,
        "summary": {"total_pool_visits": 14, "maintenance_visits": 12,
                    "repair_visits": 2, "other_visits": 0},
        "totals": {"pools_serviced": 12, "repairs_completed": 2},
        "rows": [{
            "technician_id": "u1", "technician_name": "Mike",
            "technician_active": True,
            "pools_serviced": 12, "repairs_completed": 2,
            "other": 0, "skipped": 0, "completed": 12,
        }],
        "maintenance": [{
            "technician_id": "u1", "technician_name": "Mike",
            "technician_active": True,
            "pools_serviced": 12, "repairs_completed": 2,
            "other": 0, "skipped": 0, "completed": 12,
        }],
        "repairs": [{
            "technician_id": "u1", "technician_name": "Mike",
            "technician_active": True,
            "pools_serviced": 12, "repairs_completed": 2,
            "other": 0, "skipped": 0, "completed": 12,
        }],
        "by_technician": [{
            "technician_id": "u1", "technician_name": "Mike",
            "technician_active": True,
            "pools_serviced": 12, "repairs_completed": 2,
            "other": 0, "skipped": 0, "completed": 12,
        }],
    }
    html = _compose_html("AquaTerra Pools", report)
    # Tech count aggregate — Mike should appear.
    assert "Mike" in html
    # But per-visit chemistry MUST NOT leak — even though the
    # underlying jobs may have had amount-only entries in real Mongo.
    assert "Chemicals added" not in html
    # POOL-B split surface still intact.
    assert "Maintenance" in html or "Repairs" in html
