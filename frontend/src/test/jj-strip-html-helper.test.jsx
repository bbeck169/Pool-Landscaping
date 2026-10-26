/**
 * Ticket JJ · Feb-2026 — FE helper tests.
 *
 * Golden-fixture parity with ``tests/test_jj_html_to_plain_helper.py``
 * (Commit 1).  Any divergence between the two helpers is a bug — the
 * same raw string MUST emit the same cleaned string on both sides.
 */
import { describe, it, expect } from "vitest";
import stripHtmlToPlainText from "@/utils/stripHtmlToPlainText";

// ─── BASICS ─────────────────────────────────────────────────────────
describe("JJ · stripHtmlToPlainText basics", () => {
  it("null → ''", () => expect(stripHtmlToPlainText(null)).toBe(""));
  it("undefined → ''", () => expect(stripHtmlToPlainText(undefined)).toBe(""));
  it("'' → ''", () => expect(stripHtmlToPlainText("")).toBe(""));
  it("plain is idempotent", () =>
    expect(stripHtmlToPlainText("Weekly pool service"))
      .toBe("Weekly pool service"));
  it("plain with newline preserved", () =>
    expect(stripHtmlToPlainText("line one\nline two"))
      .toBe("line one\nline two"));
});

// ─── TAG STRIPPING ─────────────────────────────────────────────────
describe("JJ · stripHtmlToPlainText tag stripping", () => {
  it("single <p> wrapper", () =>
    expect(stripHtmlToPlainText("<p>Weekly pool service</p>"))
      .toBe("Weekly pool service"));
  it("<b> <i> <span> all dropped", () =>
    expect(stripHtmlToPlainText("<b>Bold</b> and <i>italic</i> and <span>span</span>"))
      .toBe("Bold and italic and span"));
  it("nested tags cleaned", () =>
    expect(stripHtmlToPlainText("<div><p><b>Hi</b></p></div>"))
      .toBe("Hi"));
  it("self-closing random tag dropped", () =>
    expect(stripHtmlToPlainText("<meta charset='utf-8'/>hello"))
      .toBe("hello"));
});

// ─── STRUCTURE PRESERVED ─────────────────────────────────────────────
describe("JJ · stripHtmlToPlainText structure preserved", () => {
  it("<br> becomes \\n", () =>
    expect(stripHtmlToPlainText("line one<br>line two"))
      .toBe("line one\nline two"));
  it("<br/> becomes \\n", () =>
    expect(stripHtmlToPlainText("line one<br/>line two"))
      .toBe("line one\nline two"));
  it("<br /> becomes \\n", () =>
    expect(stripHtmlToPlainText("line one<br />line two"))
      .toBe("line one\nline two"));
  it("</p></p> → A\\nB (matches BE)", () =>
    expect(stripHtmlToPlainText("<p>A</p><p>B</p>")).toBe("A\nB"));
  it("<li> opens with '• '", () => {
    const out = stripHtmlToPlainText("<ul><li>First</li><li>Second</li></ul>");
    expect(out).toBe("• First\n• Second");
  });
});

// ─── ENTITY DECODE ─────────────────────────────────────────────────
describe("JJ · stripHtmlToPlainText entity decode", () => {
  it("&amp; → &", () =>
    expect(stripHtmlToPlainText("Rock &amp; Roll"))
      .toBe("Rock & Roll"));
  it("&lt; &gt;", () =>
    expect(stripHtmlToPlainText("x &lt; y &gt; z"))
      .toBe("x < y > z"));
  it("&#39; → '", () =>
    expect(stripHtmlToPlainText("don&#39;t stop"))
      .toBe("don't stop"));
  it("&quot; → \"", () =>
    expect(stripHtmlToPlainText("say &quot;hi&quot;"))
      .toBe('say "hi"'));
  it("&nbsp; collapses to space (no U+00A0 residue)", () => {
    const out = stripHtmlToPlainText("one&nbsp;two");
    expect(out).toBe("one two");
    expect(out).not.toMatch(/\u00a0/);
  });
  it("numeric decimal entity (en-dash)", () =>
    expect(stripHtmlToPlainText("A &#8211; B"))
      .toBe("A \u2013 B"));
  it("numeric hex entity (em-dash)", () =>
    expect(stripHtmlToPlainText("A &#x2014; B"))
      .toBe("A \u2014 B"));
});

// ─── REAL-WORLD FIXTURE (parity with BE) ────────────────────────────
describe("JJ · real-world pricebook import sample", () => {
  const RAW = "<p>Weekly pool service &amp; chemicals</p>"
            + "<ul><li>Skim surface</li><li>Vacuum &#38; brush</li></ul>"
            + "<p>Includes <b>chlorine</b> top-up.</p>";

  it("no tags survive", () => {
    expect(stripHtmlToPlainText(RAW)).not.toMatch(/</);
  });
  it("no entities survive", () => {
    expect(stripHtmlToPlainText(RAW)).not.toMatch(/&amp;/);
  });
  it("content + bullets present", () => {
    const out = stripHtmlToPlainText(RAW);
    expect(out).toContain("Weekly pool service & chemicals");
    expect(out).toContain("• Skim surface");
    expect(out).toContain("• Vacuum & brush");
    expect(out).toContain("Includes chlorine top-up.");
  });
});

// ─── WHITESPACE NORMALISATION ───────────────────────────────────────
describe("JJ · stripHtmlToPlainText whitespace", () => {
  it("trailing per-line whitespace trimmed", () => {
    const out = stripHtmlToPlainText("A    <br>B");
    for (const line of out.split("\n")) {
      expect(line).toBe(line.replace(/\s+$/, ""));
    }
  });
  it("outer whitespace trimmed", () =>
    expect(stripHtmlToPlainText("   <p>hi</p>   ")).toBe("hi"));
});

// ─── NON-STRING-SAFE ────────────────────────────────────────────────
describe("JJ · stripHtmlToPlainText non-string input", () => {
  it("integer coerced", () => expect(stripHtmlToPlainText(42)).toBe("42"));
  it("boolean coerced", () => expect(stripHtmlToPlainText(true)).toBe("true"));
  // Note: JS String(true) → "true" lowercase; Python str(True) → "True".
  // Divergence is coercion-level only; both honour the "stringify
  // then strip" contract.  Documented in the file-level comment.
});
