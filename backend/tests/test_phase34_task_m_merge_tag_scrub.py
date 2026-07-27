"""Phase 34 · Task M · Feb-2026 — merge-tag rendering regression.

Pins two invariants:

1. The canonical ``services.marketing.merge_tags.render_template``
   NEVER leaves a ``{{TAG}}`` literal in its output. Unknown tags
   render as empty; known tags with data render to their value.

2. The ``services.email.resend_adapter._scrub_leftover_tags`` safety
   net catches anything that bypasses the renderer. Even a bare
   HTML string with ``{{UNKNOWN_TAG}}`` embedded is stripped to empty
   before reaching Resend.

If either regresses, a customer's inbox will show literal
``{{SERVICE_RECORD_IMAGES}}`` (etc.) — the exact bug this task fixes.
"""
from __future__ import annotations

from services.marketing.merge_tags import render_template
from services.email.resend_adapter import _scrub_leftover_tags


SERVICE_COMPLETED_BODY = (
    "{{SERVICE_RECORD_IMAGES}}\n"
    "Hi {{customer.first_name}}, We just wrapped up your {{EVENT_TITLE}} "
    "visit {{CUSTOMER_ADDRESS}}.\n"
    "{{JOB_DATE}}{{JOB_TIME}}\n"
    "{{EVENT_NOTES}}\n"
    "View Your Account\n"
    "{{CUSTOMER_PORTAL_LINK}}\n"
    "The {{tenant.name}} team"
)


def _has_leftover_tags(text: str) -> bool:
    return "{{" in text or "}}" in text


# ══════════════════════════════════════════════════════════════════════
# 1 · Canonical renderer never leaks {{TAG}} literals
# ══════════════════════════════════════════════════════════════════════
def test_render_never_leaks_literal_tags_flat_ctx():
    """Even with a nearly-empty ctx, the renderer replaces every
    ``{{TAG}}`` with either a value or empty string."""
    ctx = {"customer.first_name": "Alex"}
    out, _ = render_template(SERVICE_COMPLETED_BODY, ctx)
    assert not _has_leftover_tags(out), (
        f"leftover {{{{TAG}}}} in rendered output:\n{out!r}"
    )
    # Positive: first name did resolve.
    assert "Alex" in out


def test_render_never_leaks_literal_tags_nested_ctx():
    """With a rich nested ctx that resolvers understand, the same
    template renders every registered tag to a real value AND still
    leaks no ``{{TAG}}`` literals."""
    ctx = {
        "customer": {
            "first_name": "Alex",
            "address": "123 Main",
            "city": "Peoria",
            "state": "AZ",
            "zip": "85383",
        },
        "tenant": {"name": "Pool & Landscaping of Vistancia"},
        "event": {
            "title": "Weekly Pool Service",
            "date": "2026-02-15",
            "notes": "Skimmed heavy today",
        },
        "job": {
            "scheduled_date": "2026-02-15",
            "scheduled_start": "2026-02-15T14:00:00Z",
            "service_type": "Pool Cleaning",
        },
    }
    out, _ = render_template(SERVICE_COMPLETED_BODY, ctx)
    assert not _has_leftover_tags(out), (
        f"leftover {{{{TAG}}}} in rendered output:\n{out!r}"
    )
    # Positive: nested resolvers fire correctly.
    assert "Weekly Pool Service" in out
    assert "Pool & Landscaping of Vistancia" in out


# ══════════════════════════════════════════════════════════════════════
# 2 · Safety net catches anything that bypassed the renderer
# ══════════════════════════════════════════════════════════════════════
def test_resend_final_scrub_strips_unknown_leftover_tags():
    """If a caller somehow feeds raw ``{{TAG}}`` HTML into the adapter
    (bypassing the renderer), the final-scrub pass MUST strip them
    before the payload is handed to Resend."""
    subject = "Your service is done, {{customer.first_name}}!"
    html = (
        "<p>Hello {{customer.first_name}}, "
        "here is {{SOME_TYPO_TAG}} and {{another.bogus}}.</p>"
    )
    safe_subject, safe_html, missing = _scrub_leftover_tags(subject, html)

    assert not _has_leftover_tags(safe_subject), safe_subject
    assert not _has_leftover_tags(safe_html), safe_html
    # The safety net reports every stripped/unresolved token so ops
    # can grep the log and fix the source template.
    joined = ",".join(missing).lower()
    assert "some_typo_tag" in joined or "SOME_TYPO_TAG".lower() in joined
    assert "another.bogus" in joined or "another".lower() in joined


def test_scrub_is_idempotent_on_clean_html():
    """A payload with no leftover tags passes through unchanged."""
    subject = "Hello Alex"
    html = "<p>Nothing to see here.</p>"
    s, h, missing = _scrub_leftover_tags(subject, html)
    assert s == subject
    assert h == html
    assert missing == []
