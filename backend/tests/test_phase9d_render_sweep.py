"""Phase 9D · Feb 2026 — Legacy render-engine sweep coverage.

Every send-time surface now delegates to
:func:`services.marketing.merge_tags.render_template`. This suite locks
the port in with golden-context byte-identity checks per feature area:

  · M2 (marketing_campaigns.render_body)          — email + SMS golden
  · M5c drips (marketing/render.render_template)  — email + SMS golden
  · Portal transactional (comm_tokens)            — email + SMS golden
  · Referral welcome (marketing/render)           — email + SMS golden
  · Review requests (M6, marketing/render)        — email + SMS golden
  · Dunning ladders (routers/dunning._render)     — email + SMS golden
  · Merge-tag catalog fallback (flat + flat-dotted)
  · Lint guard — grep-fails when a legacy substitution is
    reintroduced outside ``services/marketing/``.

Every "before" fixture below reproduces the pre-9D input verbatim
using the templates that shipped in the repo. The "after" assertions
freeze what the unified engine produces. Where the two engines
diverged intentionally (unresolved token behavior: literal → empty),
the divergence is documented in the assertion itself.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest


# ═══════════════════════════ M2 (marketing_campaigns) ═════════════════
def test_m2_campaign_email_golden():
    from services.marketing_campaigns import render_body
    tpl = ("Hi {first_name}, thanks for choosing {tenant_name}. "
            "See {customer.city} tips at {web_view_url}.")
    ctx = {
        "first_name": "Alex",
        "tenant_name": "Aquaterra",
        "customer": {"city": "Peoria"},
        "web_view_url": "https://x.example/w/abc",
    }
    out, missing = render_body(tpl, ctx)
    assert out == (
        "Hi Alex, thanks for choosing Aquaterra. See Peoria tips at "
        "https://x.example/w/abc."
    )
    assert missing == []


def test_m2_campaign_sms_golden_with_unresolved():
    """Documents the Phase 9D behavior change — a token that has NO
    resolver renders EMPTY (was: left verbatim). Downstream code
    already treated ``missing`` as the warning surface, not a value
    channel."""
    from services.marketing_campaigns import render_body
    tpl = "Hi {first_name}, use code {UNKNOWN_TOKEN}."
    ctx = {"first_name": "Alex"}
    out, missing = render_body(tpl, ctx)
    assert out == "Hi Alex, use code ."
    assert "UNKNOWN_TOKEN" in missing


# ═══════════════════════════ M5c drips (marketing/render) ═════════════
def test_m5c_drip_email_golden():
    from services.marketing.render import render_template
    tpl = ("Hi {{customer.first_name}}, your next visit is "
            "{{next_service_date}} — {{next_service_type}}.")
    ctx = {
        "customer": {"first_name": "Sam"},
        "next_service_date": "2026-08-05",
        "next_service_type": "Pool Cleaning",
    }
    out, missing = render_template(tpl, ctx)
    assert out == ("Hi Sam, your next visit is 2026-08-05 — Pool Cleaning.")
    assert missing == []


def test_m5c_drip_sms_golden():
    from services.marketing.render import render_template
    tpl = "{{tenant.name}}: next visit {{next_service_date}}. Reply STOP to opt out."
    ctx = {"tenant": {"name": "Aquaterra"},
            "next_service_date": "Fri Aug 5"}
    out, missing = render_template(tpl, ctx)
    assert out == "Aquaterra: next visit Fri Aug 5. Reply STOP to opt out."
    assert missing == []


# ═══════════════════════════ Portal transactional (comm_tokens) ═══════
def test_portal_transactional_email_golden():
    from services.comm_tokens import resolve_tokens
    tpl = ("Hi {{customer.first_name}}, invoice "
            "{{invoice.invoice_number}} for {{invoice.amount_due}} "
            "is ready. Pay: {{invoice.portal_link}}")
    ctx = {
        "customer.first_name": "Alex",
        "invoice.invoice_number": "INV-2026-00412",
        "invoice.amount_due": "$135.00",
        "invoice.portal_link": "https://portal.example.com/i/INV-2026-00412",
    }
    out = resolve_tokens(tpl, ctx)
    assert out == (
        "Hi Alex, invoice INV-2026-00412 for $135.00 is ready. "
        "Pay: https://portal.example.com/i/INV-2026-00412"
    )


def test_portal_transactional_sms_golden():
    from services.comm_tokens import resolve_tokens
    tpl = "{{company.name}}: invoice {{invoice.invoice_number}} paid — thanks!"
    ctx = {
        "company.name": "Aquaterra",
        "invoice.invoice_number": "INV-2026-00412",
    }
    out = resolve_tokens(tpl, ctx)
    assert out == "Aquaterra: invoice INV-2026-00412 paid — thanks!"


# ═══════════════════════════ Referral welcome (marketing/render) ══════
def test_referral_welcome_email_golden():
    from services.marketing.render import render_subject_and_body
    subject = "{{customer.first_name}}, a friend referred you to {{tenant.name}}"
    body = ("Welcome {{customer.first_name}}! You've been credited "
             "$25 towards your first service.")
    ctx = {"customer": {"first_name": "Alex"},
            "tenant": {"name": "Aquaterra"}}
    s, b, missing = render_subject_and_body(subject, body, ctx)
    assert s == "Alex, a friend referred you to Aquaterra"
    assert b == ("Welcome Alex! You've been credited $25 towards your "
                  "first service.")
    assert missing == []


def test_referral_credit_earned_sms_golden():
    from services.marketing.render import render_template
    tpl = "{{tenant.name}}: You earned $25 in credit — thanks for the referral!"
    ctx = {"tenant": {"name": "Aquaterra"}}
    out, missing = render_template(tpl, ctx)
    assert out == "Aquaterra: You earned $25 in credit — thanks for the referral!"
    assert missing == []


# ═══════════════════════════ Review requests (M6, marketing/render) ═══
def test_review_request_email_golden():
    from services.marketing.render import render_subject_and_body
    subject = "How was your visit with {{tech.first_name}}?"
    body = ("Hi {{customer.first_name}} — we hope {{tech.full_name}} "
             "took great care of you. Please share your feedback: "
             "{{review_request.public_url}}")
    ctx = {
        "customer": {"first_name": "Alex"},
        "tech": {"first_name": "Mike", "full_name": "Mike Rivera"},
        "review_request": {
            "public_url": "https://portal.example.com/reviews/r/abc123",
        },
    }
    s, b, missing = render_subject_and_body(subject, body, ctx)
    assert s == "How was your visit with Mike?"
    assert b == (
        "Hi Alex — we hope Mike Rivera took great care of you. "
        "Please share your feedback: "
        "https://portal.example.com/reviews/r/abc123"
    )
    assert missing == []


def test_review_request_sms_golden():
    from services.marketing.render import render_template
    tpl = "{{tenant.name}}: how was {{tech.first_name}}'s visit? {{review_request.public_url}}"
    ctx = {
        "tenant": {"name": "Aquaterra"},
        "tech": {"first_name": "Mike"},
        "review_request": {"public_url": "https://x.example/r/abc"},
    }
    out, missing = render_template(tpl, ctx)
    assert out == "Aquaterra: how was Mike's visit? https://x.example/r/abc"
    assert missing == []


# ═══════════════════════════ Dunning ladders ══════════════════════════
def test_dunning_pre_due_email_golden():
    """Locks the first ``DEFAULT_STAGES`` payload byte-identically to
    what ``str.format(**ctx)`` produced pre-Phase-9D."""
    from routers.dunning import _render, DEFAULT_STAGES
    stage = DEFAULT_STAGES[0]  # pre_due_3d
    ctx = {
        "customer_name": "Alex Reyes",
        "invoice_number": "abc12345",
        "invoice_total": "135.00",
        "due_date": "2026-08-15",
        "days_past_due": 0,
        "payment_link": "https://buy.stripe.com/test_abc",
        "tenant_name": "Aquaterra Pools",
        "tenant_phone": "(602) 555-0100",
    }
    subject = _render(stage["subject_template"], ctx)
    body = _render(stage["body_template"], ctx)
    sms = _render(stage["sms_template"], ctx)
    assert subject == "Reminder: invoice abc12345 due in 3 days"
    assert body == (
        "Hi Alex Reyes,\n\n"
        "Just a friendly reminder that invoice abc12345 for $135.00 is "
        "due on 2026-08-15.\n\n"
        "Pay online: https://buy.stripe.com/test_abc\n\n"
        "Thanks,\nAquaterra Pools"
    )
    assert sms == (
        "Aquaterra Pools: invoice abc12345 ($135.00) due 2026-08-15. "
        "Pay: https://buy.stripe.com/test_abc"
    )


def test_dunning_past_due_60d_sms_golden():
    from routers.dunning import _render, DEFAULT_STAGES
    stage = next(s for s in DEFAULT_STAGES if s["id"] == "past_due_60d")
    ctx = {
        "customer_name": "Alex Reyes",
        "invoice_number": "abc12345",
        "invoice_total": "135.00",
        "days_past_due": 62,
        "payment_link": "https://buy.stripe.com/test_abc",
        "tenant_name": "Aquaterra Pools",
        "tenant_phone": "(602) 555-0100",
    }
    sms = _render(stage["sms_template"], ctx)
    assert sms == (
        "Aquaterra Pools: your account is flagged for collections. "
        "Invoice abc12345 60d+ past due. Call (602) 555-0100."
    )


def test_dunning_unknown_token_renders_empty():
    """Behavior change (documented): ``_render`` used to leave
    unresolved single-brace tokens verbatim when ``.format()`` raised
    KeyError; now they render empty via the unified engine. This is
    the correct behavior — the operator sees a template with a typo
    render as gapped text, not as a Python ``KeyError`` swallowed
    silently."""
    from routers.dunning import _render
    tpl = "Hi {customer_name}, {NOT_A_TOKEN}!"
    ctx = {"customer_name": "Alex"}
    assert _render(tpl, ctx) == "Hi Alex, !"


# ═══════════════════════════ Merge-tag catalog fallback ═══════════════
def test_merge_tags_flat_key_fallback():
    from services.marketing.merge_tags import render_template
    out, missing = render_template(
        "Hi {{customer_name}}, invoice {{invoice_number}}.",
        {"customer_name": "Alex", "invoice_number": "INV-1"},
    )
    assert out == "Hi Alex, invoice INV-1."
    assert missing == []


def test_merge_tags_flat_dotted_fallback():
    from services.marketing.merge_tags import render_template
    out, missing = render_template(
        "Hi {{customer.first_name}}.",
        {"customer.first_name": "Alex"},   # FLAT-DOTTED key (comm_tokens ctx shape)
    )
    assert out == "Hi Alex."
    assert missing == []


# ═══════════════════════════ Lint guard ══════════════════════════════
_BACKEND = Path(__file__).resolve().parents[1]

# Files where legacy substitution patterns are LEGITIMATELY present:
#   * services/marketing/merge_tags.py — the canonical engine
#   * services/marketing/render.py     — thin adapter (docstring only)
#   * services/marketing_campaigns.py  — single-brace NORMALISER regex
#   * services/comm_tokens.py          — token catalog + extract_tokens
#   * routers/dunning.py               — single-brace NORMALISER regex
_ALLOW_LEGACY_SUB = {
    "services/marketing/merge_tags.py",
    "services/marketing/render.py",
    "services/marketing_campaigns.py",
    "services/comm_tokens.py",
    "routers/dunning.py",
}


def _all_python_files():
    for p in _BACKEND.rglob("*.py"):
        rel = str(p.relative_to(_BACKEND))
        if rel.startswith(("tests/", "venv/", "__pycache__/", "comms_seed/")):
            continue
        yield p, rel


def test_lint_no_stray_format_or_regex_substitution_on_templates():
    """Grep-fails if a NEW file introduces ``str.format(**`` on a
    variable named body/subject/text/template OR a raw ``{{...}}``
    substitution regex outside the allow-list."""
    format_pat = re.compile(
        r"\b(body|subject|text|html|template|content|message|msg)\s*\.format\s*\("
    )
    regex_sub_pat = re.compile(
        r"re\.compile\s*\(\s*r?[\"'][^\"']*\\\{\\\{"
    )
    violations = []
    for p, rel in _all_python_files():
        if rel in _ALLOW_LEGACY_SUB:
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in format_pat.finditer(src):
            line_no = src[:m.start()].count("\n") + 1
            violations.append(f"{rel}:{line_no}  .format() on template var")
        for m in regex_sub_pat.finditer(src):
            line_no = src[:m.start()].count("\n") + 1
            violations.append(f"{rel}:{line_no}  raw {{...}} substitution regex")
    assert not violations, (
        "Legacy inline substitution reintroduced — please route through "
        "services.marketing.merge_tags.render_template() instead.\n"
        + "\n".join(violations)
    )


def test_lint_guard_would_catch_a_reintroduction(tmp_path, monkeypatch):
    """Prove the lint guard fires when a violation is added. Writes a
    temporary Python file under a mocked backend root and re-runs the
    scanner logic against it."""
    fake_root = tmp_path / "backend"
    fake_root.mkdir()
    (fake_root / "routers").mkdir()
    (fake_root / "routers" / "bad.py").write_text(
        "def send(body, ctx):\n"
        "    return body.format(**ctx)\n",
        encoding="utf-8",
    )
    # Re-run the scanner against fake_root.
    format_pat = re.compile(
        r"\b(body|subject|text|html|template|content|message|msg)\s*\.format\s*\("
    )
    hits = []
    for p in fake_root.rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        if format_pat.search(src):
            hits.append(str(p.relative_to(fake_root)))
    assert hits == ["routers/bad.py"], (
        f"lint guard would MISS a reintroduction (hits={hits})"
    )
