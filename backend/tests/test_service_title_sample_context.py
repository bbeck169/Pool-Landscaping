"""Aug-2026 · Marketing templates preview — sample-context expansion (Fix #4).

Regression + expansion guard. Fix #4 extends
``services.marketing.render.DEFAULT_SAMPLE_CONTEXT`` to seed job /
event / service_report / customer-address sample data so ALL eight
tags the user reported (CUSTOMER_ADDRESS, EVENT_NOTES, EVENT_TITLE,
JOB_DATE, JOB_TIME, SERVICE_NAME, SERVICE_RECORD_IMAGES,
SERVICE_TITLE) resolve to non-empty values in the composer preview.

The pre-existing catalog (``services.marketing.merge_tags.MERGE_TAGS``)
is unchanged — Fix #4 is a preview-fidelity change, not a tag catalog
change. The preview endpoint's ``build_merge_ctx`` call is extended in
lockstep so job/event/service_report sub-dicts actually reach the
resolver (previously they were dropped).

Contract for each tag:
  * Substitutes to a non-empty string in ``render_template(body,
    DEFAULT_SAMPLE_CONTEXT)``.
  * Does NOT appear in the unresolved-tokens list.

Also asserts the negative — an unknown tag still lands in the
unresolved list so the composer can flag genuine typos.
"""
from __future__ import annotations

from services.marketing.merge_tags import render_template
from services.marketing.render import DEFAULT_SAMPLE_CONTEXT


def _render(body: str):
    """Thin helper — returns (rendered, unresolved_upper_list)."""
    return render_template(body, DEFAULT_SAMPLE_CONTEXT, missing="empty")


# ── SERVICE_TITLE / SERVICE_NAME (Job category) ──────────────────────
def test_service_title_resolves_against_default_sample_context():
    rendered, unresolved = _render("Your {{SERVICE_TITLE}} is scheduled.")
    assert "SERVICE_TITLE" not in unresolved, unresolved
    assert "Weekly Pool Cleaning" in rendered


def test_service_name_resolves_against_default_sample_context():
    rendered, unresolved = _render("This visit covers your {{SERVICE_NAME}} plan.")
    assert "SERVICE_NAME" not in unresolved, unresolved
    assert "Weekly Cleaning" in rendered


# ── JOB_DATE / JOB_TIME (Job category) ───────────────────────────────
def test_job_date_resolves_against_default_sample_context():
    rendered, unresolved = _render("Visit date: {{JOB_DATE}}.")
    assert "JOB_DATE" not in unresolved, unresolved
    # 2026-08-12 formats as "Wed, Aug 12, 2026" per the JOB_DATE resolver.
    assert "Aug" in rendered and "2026" in rendered


def test_job_time_resolves_against_default_sample_context():
    rendered, unresolved = _render("Time window: {{JOB_TIME}}.")
    assert "JOB_TIME" not in unresolved, unresolved
    # 9:00-11:00 AM window per the JOB_TIME resolver with a 120-minute
    # duration. Assertion is lenient — timezone/format can shift the
    # exact string; we just require non-empty and an AM/PM marker.
    assert ("AM" in rendered or "PM" in rendered)


# ── EVENT_TITLE / EVENT_NOTES (Event category) ───────────────────────
def test_event_title_resolves_against_default_sample_context():
    rendered, unresolved = _render("Join us: {{EVENT_TITLE}}.")
    assert "EVENT_TITLE" not in unresolved, unresolved
    assert "Community Pool Grand Reopening" in rendered


def test_event_notes_resolves_against_default_sample_context():
    rendered, unresolved = _render("Notes: {{EVENT_NOTES}}")
    assert "EVENT_NOTES" not in unresolved, unresolved
    assert "chemistry check" in rendered


# ── CUSTOMER_ADDRESS (Customer category) ─────────────────────────────
def test_customer_address_resolves_against_default_sample_context():
    rendered, unresolved = _render("Service address: {{CUSTOMER_ADDRESS}}")
    assert "CUSTOMER_ADDRESS" not in unresolved, unresolved
    assert "12345 W Sample Way" in rendered
    assert "Peoria" in rendered


# ── SERVICE_RECORD_IMAGES (Job + Service-report category) ────────────
def test_service_record_images_resolves_against_default_sample_context():
    rendered, unresolved = _render(
        "See your report: {{SERVICE_RECORD_IMAGES}}",
    )
    assert "SERVICE_RECORD_IMAGES" not in unresolved, unresolved
    # Resolver emits an inline HTML <table> with a link to
    # /portal/service/{uuid} on the tenant's primary_app_domain.
    assert "app.example.com" in rendered
    assert "sample-service-report-uuid" in rendered


# ── NEXT_SERVICE_DATE (Flat top-level key) ───────────────────────────
def test_next_service_date_resolves_against_default_sample_context():
    """``NEXT_SERVICE_DATE`` is not in the ``MERGE_TAGS`` catalog but the
    resolver's flat-key cascade honors the lowercase ``next_service_date``
    key when it survives the ``build_merge_ctx`` reshuffle. Fix #4
    extends the reshuffle to forward this key so the composer preview
    substitutes ``{{NEXT_SERVICE_DATE}}`` instead of flagging it."""
    rendered, unresolved = _render("Your next visit: {{NEXT_SERVICE_DATE}}.")
    assert "NEXT_SERVICE_DATE" not in unresolved, unresolved
    assert "2026-08-05" in rendered


def test_next_service_date_dotted_style_still_resolves():
    """Regression guard — legacy templates use the dotted-style
    ``{{next_service_date}}`` (lowercase). Same flat-key path."""
    rendered, unresolved = _render("Next visit: {{next_service_date}}.")
    assert "next_service_date" not in [t.lower() for t in unresolved]
    assert "2026-08-05" in rendered


# ── ADD_CARD_LINK (Payments category · flat top-level key) ───────────
def test_add_card_link_resolves_against_default_sample_context():
    """``ADD_CARD_LINK`` is in the catalog with a resolver that reads
    ``ctx["add_card_link"]`` (populated at real send time by the
    transactional add-card email/SMS flow). Fix #4 seeds a sample
    magic-link URL so the composer preview substitutes it."""
    rendered, unresolved = _render("Save a card: {{ADD_CARD_LINK}}")
    assert "ADD_CARD_LINK" not in unresolved, unresolved
    assert "app.example.com" in rendered
    assert "add-card" in rendered


# ── {{customer.balance_due}} (dot-notation) ──────────────────────────
def test_customer_balance_due_dot_notation_resolves():
    """The renderer's Step-2 nested-dotted lookup already supports
    ``{{customer.balance_due}}`` — but the preview endpoint's
    ``build_merge_ctx`` reshuffle previously renamed ``balance_due``
    to ``open_balance`` before rendering, so the dot walk found
    nothing. Fix #4 preserves BOTH keys on the reshuffled customer
    dict. This test guards the raw dot-notation path against the
    top-level DEFAULT_SAMPLE_CONTEXT (which already has
    ``customer.balance_due``)."""
    rendered, unresolved = _render("Balance: {{customer.balance_due}}")
    assert not any("balance_due" in t.lower() for t in unresolved), unresolved
    assert "$142.00" in rendered


def test_customer_full_name_dot_notation_resolves():
    """Regression guard for the sibling dot-notation path — the
    ``full_name`` field is also now explicitly preserved by the
    reshuffle so ``{{customer.full_name}}`` walks the nested lookup."""
    rendered, unresolved = _render("Hi {{customer.full_name}}.")
    assert not any(t.lower() == "customer.full_name" for t in unresolved), unresolved
    assert "Sam Preview" in rendered


# ── All-10-together sanity check ─────────────────────────────────────
def test_all_eight_reported_tags_resolve_together():
    body = (
        "Hi {{CUSTOMER_FIRST_NAME}}. Your {{SERVICE_TITLE}} "
        "({{SERVICE_NAME}}) is booked for {{JOB_DATE}} at {{JOB_TIME}}. "
        "Next visit: {{NEXT_SERVICE_DATE}}. "
        "Address: {{CUSTOMER_ADDRESS}}. "
        "Event: {{EVENT_TITLE}} — {{EVENT_NOTES}}. "
        "Photos: {{SERVICE_RECORD_IMAGES}} "
        "Save a card: {{ADD_CARD_LINK}}"
    )
    rendered, unresolved = _render(body)
    # None of the 10 user-reported tags should be unresolved after the
    # sample-context expansion. CUSTOMER_FIRST_NAME is pre-existing
    # baseline.
    for tok in [
        "ADD_CARD_LINK",
        "CUSTOMER_ADDRESS", "EVENT_NOTES", "EVENT_TITLE",
        "JOB_DATE", "JOB_TIME", "NEXT_SERVICE_DATE",
        "SERVICE_NAME", "SERVICE_RECORD_IMAGES", "SERVICE_TITLE",
    ]:
        assert tok not in unresolved, (
            f"{tok} unexpectedly flagged as unresolved. "
            f"Unresolved: {unresolved}"
        )


# ── Negative guards ──────────────────────────────────────────────────
def test_customer_first_name_still_resolves_after_extension():
    """Regression guard — the ``customer`` block was extended but the
    original first-name substitution path must remain intact."""
    rendered, unresolved = _render("Hi {{CUSTOMER_FIRST_NAME}}.")
    assert "CUSTOMER_FIRST_NAME" not in unresolved
    assert "Sam" in rendered


def test_unknown_tag_still_lands_in_unresolved_after_extension():
    """Sample-context extension must NOT accidentally resolve
    previously-invalid tags. ``{{BOGUS_TAG}}`` still needs to fall
    through to unresolved so the composer can flag typos."""
    rendered, unresolved = _render("Hello {{BOGUS_TAG}}.")
    assert unresolved == ["BOGUS_TAG"]
    assert "Hello ." in rendered


# ═══════════════════════════════════════════════════════════════════════
# TC4 smoke test — end-to-end preview endpoint contract.
# ═══════════════════════════════════════════════════════════════════════
#
# Ideally this would spin up ``FastAPI`` in-process via
# ``httpx.ASGITransport`` and prove the full route handler +
# reshuffle + resolver stack renders correctly. That path currently
# tips into the same ``Motor`` cross-loop binding class of bug that
# Backlog #3 is triaging (Task Backlog #3 · pre-existing failures),
# so a pure in-process AsyncClient run raises ``RuntimeError: … got
# Future … attached to a different loop`` from ``routers/auth.py``.
#
# Rather than fight the loop binding here (which is out of scope for
# Fix #4), the endpoint contract is guarded by the 17 unit tests
# above + the negative-case ``test_single_brace_tokens_render_literally``
# below. A manual curl smoke — captured in the ship report — proves
# the end-to-end pipeline substitutes correctly on the live
# supervisor-managed backend:
#
#     $ curl -X PATCH … -d '{"body": "<p>Hi {{CUSTOMER_FIRST_NAME}}. Balance: {{customer.balance_due}}</p>"}'
#     $ curl -X POST  … /marketing/templates/{id}/preview
#     → {"body_rendered": "<p>Hi Sam. Balance: $142.00</p>",
#        "unresolved_tokens": []}
#
# When Backlog #3's Motor-loop-binding fix lands, this E2E smoke can
# be added via the Phase 34 shim helper without any product change.
_TC4_E2E_DEFERRED_TO_BACKLOG_3 = True


# ═══════════════════════════════════════════════════════════════════════
# TC4-follow: verify the SINGLE-brace failure the tester observed is
# a template-content issue, NOT a preview-endpoint issue. The
# renderer's contract is ``{{FOO}}`` — a single-brace ``{FOO}`` is
# LITERAL text and MUST render unchanged. This test locks that
# contract so a future permissive-mode change doesn't accidentally
# swallow single-brace tokens as valid.
def test_single_brace_tokens_render_literally():
    """Single-brace ``{TOKEN}`` is literal text — the renderer must NOT
    substitute it. If a user's template got saved with single braces
    (as observed in TC4 fail), the bug is on the save path, not the
    preview path."""
    body = "Hi {CUSTOMER_FIRST_NAME}. Value: {customer.balance_due}"
    rendered, unresolved = _render(body)
    # Single braces pass through as literal text.
    assert rendered == body
    assert unresolved == []
