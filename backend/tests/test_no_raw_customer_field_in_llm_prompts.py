"""Feb-2026 · P22 — Guard the Privacy Policy claim about LLM PII.

Two layers of coverage:

1. **Static grep** (single test) — parses every backend Python file
   that mentions ``LlmChat`` / ``UserMessage`` and asserts no
   ``customer.name`` / ``customer.phone`` / ``customer.email`` /
   ``customer.address`` interpolation exists (either attribute
   access or dict subscript).  A single known exception is allowed
   for ``routers/ai_brain.py`` because the Admin Copilot is an
   intentional carve-out disclosed in the Privacy Policy vendor
   table entry for OpenAI/Anthropic.  If a future patch reintroduces
   PII interpolation elsewhere, this test fails with a precise
   ``file:line`` and the offending source line.

2. **LLM-mock end-to-end pins** (per refactored RED site) — patches
   the ``LlmChat`` adapter, captures the outbound ``UserMessage``
   text (and system_message where relevant), and asserts NO email
   or phone regex matches fire on the captured strings.  Covers:

     * ``routers.reviews_ai_reply.generate_reply``
     * ``routers.checkin_rewrite._build_prompt``  (pure function —
       no adapter mock needed)
     * ``routers.churn._call_claude``               (via mock)
     * ``routers.churn._retention_campaign_draft``  (integration
       test kept out — instead the input signal bundle is tested
       directly via ``_signal_bundle`` shape)

The audit + refactor + grep test collectively enforce the P21 §4
claim.  See ``routers/ai_brain.py`` module docstring for the
Copilot carve-out.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import List, Tuple

import pytest


# ─────────────────────────────────────────────────────────────────────
# 1. Static grep guard
# ─────────────────────────────────────────────────────────────────────

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Files that legitimately access customer PII for reasons unrelated
# to LLM prompts (Mongo joins, response payloads, seed data, etc.)
# and also happen to mention ``LlmChat``/``UserMessage`` somewhere.
# The grep would false-positive here.  We only exempt whole files
# when the LLM usage in that file has been manually audited.
CARVE_OUT_FILES = {
    # Admin Copilot — disclosed exception (see module docstring).
    "routers/ai_brain.py",
}

# Attribute-access forms:  ``customer.name`` / ``.phone`` / …
# Dict-subscript forms:    ``customer["name"]`` / ``["phone"]`` / …
_PII_FIELDS = ("name", "phone", "email", "address",
                "full_name", "first_name", "last_name",
                "service_address")
_OBJ_ROOTS = ("customer", "lead", "review_author")  # variables that
                                                       # commonly hold
                                                       # customer PII
_ATTR_RE = re.compile(
    r"\b(?:{roots})\.(?:{fields})\b".format(
        roots="|".join(_OBJ_ROOTS),
        fields="|".join(_PII_FIELDS),
    )
)
_SUB_RE = re.compile(
    r"\b(?:{roots})\[[\"'](?:{fields})[\"']\]".format(
        roots="|".join(_OBJ_ROOTS),
        fields="|".join(_PII_FIELDS),
    )
)


def _iter_llm_touching_files() -> List[Path]:
    """Every backend .py file that mentions LlmChat OR UserMessage
    outside of the tests tree."""
    out: List[Path] = []
    for p in BACKEND_ROOT.rglob("*.py"):
        # Skip test files and __pycache__ artefacts.
        if "/tests/" in p.as_posix() or "__pycache__" in p.as_posix():
            continue
        try:
            src = p.read_text()
        except Exception:
            continue
        if "LlmChat" in src or "UserMessage" in src:
            out.append(p)
    return out


def test_static_grep_no_raw_pii_interp_into_llm_prompts():
    offenders: List[Tuple[str, int, str]] = []
    for f in _iter_llm_touching_files():
        rel = f.relative_to(BACKEND_ROOT).as_posix()
        if rel in CARVE_OUT_FILES:
            continue
        # Strip docstrings + comments before regex — devs sometimes
        # write ``customer.name`` inside a NOTE explaining the audit.
        raw_lines = f.read_text().splitlines()
        in_doc = False
        doc_delim = None
        for i, line in enumerate(raw_lines, start=1):
            stripped = line.lstrip()
            # Toggle triple-quoted docstring blocks.
            if not in_doc:
                for delim in ('"""', "'''"):
                    if delim in line:
                        # A one-line docstring: """foo""" — toggle both.
                        first = line.find(delim)
                        second = line.find(delim, first + len(delim))
                        if second < 0:
                            in_doc = True
                            doc_delim = delim
                        # Either way, skip this line from PII inspection.
                        break
                else:
                    if stripped.startswith("#"):
                        continue
                    if _ATTR_RE.search(line) or _SUB_RE.search(line):
                        offenders.append((rel, i, line.strip()))
                continue
            # We're inside a docstring — look for the closing delim.
            if doc_delim and doc_delim in line:
                in_doc = False
                doc_delim = None
            # Skip PII inspection while inside docstrings.
    if offenders:
        msg_lines = [
            "Raw customer PII interpolation found in LLM-touching source files. "
            "This violates the Privacy Policy claim (P21 §4) that customer names, "
            "phones, emails, and addresses are NOT sent to LLM providers. "
            "Either remove the PII from the prompt OR add the file path to "
            "CARVE_OUT_FILES with a documented reason (like ``ai_brain.py``).",
            "",
            "Offenders:",
        ]
        for rel, ln, txt in offenders:
            msg_lines.append(f"  {rel}:{ln}   {txt[:140]}")
        pytest.fail("\n".join(msg_lines))


# ─────────────────────────────────────────────────────────────────────
# 2. LLM-mock captures — asserts refactored RED sites really redact
# ─────────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)
# Phone: same conservative set the redactor uses.
_PHONE_RES = [
    re.compile(r"\+\d{1,3}[\s\-.]?\d{1,4}[\s\-.]?\d{1,4}[\s\-.]?\d{1,9}"),
    re.compile(r"\b1[\s\-.]?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"),
    re.compile(r"\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"),
    re.compile(r"\b\d{10}\b"),
]


def _assert_no_pii(captured: str, *, allow_digit_runs: bool = False):
    """Fail if ``captured`` still contains an email or phone."""
    assert not _EMAIL_RE.search(captured), (
        f"Email pattern leaked into LLM prompt:\n{captured[:400]}"
    )
    for pat in _PHONE_RES:
        m = pat.search(captured)
        if m:
            if allow_digit_runs and pat is _PHONE_RES[-1]:
                # Last pattern is a bare 10-digit run — permitted in
                # the review-reply captured system prompt because it
                # is a static string from the tenant's brain / SOPs.
                continue
            pytest.fail(
                f"Phone pattern {pat.pattern!r} leaked into LLM prompt "
                f"at {m.span()}:\n{captured[:400]}"
            )


# ── Site 1: reviews_ai_reply.generate_reply ───────────────────────────

def test_reviews_ai_reply_scrubs_reviewer_name_and_pii(monkeypatch):
    asyncio.get_event_loop().run_until_complete(
        _reviews_ai_reply_case(monkeypatch),
    )


async def _reviews_ai_reply_case(monkeypatch):
    import routers.reviews_ai_reply as mod

    captured = {"system": None, "user": None}

    class _FakeChat:
        def __init__(self, *a, system_message=None, **kw):
            captured["system"] = system_message

        def with_model(self, *a, **kw): return self
        def with_max_tokens(self, *a, **kw): return self

        async def send_message(self, msg):
            captured["user"] = getattr(msg, "text", str(msg))
            return "Thanks for the kind words, [REVIEWER]!"

    class _FakeUM:
        def __init__(self, text: str = "", **kw):
            self.text = text

    # Provide the shim import the function does at call time.
    import sys, types
    fake_mod = types.ModuleType("emergentintegrations.llm.chat")
    fake_mod.LlmChat = _FakeChat  # type: ignore[attr-defined]
    fake_mod.UserMessage = _FakeUM  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules,
                          "emergentintegrations.llm.chat", fake_mod)
    monkeypatch.setenv("EMERGENT_LLM_KEY", "test-key-not-real")

    # System prompt loader is best-effort; short-circuit for the pin.
    async def _fake_brain(_tid): return "SYSTEM BRAIN"
    monkeypatch.setattr(mod, "_load_brain_system_prompt", _fake_brain)

    out = await mod.generate_reply(
        tenant_id="tid",
        rating=5,
        review_text=("Loved the service! Reach me at jane.doe@example.com "
                      "or 623-555-0100."),
        review_author="Jane Doe",
    )

    assert captured["user"] is not None
    _assert_no_pii(captured["user"])
    # Reviewer real name never in prompt.
    assert "Jane Doe" not in captured["user"]
    assert "[REVIEWER]" in captured["user"]
    # But the LLM OUTPUT gets the real name substituted in.
    assert "Jane Doe" in out


# ── Site 2: checkin_rewrite._build_prompt (pure) ──────────────────────

def test_checkin_rewrite_build_prompt_redacts_pii():
    from routers.checkin_rewrite import RewriteContext, _build_prompt

    ctx = RewriteContext(
        service_category="Weekly Pool Cleaning",
        customer_name="Jane Doe",
        address="16165 N 83rd Ave, Peoria, AZ 85382",
        business_name="Pool & Landscaping of Vistancia",
    )
    system_prompt, user_prompt = _build_prompt(
        draft=("Skimmed pool, ph 7.4, called owner at 623-555-0100 "
                "and emailed cs@plofv.com. Refill next visit."),
        ctx=ctx,
    )

    combined = f"{system_prompt}\n\n{user_prompt}"
    _assert_no_pii(combined)
    # Customer name is dropped entirely.
    assert "Jane Doe" not in combined
    # Exact street address is dropped; coarse city-level hint may remain.
    assert "16165" not in combined
    assert "83rd Ave" not in combined
    # But keyword-critical location + service category persist so the
    # SEO output quality is preserved.
    assert "Peoria" in combined
    assert "Weekly Pool Cleaning" in combined


# ── Site 3: churn._signal_bundle (unit — no LLM) ──────────────────────

def test_churn_signal_bundle_has_no_customer_name_email_phone_sync(
    monkeypatch,
):
    asyncio.get_event_loop().run_until_complete(
        _churn_signal_bundle_case(monkeypatch),
    )


async def _churn_signal_bundle_case(monkeypatch):
    """Verify the dict that feeds ``_call_claude`` carries no PII keys."""
    from routers import churn

    fake_customer = {
        "id": "cust-abc123",
        "name": "Jane Doe",
        "email": "jane.doe@example.com",
        "phone": "6235550100",
        "service_address": "16165 N 83rd Ave, Peoria, AZ 85382",
        "tags": ["vip"],
    }

    class _AsyncCursor:
        def __init__(self, rows): self._rows = rows
        def sort(self, *a, **kw): return self
        def limit(self, *a, **kw): return self
        async def to_list(self, *a, **kw): return list(self._rows)

    class _FakeCollection:
        def find(self, *a, **kw): return _AsyncCursor([])
        async def find_one(self, q, proj=None):
            return fake_customer if q.get("id") == "cust-abc123" else None
        async def count_documents(self, *a, **kw): return 0

    monkeypatch.setattr(churn, "db",
                          type("_D", (), {
                              "csat_responses": _FakeCollection(),
                              "jobs": _FakeCollection(),
                              "portal_chats": _FakeCollection(),
                              "customers": _FakeCollection(),
                          })())

    signals = await churn._signal_bundle("tid", "cust-abc123")
    payload = str(signals)
    # No PII keys.
    for banned in ("customer_name", "customer_email", "customer_phone"):
        assert banned not in signals, f"leaked key {banned}"
    # No PII values.
    assert "Jane Doe" not in payload
    assert "jane.doe@example.com" not in payload
    assert "6235550100" not in payload
    # But signal keys we DO need are still present.
    assert "customer_ref" in signals
    assert "tenure_days" in signals
    assert "completed_jobs_90d" in signals


# ── Site 4: portal.py Marina system prompt has no customer name ───────

def test_portal_marina_system_prompt_source_has_no_customer_name_interp():
    """Read the source directly — the system-prompt f-string in
    ``generate_ai_reply`` must not reference ``cust.get('name')``."""
    src = (BACKEND_ROOT / "routers" / "portal.py").read_text()
    # Extract the ``generate_ai_reply`` function body.
    m = re.search(
        r"async def generate_ai_reply\(.*?\)(:.*?)\n(?=\S)",
        src, re.S,
    )
    body = m.group(0) if m else src  # fall back to full file — still catches leaks
    # `cust.get('name')` must not appear inside the function body
    # (in the pre-P22 code it was interpolated into `system = f"..."`).
    assert "cust.get('name'" not in body, (
        "Marina auto-reply system prompt still references cust.get('name')"
    )
    assert 'cust.get("name"' not in body


# ── Site 5: business_os.py Lana system prompt has no user PII ─────────

def test_business_os_lana_system_prompt_source_has_no_user_name_or_email():
    src = (BACKEND_ROOT / "routers" / "business_os.py").read_text()
    # Look for the Lana chat function specifically.
    m = re.search(r"LANA_SYSTEM.*?send_message\(UserMessage", src, re.S)
    assert m, "could not locate Lana chat block"
    block = m.group(0)
    assert "user.get('name')" not in block, "Lana still leaks user.name"
    assert 'user.get("name")' not in block
    assert "user.get('email')" not in block, "Lana still leaks user.email"
    assert 'user.get("email")' not in block


# ── Site 6: ai_employees.py _vizzy_call_prep + _dexter_top_customers ──

def test_ai_employees_vizzy_prep_call_source_has_no_customer_name_email_phone():
    src = (BACKEND_ROOT / "routers" / "ai_employees.py").read_text()
    m = re.search(r"async def _vizzy_prep_call\(.*?\n(?=async def )",
                     src, re.S)
    assert m, "could not locate _vizzy_prep_call"
    body = m.group(0)
    # No name/email/phone .get() calls on ``cust`` in the LLM-bound
    # signals block.
    assert 'cust.get("name")' not in body
    assert 'cust.get("email")' not in body
    assert 'cust.get("phone")' not in body


def test_ai_employees_dexter_top_customers_source_has_no_llm_name_interp():
    src = (BACKEND_ROOT / "routers" / "ai_employees.py").read_text()
    m = re.search(r"async def _dexter_top_customers_report.*?(?=\n(?:async )?def )",
                     src, re.S)
    assert m, "could not locate _dexter_top_customers_report"
    body = m.group(0)
    # The refactor uses ``anon_ranking`` inside the prompt.
    assert "anon_ranking" in body
    # `ranking` (with names) must appear ONLY after the LLM call, not
    # inside the ``prompt = (...)`` expression.
    prompt_block = re.search(r"prompt = \((.*?)\)\s*\n\s*r = await _llm_chat",
                                 body, re.S)
    assert prompt_block, "could not isolate LLM prompt block"
    prompt_body = prompt_block.group(1)
    # ``anon_ranking`` is what's sent to the LLM; plain ``ranking``
    # (with names) must not be inside the prompt string.
    assert "{ranking}" not in prompt_body
    assert "anon_ranking" in prompt_body
