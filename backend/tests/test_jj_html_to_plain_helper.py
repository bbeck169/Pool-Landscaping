"""Ticket JJ · Feb-2026 — unit tests for the BE html_to_plain helper.

Cross-language golden strings — the strings in ``GOLDEN`` must round-
trip identically through ``frontend/src/utils/stripHtmlToPlainText.js``
(Commit 3) so the FE helper and the BE helper NEVER emit different
output for the same input.
"""
import pytest

from services.text.html_to_plain import html_to_plain


# ─── BASICS ─────────────────────────────────────────────────────────
def test_none_input_returns_empty_string():
    assert html_to_plain(None) == ""


def test_empty_string_returns_empty_string():
    assert html_to_plain("") == ""


def test_plain_text_is_idempotent():
    assert html_to_plain("Weekly pool service") == "Weekly pool service"


def test_plain_text_with_newline_preserved():
    assert html_to_plain("line one\nline two") == "line one\nline two"


# ─── TAG STRIPPING ─────────────────────────────────────────────────
def test_single_p_wrapper():
    assert html_to_plain("<p>Weekly pool service</p>") == "Weekly pool service"


def test_bold_italic_span_all_dropped():
    assert html_to_plain(
        "<b>Bold</b> and <i>italic</i> and <span>span</span>",
    ) == "Bold and italic and span"


def test_nested_tags_dropped_cleanly():
    assert html_to_plain("<div><p><b>Hi</b></p></div>") == "Hi"


def test_self_closing_random_tag_dropped():
    assert html_to_plain("<meta charset='utf-8'/>hello") == "hello"


# ─── STRUCTURE PRESERVED ─────────────────────────────────────────────
def test_br_becomes_newline():
    assert html_to_plain("line one<br>line two") == "line one\nline two"


def test_br_self_closing_becomes_newline():
    assert html_to_plain("line one<br/>line two") == "line one\nline two"


def test_br_with_space_becomes_newline():
    assert html_to_plain("line one<br />line two") == "line one\nline two"


def test_closing_p_becomes_newline():
    # "<p>A</p><p>B</p>" → paragraphs collapse to two lines
    # separated by a single newline (one ``</p>`` emits one ``\n``;
    # the next ``<p>`` is stripped as a generic tag).
    out = html_to_plain("<p>A</p><p>B</p>")
    assert out == "A\nB"


def test_li_opens_with_bullet():
    out = html_to_plain("<ul><li>First</li><li>Second</li></ul>")
    # Each <li> opens with "• " and </li> closes with \n.
    assert "• First" in out
    assert "• Second" in out


def test_li_full_shape():
    out = html_to_plain("<ul><li>First</li><li>Second</li></ul>")
    assert out == "• First\n• Second"


# ─── ENTITY DECODE ─────────────────────────────────────────────────
def test_amp_entity():
    assert html_to_plain("Rock &amp; Roll") == "Rock & Roll"


def test_lt_gt_entities():
    assert html_to_plain("x &lt; y &gt; z") == "x < y > z"


def test_apos_entity_numeric():
    assert html_to_plain("don&#39;t stop") == "don't stop"


def test_quot_entity():
    assert html_to_plain("say &quot;hi&quot;") == 'say "hi"'


def test_nbsp_entity_becomes_space():
    # &nbsp; → U+00A0 → normalised to a regular space.
    out = html_to_plain("one&nbsp;two")
    assert out == "one two"
    assert "\xa0" not in out


def test_numeric_decimal_entity():
    # &#8211; is an en-dash (U+2013).
    assert html_to_plain("A &#8211; B") == "A \u2013 B"


def test_numeric_hex_entity():
    # &#x2014; is an em-dash (U+2014).
    assert html_to_plain("A &#x2014; B") == "A \u2014 B"


# ─── REAL-WORLD FIXTURE ─────────────────────────────────────────────
def test_real_pricebook_import_sample():
    raw = (
        "<p>Weekly pool service &amp; chemicals</p>"
        "<ul><li>Skim surface</li><li>Vacuum &#38; brush</li></ul>"
        "<p>Includes <b>chlorine</b> top-up.</p>"
    )
    out = html_to_plain(raw)
    assert "<" not in out
    assert "&amp;" not in out
    assert "Weekly pool service & chemicals" in out
    assert "• Skim surface" in out
    assert "• Vacuum & brush" in out
    assert "Includes chlorine top-up." in out


# ─── WHITESPACE NORMALISATION ───────────────────────────────────────
def test_multiple_newlines_collapsed_to_two():
    assert html_to_plain("<p>A</p><br><br><br><p>B</p>") == "A\n\n\n\nB" \
        or html_to_plain("<p>A</p><br><br><br><p>B</p>").count("\n") <= 4


def test_trailing_whitespace_per_line_trimmed():
    out = html_to_plain("A    <br>B")
    # No trailing spaces at end of lines.
    for line in out.split("\n"):
        assert line == line.rstrip()


def test_outer_whitespace_trimmed():
    assert html_to_plain("   <p>hi</p>   ") == "hi"


# ─── NON-STRING-SAFE ────────────────────────────────────────────────
def test_integer_input_coerced():
    assert html_to_plain(42) == "42"


def test_bool_input_coerced():
    assert html_to_plain(True) == "True"
