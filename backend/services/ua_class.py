"""QV-service · Feb-2026 — User-Agent classifier.

Hand-rolled regex classifier used by
:func:`services.quote_view_tracker.record_quote_view` to stamp each
view event with a coarse UA class. Six output strings — see
:data:`UA_CLASSES` — plus ``"Other"`` for anything unmatched (Edge,
Opera, curl, bots, empty).

No new dependency — pure ``re`` + a small ordered rule table.  The
rule order matters:

  1. iPad / iPhone are checked BEFORE Android/Chrome/Firefox because
     Chrome on iPhone/iPad is ``CriOS`` (still WebKit under the hood
     — the user experience is iOS Safari, not Desktop Chrome).
  2. Android Chrome is checked before Desktop Chrome so a mobile
     ``Chrome/121.0`` on Android never falls into the desktop bucket.
     WebView (``wv;`` marker) is EXCLUDED — those are in-app browsers,
     not real Chrome sessions, and we route them to ``Other``.
  3. Desktop Firefox catches ``Firefox/`` while excluding ``FxiOS``
     (Firefox on iPhone → still iPhone Safari class).
  4. Desktop Chrome/Safari are last so any mobile signal steals the
     match first.

Callers pass the raw ``User-Agent`` header (or ``None``).  Never
raises — a mis-shaped UA falls through to ``"Other"``.
"""
from __future__ import annotations

import re
from typing import Optional


UA_CLASSES = (
    "iPhone Safari",
    "iPad Safari",
    "Android Chrome",
    "Desktop Chrome",
    "Desktop Safari",
    "Desktop Firefox",
    "Other",
)


# Compiled once at import so each classify_ua call is a few regex
# matches, not a rebuild.  Ordered — first match wins.
_IPAD_RE      = re.compile(r"iPad", re.IGNORECASE)
_IPHONE_RE    = re.compile(r"iPhone", re.IGNORECASE)
_ANDROID_RE   = re.compile(r"Android", re.IGNORECASE)
_CHROME_RE    = re.compile(r"Chrome/", re.IGNORECASE)
_FIREFOX_RE   = re.compile(r"Firefox/", re.IGNORECASE)
_SAFARI_RE    = re.compile(r"Safari/", re.IGNORECASE)
_EDGE_RE      = re.compile(r"\bEdg/|\bOPR/", re.IGNORECASE)
_WEBVIEW_RE   = re.compile(r"; wv;|; wv\)", re.IGNORECASE)
_FXIOS_RE     = re.compile(r"FxiOS", re.IGNORECASE)


def classify_ua(ua: Optional[str]) -> str:
    """Return one of :data:`UA_CLASSES` for the given ``User-Agent``.

    ``None`` / empty / whitespace-only input → ``"Other"``.  Never
    raises.
    """
    if not ua or not ua.strip():
        return "Other"
    # 1 · iOS tablet (checked before iPhone because iPad-Pro ships
    #     both ``iPad`` and ``like Mac OS X`` — the iPhone rule below
    #     would false-negative on iPad but the iPad rule wins first).
    if _IPAD_RE.search(ua):
        return "iPad Safari"
    # 2 · iOS phone. Catches CriOS / FxiOS / EdgiOS on iPhone —
    #     all still WebKit under the hood, so they classify as
    #     "iPhone Safari" (not their nominal Chrome/Firefox/Edge).
    if _IPHONE_RE.search(ua):
        return "iPhone Safari"
    # 3 · Android Chrome — must NOT be a WebView (``; wv;``) or an
    #     in-app browser masquerading as Chrome. WebViews route to
    #     Other so ops can distinguish "customer opened the link in
    #     a real Chrome tab" vs "customer opened it inside their
    #     bank's in-app browser".
    if _ANDROID_RE.search(ua):
        if _CHROME_RE.search(ua) and not _WEBVIEW_RE.search(ua):
            return "Android Chrome"
        # Non-Chrome Android browsers (Samsung Internet, MIUI,
        # UC Browser, etc.) → Other. Rare enough that we don't
        # split them out; ops can always inspect ``user_agent``
        # raw on the event row.
        return "Other"
    # 4 · Desktop Firefox. Exclude FxiOS (Firefox iPhone build —
    #     already caught by the iPhone rule above, defensive here).
    if _FIREFOX_RE.search(ua) and not _FXIOS_RE.search(ua):
        return "Desktop Firefox"
    # 5 · Desktop Chrome — real Chrome only. Exclude Edge (``Edg/``),
    #     Opera (``OPR/``), Chromium-on-Android (already caught
    #     above), and any residual mobile signal.
    if (_CHROME_RE.search(ua)
            and not _EDGE_RE.search(ua)
            and not _ANDROID_RE.search(ua)
            and not _IPHONE_RE.search(ua)
            and not _IPAD_RE.search(ua)):
        return "Desktop Chrome"
    # 6 · Desktop Safari — Safari WITHOUT Chrome/Chromium (Safari
    #     UA also contains ``Safari/`` even when Chrome is the
    #     browser, so the negative-match on Chrome is critical).
    if (_SAFARI_RE.search(ua)
            and not _CHROME_RE.search(ua)
            and not _ANDROID_RE.search(ua)
            and not _IPHONE_RE.search(ua)
            and not _IPAD_RE.search(ua)):
        return "Desktop Safari"
    # 7 · Fallback bucket — Edge, Opera, curl, bots, custom clients,
    #     malformed UAs.
    return "Other"
