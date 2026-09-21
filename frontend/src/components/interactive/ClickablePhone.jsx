/**
 * Phase P14 · Feb-2026 · Item 5 — ClickablePhone.
 *
 * Wraps a phone number in a ``<a href="tel:...">``. Normalizes the
 * href by stripping spaces / dashes / parens / letter chars while
 * KEEPING a leading ``+`` (E.164) if present. The visible text is
 * unchanged — only the href is normalized.
 *
 * When the phone is empty OR contains no digits, renders as plain
 * text (no anchor, no ``tel:`` scheme). Prevents the hijack case
 * where a clickable list row would fire the row nav on tapping
 * the phone by defaulting ``onClick`` to a stop-propagation
 * handler; callers can override with their own handler.
 */
import React from "react";


/** Strip everything except leading ``+`` and digits. */
function _normalize(phone) {
  if (typeof phone !== "string") return "";
  const trimmed = phone.trim();
  if (!trimmed) return "";
  const digits = trimmed.replace(/[^\d+]/g, "");
  // Only allow a leading ``+`` — any interior ``+`` is a garbage
  // shape and we drop it.
  const cleaned = digits.startsWith("+")
    ? "+" + digits.slice(1).replace(/\+/g, "")
    : digits.replace(/\+/g, "");
  return cleaned;
}


export function ClickablePhone({
  phone,
  className = "",
  testid,
  onClick,
}) {
  const display = (phone == null ? "" : String(phone)).trim();
  const href = _normalize(display);
  const hasDigits = /\d/.test(href);

  if (!display || !hasDigits) {
    return (
      <span
        className={className}
        data-testid={testid}
      >
        {display}
      </span>
    );
  }

  const _click = (e) => {
    // Prevent row-navigation hijack — the anchor's default
    // ``tel:`` behavior still fires because we only stop
    // propagation, not the default.
    e.stopPropagation();
    if (typeof onClick === "function") onClick(e);
  };

  return (
    <a
      href={`tel:${href}`}
      className={`${className} hover:underline text-blue-600`.trim()}
      data-testid={testid}
      onClick={_click}
    >
      {display}
    </a>
  );
}


export default ClickablePhone;
