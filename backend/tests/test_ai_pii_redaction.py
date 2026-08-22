"""Feb-2026 · P22 — Unit tests for `services.ai.pii_redactor`.

Backs the Privacy Policy claim (P21 §4): "we do NOT send customer
names, addresses, or phone numbers to LLM providers."  This module
supplies the defensive helper.  Sister tests in
``test_no_raw_customer_field_in_llm_prompts.py`` guard the *usage*
of the helper across the LLM call-site inventory.
"""
from __future__ import annotations

from services.ai.pii_redactor import (
    EMAIL_TOKEN, PHONE_TOKEN, ADDRESS_TOKEN, redact_pii,
)


# ─── Email ────────────────────────────────────────────────────────────

class TestRedactEmails:
    def test_simple_email(self):
        out = redact_pii("Contact us at cs@plofv.com today")
        assert "cs@plofv.com" not in out
        assert EMAIL_TOKEN in out

    def test_multiple_emails(self):
        out = redact_pii("Send to a@b.com and also c.d@example.co.uk")
        assert "a@b.com" not in out
        assert "c.d@example.co.uk" not in out
        assert out.count(EMAIL_TOKEN) == 2

    def test_plus_addressing(self):
        out = redact_pii("Route: foo+bar@example.com")
        assert "foo+bar@example.com" not in out
        assert EMAIL_TOKEN in out

    def test_email_with_digits_in_local_part(self):
        out = redact_pii("tech.42@company.io")
        assert "tech.42@company.io" not in out
        assert EMAIL_TOKEN in out


# ─── Phone ────────────────────────────────────────────────────────────

class TestRedactPhones:
    def test_us_parens_dash(self):
        assert PHONE_TOKEN in redact_pii("Call (623) 555-0100 today")

    def test_us_dash_only(self):
        assert PHONE_TOKEN in redact_pii("Call 623-555-0100 today")

    def test_us_dot_separator(self):
        assert PHONE_TOKEN in redact_pii("Number: 623.555.0100")

    def test_us_contiguous_10digit(self):
        out = redact_pii("Number: 6235550100 direct")
        assert "6235550100" not in out
        assert PHONE_TOKEN in out

    def test_us_leading_one(self):
        out = redact_pii("Call 1-623-555-0100 direct")
        assert "1-623-555-0100" not in out
        assert PHONE_TOKEN in out

    def test_e164_us(self):
        out = redact_pii("Ping +1 623 555 0100 please")
        assert "+1 623 555 0100" not in out
        assert PHONE_TOKEN in out

    def test_e164_international(self):
        out = redact_pii("UK line +447700900123")
        assert "+447700900123" not in out
        assert PHONE_TOKEN in out

    def test_us_spaces(self):
        assert PHONE_TOKEN in redact_pii("Number: 623 555 0100")

    def test_multiple_phones(self):
        out = redact_pii("First 623-555-0100 second 480-555-0200")
        assert out.count(PHONE_TOKEN) == 2


# ─── Combined ─────────────────────────────────────────────────────────

class TestRedactCombined:
    def test_email_and_phone(self):
        out = redact_pii("Ping cs@plofv.com or call 623-555-0100")
        assert EMAIL_TOKEN in out
        assert PHONE_TOKEN in out
        assert "cs@plofv.com" not in out
        assert "623-555-0100" not in out

    def test_free_text_stays_untouched(self):
        text = ("The pool chemistry looked good. pH 7.4, free "
                "chlorine 3.0 ppm. Recommend adding CYA next visit.")
        assert redact_pii(text) == text

    def test_short_numeric_run_ignored(self):
        # SKU / job ID / order number — must NOT be flagged as phone.
        text = "Job #1234 sku ABC-5678 water reading 7.4"
        out = redact_pii(text)
        assert "1234" in out
        assert "5678" in out
        assert PHONE_TOKEN not in out


# ─── Address (explicit only — no auto-detect) ─────────────────────────

class TestRedactAddress:
    def test_explicit_address_scrubbed(self):
        text = "Serviced pool at 16165 N 83rd Ave, Peoria, AZ 85382 today"
        out = redact_pii(text,
                            address_fields=["16165 N 83rd Ave, Peoria, AZ 85382"])
        assert "16165 N 83rd Ave" not in out
        assert ADDRESS_TOKEN in out

    def test_address_case_insensitive(self):
        text = "at 16165 n 83rd ave, peoria today"
        out = redact_pii(text,
                            address_fields=["16165 N 83RD AVE, Peoria"])
        assert "16165" not in out
        assert ADDRESS_TOKEN in out

    def test_no_autodetect_when_address_fields_empty(self):
        # We deliberately do NOT auto-detect address strings — false
        # positives on service notes are too high.
        text = "Serviced pool at 16165 N 83rd Ave, Peoria, AZ 85382 today"
        out = redact_pii(text)
        # ADDRESS_TOKEN must not appear when caller didn't opt in.
        assert ADDRESS_TOKEN not in out
        # (Phone regex may catch the zip-adjacent 10-digit run —
        # this is a known trade-off. Verify the street portion is
        # otherwise intact.)
        assert "N 83rd Ave" in out

    def test_empty_address_field_skipped(self):
        text = "Serviced pool today"
        out = redact_pii(text, address_fields=["", None, "   ", "abc"])
        assert out == text  # no changes


# ─── Edge cases ───────────────────────────────────────────────────────

class TestRedactEdgeCases:
    def test_none_input(self):
        assert redact_pii(None) == ""

    def test_empty_input(self):
        assert redact_pii("") == ""

    def test_non_string_coerced(self):
        # Not standard usage but must not crash.
        assert redact_pii(12345) == "12345"  # coerced via str, short so no phone regex match

    def test_leading_trailing_whitespace_preserved(self):
        text = "  cs@plofv.com  "
        out = redact_pii(text)
        assert out.startswith("  ") and out.endswith("  ")
        assert EMAIL_TOKEN in out
