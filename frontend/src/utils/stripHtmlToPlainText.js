/**
 * Ticket JJ · Feb-2026 — HTML → plain-text helper (FE mirror).
 *
 * Must emit the SAME string for the SAME input as
 * ``backend/services/text/html_to_plain.py`` (Commit 1).  A golden
 * cross-language fixture lives in both ``jj-strip-html-helper.test.jsx``
 * and ``tests/test_jj_html_to_plain_helper.py`` to catch drift.
 *
 * Operator-locked rules (JJ brief §1 + §5):
 *   * Strip-everything (no allow-list).
 *   * Decode HTML entities — named (``&amp; &lt; &gt; &quot; &#39;
 *     &nbsp;``) + numeric decimal (``&#NNN;``) + hex (``&#xHH;``).
 *   * Preserve structure: ``<li>`` → ``"• "``, ``<br>`` → ``"\n"``,
 *     ``</p>`` / ``</div>`` / ``</li>`` → ``"\n"``.
 *   * ``&nbsp;`` collapses to a regular space.
 *   * Trim trailing per-line whitespace, collapse 3+ newlines to 2,
 *     trim outer whitespace.
 *   * Idempotent on already-plain input.  Returns ``""`` for null /
 *     undefined / empty.  Coerces non-string inputs via ``String()``.
 *
 * Pure function.  No DOM.  No deps.  Safe on both the browser and
 * jsdom (test) environments.
 */

const _LI_OPEN_RE = /<\s*li[^>]*>/gi;
const _BR_RE = /<\s*br\s*\/?\s*>/gi;
const _PARA_CLOSE_RE = /<\s*\/\s*(p|div|li)\s*>/gi;
const _GENERIC_TAG_RE = /<[^>]+>/g;
const _MULTI_NEWLINE_RE = /\n{3,}/g;
const _TRAILING_WS_PER_LINE_RE = /[ \t]+$/gm;
const _NAMED_ENTITY_MAP = {
  "&amp;":  "&",
  "&lt;":   "<",
  "&gt;":   ">",
  "&quot;": '"',
  "&#39;":  "'",
  "&apos;": "'",
  "&nbsp;": " ",
};
const _NAMED_ENTITY_RE = /&(amp|lt|gt|quot|#39|apos|nbsp);/g;
const _NUMERIC_DEC_RE = /&#(\d+);/g;
const _NUMERIC_HEX_RE = /&#x([0-9a-fA-F]+);/g;

/**
 * @param {string|null|undefined|number|boolean} raw
 * @returns {string}
 */
export function stripHtmlToPlainText(raw) {
  if (raw === null || raw === undefined) return "";
  let s = String(raw);
  if (!s) return "";

  // 1. Structure tokens → plain-text sentinels first.
  s = s.replace(_LI_OPEN_RE, "• ");
  s = s.replace(_BR_RE, "\n");
  s = s.replace(_PARA_CLOSE_RE, "\n");

  // 2. Strip every other tag.
  s = s.replace(_GENERIC_TAG_RE, "");

  // 3. Decode entities.  Named table first (fast path), then
  // numeric decimal + hex.
  s = s.replace(_NAMED_ENTITY_RE, (m) => _NAMED_ENTITY_MAP[m] ?? m);
  s = s.replace(_NUMERIC_DEC_RE, (_m, n) =>
    String.fromCodePoint(parseInt(n, 10)));
  s = s.replace(_NUMERIC_HEX_RE, (_m, n) =>
    String.fromCodePoint(parseInt(n, 16)));

  // 4. Normalise non-breaking spaces to regular spaces.
  s = s.replace(/\u00a0/g, " ");

  // 5. Tidy whitespace.
  s = s.replace(_TRAILING_WS_PER_LINE_RE, "");
  s = s.replace(_MULTI_NEWLINE_RE, "\n\n");
  return s.trim();
}

export default stripHtmlToPlainText;
