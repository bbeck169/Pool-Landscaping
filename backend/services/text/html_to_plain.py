"""Ticket JJ · Feb-2026 — HTML → plain-text helper.

Operator-locked rule (JJ brief §1 ``Strip-everything``): no allow-
list.  Every tag is removed; HTML entities are decoded.  Preserved
structure per brief §5 (``Strip-but-preserve-structure``):

  * ``<li>`` opens with ``• `` (U+2022 bullet).
  * ``<br>`` / ``<br/>`` / ``<br />`` collapse to a newline.
  * ``</p>`` + ``</div>`` + ``</li>`` close with a newline.
  * Everything else is dropped.
  * Named entities covered: ``&amp; &lt; &gt; &quot; &#39; &nbsp;``.
    Numeric decimal (``&#NNN;``) + hex (``&#xHH;``) entities decoded
    via ``html.unescape``.

Mirrors ``frontend/src/utils/stripHtmlToPlainText.js`` (Commit 3).
Both helpers must emit the same string for the same input — a
cross-language golden test is covered in
``tests/test_jj_html_to_plain_helper.py``.

Pure function.  No I/O.  Idempotent — stripping already-plain text
is a no-op (``"Hello" → "Hello"``).
"""
from __future__ import annotations

import html
import re
from typing import Optional

# Order matters — structure tokens are swapped BEFORE the generic
# tag strip so the structure survives.
_LI_OPEN_RE = re.compile(r"<\s*li[^>]*>", re.IGNORECASE)
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_PARA_CLOSE_RE = re.compile(r"<\s*/\s*(p|div|li)\s*>", re.IGNORECASE)
_GENERIC_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_TRAILING_WS_PER_LINE_RE = re.compile(r"[ \t]+$", re.MULTILINE)


def html_to_plain(raw: Optional[str]) -> str:
    """Strip HTML tags + decode entities, preserving ``• `` for
    list items and ``\n`` for paragraph / line breaks."""
    if raw is None:
        return ""
    s = str(raw)
    if not s:
        return ""

    # 1. Structure tokens → sentinel plain-text first.  Doing this
    # BEFORE the generic strip means ``<li>text</li>`` → ``• text\n``.
    s = _LI_OPEN_RE.sub("• ", s)
    s = _BR_RE.sub("\n", s)
    s = _PARA_CLOSE_RE.sub("\n", s)

    # 2. Strip every other tag.
    s = _GENERIC_TAG_RE.sub("", s)

    # 3. Decode entities (``&amp;`` → ``&``, ``&#39;`` → ``'``,
    #    ``&nbsp;`` → single space, numeric + hex, etc).  ``html.
    #    unescape`` handles the full HTML5 named set + both numeric
    #    forms.  ``&nbsp;`` → ``\xa0`` which we normalise to a
    #    regular space so downstream width calculations work.
    s = html.unescape(s)
    s = s.replace("\xa0", " ")

    # 4. Tidy whitespace — collapse 3+ newlines, trim trailing
    #    spaces per line, and trim overall.
    s = _TRAILING_WS_PER_LINE_RE.sub("", s)
    s = _MULTI_NEWLINE_RE.sub("\n\n", s)
    return s.strip()
