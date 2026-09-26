"""QV-service · Feb-2026 — User-Agent classifier tests.

Table-driven coverage for :func:`services.ua_class.classify_ua`.
Fifteen real-world User-Agent strings covering all six positive
classes plus the ``"Other"`` fallback bucket (Edge, Opera, curl,
in-app WebView, empty).
"""
from __future__ import annotations

import pytest

from services.ua_class import classify_ua, UA_CLASSES


# (name, user_agent, expected_class)
_CASES = [
    # ── iPhone Safari (WebKit — native + CriOS/FxiOS/EdgiOS all
    #    still WebKit under the hood, so all classify as iPhone) ──
    (
        "iphone_safari_16",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.6 Mobile/15E148 Safari/604.1",
        "iPhone Safari",
    ),
    (
        "iphone_chrome_crios",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "CriOS/121.0.6167.101 Mobile/15E148 Safari/604.1",
        "iPhone Safari",
    ),
    (
        "iphone_firefox_fxios",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "FxiOS/121.0 Mobile/15E148 Safari/605.1.15",
        "iPhone Safari",
    ),

    # ── iPad Safari (iPad rule wins over Safari) ────────────────
    (
        "ipad_safari_pro",
        "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1",
        "iPad Safari",
    ),

    # ── Android Chrome ──────────────────────────────────────────
    (
        "android_chrome_pixel",
        "Mozilla/5.0 (Linux; Android 14; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Mobile Safari/537.36",
        "Android Chrome",
    ),
    (
        "android_chrome_samsung",
        "Mozilla/5.0 (Linux; Android 13; SM-S911B) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36",
        "Android Chrome",
    ),

    # ── Android WebView (in-app browser) → Other ────────────────
    (
        "android_webview",
        "Mozilla/5.0 (Linux; Android 13; SM-S911B; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36",
        "Other",
    ),

    # ── Desktop Chrome (macOS + Windows) ────────────────────────
    (
        "desktop_chrome_macos",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36",
        "Desktop Chrome",
    ),
    (
        "desktop_chrome_windows",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36",
        "Desktop Chrome",
    ),

    # ── Desktop Safari (Safari on macOS, NOT Chrome) ────────────
    (
        "desktop_safari_macos",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.2 Safari/605.1.15",
        "Desktop Safari",
    ),

    # ── Desktop Firefox ─────────────────────────────────────────
    (
        "desktop_firefox_macos",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) "
        "Gecko/20100101 Firefox/122.0",
        "Desktop Firefox",
    ),
    (
        "desktop_firefox_windows",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) "
        "Gecko/20100101 Firefox/122.0",
        "Desktop Firefox",
    ),

    # ── "Other" bucket ──────────────────────────────────────────
    (
        "desktop_edge_windows",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
        "Other",
    ),
    (
        "desktop_opera",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36 OPR/106.0.0.0",
        "Other",
    ),
    (
        "curl",
        "curl/8.4.0",
        "Other",
    ),
    (
        "googlebot",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Other",
    ),
    (
        "empty_string",
        "",
        "Other",
    ),
    (
        "whitespace_only",
        "   ",
        "Other",
    ),
]


@pytest.mark.parametrize("name,ua,expected", _CASES)
def test_classify_ua_table_driven(name, ua, expected):
    got = classify_ua(ua)
    assert got == expected, (
        f"{name}: expected {expected!r}, got {got!r} "
        f"for UA={ua!r}"
    )


def test_none_input_returns_other():
    assert classify_ua(None) == "Other"


def test_return_is_always_a_declared_class():
    """Whatever weird input we feed, the result MUST be one of the
    declared classes so downstream persistence never carries a
    surprise sentinel."""
    inputs = [None, "", "  ", "garbage nonsense",
                "Mozilla/5.0 (Unknown OS) Custom/1.0",
                "\x00\x01\x02", "iPhone Firefox iPad wat"]
    for ua in inputs:
        assert classify_ua(ua) in UA_CLASSES, (
            f"classify_ua({ua!r}) returned an out-of-band value"
        )
