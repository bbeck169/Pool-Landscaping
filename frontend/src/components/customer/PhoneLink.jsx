/**
 * Feb-2026 · Clickable Customer Data — `<PhoneLink>`.
 *
 * Wraps a phone number in an `<a href="tel:...">` so it dials on
 * macOS / iOS / Windows dialer handlers. Renders a plain span when
 * the input is empty or non-numeric so we never emit a broken
 * `tel:` URL.
 *
 * Typography stays inherited from the parent — the primitive only
 * adds an underline-on-hover to signal interactivity. Click always
 * stops propagation so wrapping row-level ``onClick`` handlers on
 * list rows keep firing on empty-cell clicks but never hijack the
 * dial affordance.
 */
import React from "react";


function _normalise(raw) {
  if (raw == null) return null;
  const trimmed = String(raw).trim();
  if (!trimmed) return null;
  const digits = trimmed.replace(/\D/g, "");
  if (!digits) return null;
  // Explicit E.164 (raw carried a leading '+' before us).
  if (trimmed.startsWith("+")) return `+${digits}`;
  // 10-digit US → prepend +1.
  if (digits.length === 10) return `+1${digits}`;
  // 11-digit starting with 1 → drop the extra leading char.
  if (digits.length === 11 && digits.startsWith("1")) return `+${digits}`;
  // Everything else — still emit a tel: URL. RFC 3966 accepts any
  // digit string, and dialers on mobile OSes handle both national
  // and E.164 shapes.
  return `+${digits}`;
}


function _format(raw, tel) {
  if (!tel) return raw ?? "";
  const trimmed = String(raw ?? "").trim();
  // Preserve caller-provided formatting for anything that already
  // carried a '+' or looks non-US — mangling international shapes
  // into US triads makes them worse, not better.
  if (trimmed.startsWith("+")) return trimmed;
  const digits = trimmed.replace(/\D/g, "");
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  if (digits.length === 11 && digits.startsWith("1")) {
    return `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`;
  }
  return trimmed;
}


export const PhoneLink = ({ phone, className, children, ...rest }) => {
  const tel = _normalise(phone);
  const display = children ?? _format(phone, tel);
  if (!tel) {
    return (
      <span
        className={className}
        data-testid="customer-phone-link"
        data-invalid="true"
        {...rest}
      >
        {display}
      </span>
    );
  }
  return (
    <a
      href={`tel:${tel}`}
      rel="noopener"
      className={
        `hover:underline focus:underline ` + (className || "")
      }
      aria-label={`Call ${_format(phone, tel)}`}
      data-testid="customer-phone-link"
      onClick={(e) => e.stopPropagation()}
      {...rest}
    >
      {display}
    </a>
  );
};

export default PhoneLink;
