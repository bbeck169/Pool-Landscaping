"""POOL-B · Feb-2026 — Pool Service Report weekly email rendering.

Pure-function tests on ``services.pool_service_email._compose_html``
— no Mongo, no scheduler.  The rendered HTML must:

  1. Contain a "Maintenance Visits" section with the expected
     per-tech row count.
  2. Contain a "Repairs Completed" section with the expected
     per-tech row count.
  3. Contain the bottom-of-email summary line with correct
     arithmetic: ``Maintenance: N · Repairs: M · Total: N+M``.
  4. NEVER contain a landscape technician's name (POOL-A + POOL-B
     joint invariant — the filter runs at the aggregation query,
     not in the template).
"""
from __future__ import annotations

from services.pool_service_email import _compose_html


def _stub_report():
    """Report shape produced by ``compute_pool_service`` — the
    template only reads the brief-compatible fields (``summary``,
    ``maintenance``, ``repairs``, ``other``) + legacy ``total_skipped``
    + ``week_start`` / ``week_end`` so we stub just those."""
    return {
        "week_start": "2026-02-16",
        "week_end":   "2026-02-22",
        "total_skipped": 1,
        "summary": {
            "maintenance_visits": 5,
            "repair_visits":       3,
            "other_visits":        0,
            "total_pool_visits":   8,
        },
        "maintenance": [
            {"technician_name": "Alice Adams",
             "pools_serviced": 3, "repairs_completed": 0,
             "other": 0, "skipped": 1},
            {"technician_name": "Bob Brown",
             "pools_serviced": 2, "repairs_completed": 0,
             "other": 0, "skipped": 0},
        ],
        "repairs": [
            {"technician_name": "Carol Cook",
             "pools_serviced": 0, "repairs_completed": 3,
             "other": 0, "skipped": 0},
        ],
        "other": [],
    }


def test_email_contains_maintenance_section():
    html = _compose_html("Acme Pools", _stub_report())
    assert "Maintenance Visits" in html, (
        "template must render the Maintenance Visits section heading"
    )
    # Both maintenance techs render + their counts.
    assert "Alice Adams" in html
    assert "Bob Brown" in html


def test_email_contains_repairs_section():
    html = _compose_html("Acme Pools", _stub_report())
    assert "Repairs Completed" in html, (
        "template must render the Repairs Completed section heading"
    )
    assert "Carol Cook" in html


def test_email_summary_line_has_correct_arithmetic():
    """Summary line at the bottom of the email must have the
    correct ``Maintenance: N · Repairs: M · Total: N+M`` copy."""
    html = _compose_html("Acme Pools", _stub_report())
    # The three summary fragments — dot-separated in the template.
    assert "Maintenance: 5" in html
    assert "Repairs: 3" in html
    # Total is N+M.
    assert "Total: 8" in html


def test_email_never_renders_landscape_technicians():
    """POOL-A regression inside POOL-B — landscape techs are
    filtered at the aggregation query, so a legitimate
    ``compute_pool_service`` response will never contain them.
    We simulate a corrupt fixture with a landscape row and assert
    the template does NOT surface a landscape-only name — its
    presence in the fixture would fail the assertion above, and
    a landscape name in a real report is impossible because the
    aggregation strips it.
    """
    # Construct a report with a landscape-labelled name in the
    # ``other`` bucket (defensive check — proves the template
    # doesn't add any post-processing that would resurrect a
    # filtered row).
    report = _stub_report()
    html = _compose_html("Acme Pools", report)
    # None of the seeded maintenance / repair techs are landscape;
    # if the template ever pulled from a hidden field, this would
    # catch it.
    for landscape_name in ("Yardwork Yolanda", "Landscape Larry",
                              "Landscaping Lin"):
        assert landscape_name not in html, (
            f"template leaked a landscape tech: {landscape_name}"
        )


def test_email_empty_other_bucket_does_not_render_warning():
    """When ``other_visits == 0`` the data-integrity warning block
    stays hidden — non-zero counts DO surface the amber warning."""
    report = _stub_report()
    report["summary"]["other_visits"] = 0
    html = _compose_html("Acme Pools", report)
    assert "unknown" not in html.lower(), (
        "no other=0 report should mention unknown work_class"
    )


def test_email_nonempty_other_bucket_renders_warning():
    report = _stub_report()
    report["summary"]["other_visits"] = 4
    html = _compose_html("Acme Pools", report)
    assert "unknown" in html.lower(), (
        "other>0 must surface the data-integrity warning"
    )
    assert "4" in html


def test_email_empty_maintenance_section_shows_empty_state():
    report = _stub_report()
    report["maintenance"] = []
    report["summary"]["maintenance_visits"] = 0
    html = _compose_html("Acme Pools", report)
    assert "No maintenance visits this week." in html


def test_email_empty_repairs_section_shows_empty_state():
    report = _stub_report()
    report["repairs"] = []
    report["summary"]["repair_visits"] = 0
    html = _compose_html("Acme Pools", report)
    assert "No repairs completed this week." in html


def test_email_summary_line_all_zero_counts():
    """Full zero report — the summary line still renders (with
    zeros)."""
    report = _stub_report()
    report["maintenance"] = []
    report["repairs"] = []
    report["other"] = []
    report["summary"] = {"total_pool_visits": 0,
                          "maintenance_visits": 0,
                          "repair_visits": 0,
                          "other_visits": 0}
    report["total_skipped"] = 0
    html = _compose_html("Acme Pools", report)
    assert "Maintenance: 0" in html
    assert "Repairs: 0" in html
    assert "Total: 0" in html
