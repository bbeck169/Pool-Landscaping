"""Phase COMM1 · Feb-2026 — Completion SMS template.

Pure unit tests — hit ``build_completion_sms_body`` directly, no DB
or HTTP. Also asserts that the router's dispatcher continues to
build the SAME portal link the pre-COMM1 SMS used, so we don't
silently drift the magic-link URL builder.
"""
from __future__ import annotations

import re

from services.completion_sms_template import build_completion_sms_body


PORTAL_LINK = "https://app.plofv.com/portal/service-reports?token=abc123"


def _render(**kw):
    return build_completion_sms_body(
        tenant=kw.get("tenant"),
        job=kw.get("job"),
        customer=kw.get("customer"),
        portal_link=kw.get("portal_link", PORTAL_LINK),
    )


# ═════════════════════════════════════════════════════════════════════
# Exact rendering
# ═════════════════════════════════════════════════════════════════════
def test_sample_rendering_matches_spec_exactly():
    body = _render(
        customer={"first_name": "Diego"},
        job={"title": "Weekly pool maintenance"},
        tenant={"name": "Pool & Landscaping of Vistancia"},
    )
    assert body == (
        "Hi Diego, your Weekly pool maintenance with "
        "Pool & Landscaping of Vistancia is complete! "
        "View your full report and photos here: "
        + PORTAL_LINK
    )


# ═════════════════════════════════════════════════════════════════════
# Redaction — no chemistry, no numbers-in-chemistry-context.
# ═════════════════════════════════════════════════════════════════════
def test_no_chemistry_readings_in_the_body():
    body = _render(
        customer={"first_name": "Diego"},
        job={"title": "Weekly pool maintenance"},
        tenant={"name": "AquaTerra"},
    )
    low = body.lower()
    for banned in ("ppm", "chlorine", "cyanuric", "alkalinity", "cya"):
        assert banned not in low, f"banned token {banned!r} leaked into SMS: {body}"
    # ``ph`` is a substring of ``phone``/``photos``/``pH``. Assert
    # against a stricter pattern that catches chemistry-context pH
    # mentions (e.g., "pH 7.4") without false-flagging "photos".
    assert not re.search(r"\bpH\s*[:=]?\s*\d", body)


# ═════════════════════════════════════════════════════════════════════
# Job title trimming
# ═════════════════════════════════════════════════════════════════════
def test_job_title_over_60_chars_is_trimmed():
    long_title = "Weekly pool cleaning + salt cell rebuild + booster pump repair visit"
    assert len(long_title) > 60
    body = _render(
        customer={"first_name": "Diego"},
        job={"title": long_title},
        tenant={"name": "Aqua"},
    )
    # Trim marker present, and no character from the original title
    # past position 59 leaks through unmodified.
    assert "…" in body
    # Extract the title from between "your " and " with " for the
    # exact-length assertion.
    m = re.search(r"your (.+?) with ", body)
    assert m
    trimmed_title = m.group(1)
    assert len(trimmed_title) == 60


# ═════════════════════════════════════════════════════════════════════
# First-name fallback chain
# ═════════════════════════════════════════════════════════════════════
def test_missing_first_name_falls_back_to_full_name_first_token():
    body = _render(
        customer={"name": "Sofia Vargas"},   # no first_name
        job={"title": "Weekly pool maintenance"},
        tenant={"name": "Aqua"},
    )
    assert body.startswith("Hi Sofia, your ")


def test_missing_full_name_falls_back_to_there():
    body = _render(
        customer={},                          # nothing at all
        job={"title": "Weekly pool maintenance"},
        tenant={"name": "Aqua"},
    )
    assert body.startswith("Hi there, your ")


def test_first_name_takes_precedence_over_full_name():
    body = _render(
        customer={"first_name": "Ana", "name": "Ana Martinez"},
        job={"title": "Weekly pool maintenance"},
        tenant={"name": "Aqua"},
    )
    assert body.startswith("Hi Ana, your ")


def test_first_name_field_with_full_string_uses_first_token_only():
    body = _render(
        customer={"first_name": "Ana Martinez"},   # tenant sloppily stored full name in first_name
        job={"title": "Weekly pool maintenance"},
        tenant={"name": "Aqua"},
    )
    assert body.startswith("Hi Ana, your ")


# ═════════════════════════════════════════════════════════════════════
# Multi-tenant — no hard-coded business name.
# ═════════════════════════════════════════════════════════════════════
def test_multi_tenant_business_name_is_per_tenant():
    b1 = _render(customer={"first_name": "Diego"},
                  job={"title": "Weekly pool maintenance"},
                  tenant={"name": "Alpha Pools"})
    b2 = _render(customer={"first_name": "Diego"},
                  job={"title": "Weekly pool maintenance"},
                  tenant={"name": "Beta Landscape"})
    assert "with Alpha Pools is complete!"    in b1
    assert "with Beta Landscape is complete!" in b2
    assert b1 != b2


# ═════════════════════════════════════════════════════════════════════
# Portal-link builder regression guard.
#
# Confirms the router-side dispatcher still builds the same
# ``{APP_PUBLIC_URL}/portal/service-reports`` link the pre-COMM1
# SMS used — if that builder ever drifts, this test surfaces the
# change with a targeted assertion.
# ═════════════════════════════════════════════════════════════════════
def test_completion_sms_dispatcher_portal_link_shape_unchanged():
    import re as _re
    from pathlib import Path
    src = Path("/app/backend/routers/service_reports.py").read_text()
    # The dispatcher builds ``f"{app_url}/portal/service-reports"``.
    assert _re.search(
        r'app_url\s*=\s*_os_task_u\.environ\.get\("APP_PUBLIC_URL"',
        src,
    ), "APP_PUBLIC_URL lookup missing from completion-SMS dispatcher"
    assert 'portal_link = f"{app_url}/portal/service-reports"' in src, (
        "portal_link shape changed — regression guard on the URL builder"
    )
    # Ensure the new helper is wired in.
    assert "build_completion_sms_body(" in src, (
        "completion-SMS dispatcher no longer calls "
        "build_completion_sms_body — Phase COMM1 regression"
    )
