"""Feb-2026 · Soshie · Moderation gate (regex-only) tests."""
from __future__ import annotations

from services.soshie.moderation import moderate


def test_clean_text_returns_no_flags():
    r = moderate("Fresh pool cleaning happening today across Vistancia.")
    assert r["clean"] is True
    assert r["flags"] == []


def test_brand_dont_say_phrase_flags():
    r = moderate("We're the best pool service in Phoenix",
                    dont_say=["best"])
    assert not r["clean"]
    assert any(f["type"] == "phrase" and f["match"] == "best"
                for f in r["flags"])
    # Source labels the flag to brand_brain.dont_say.
    assert any(f["source"] == "brand_brain.dont_say"
                for f in r["flags"])


def test_banned_phrase_flags():
    r = moderate("Our results are guaranteed",
                    dont_say=[])
    assert not r["clean"]
    assert any(f["type"] == "phrase" and f["match"].lower() == "guaranteed"
                for f in r["flags"])


def test_pii_email_flags():
    r = moderate("Contact john@example.com to schedule",
                    dont_say=[])
    assert not r["clean"]
    assert any(f["type"] == "pii" and f["source"] == "email"
                for f in r["flags"])


def test_pii_phone_flags():
    r = moderate("Call us at (623) 555-1212", dont_say=[])
    assert any(f["type"] == "pii" and f["source"] == "phone"
                for f in r["flags"])


def test_case_insensitive_matching():
    r = moderate("SCAM alert — see our pricing",
                    dont_say=[])
    # "scam" is in BANNED_PHRASES.
    assert not r["clean"]
    assert any(f["match"] == "scam" for f in r["flags"])
