/**
 * Phase P14 · Feb-2026 · Item 5 — ClickableAddress.
 *
 * Coerces object-shaped addresses via ``utils/address.js`` (twin
 * of the backend's ``_coerce_address_to_str`` in
 * ``backend/routers/jobs.py``) then renders an anchor that opens
 * Google Maps in a new tab. Empty / uncoerceable addresses
 * render as plain text (no anchor).
 *
 * Default ``onClick`` stops event propagation so tapping the
 * address inside a clickable list row doesn't ALSO fire the
 * row nav.
 */
import React from "react";
import { coerceAddressToStr } from "@/utils/address";


export function ClickableAddress({
  address,
  className = "",
  testid,
  onClick,
}) {
  const str = coerceAddressToStr(address);

  if (!str) {
    return (
      <span
        className={className}
        data-testid={testid}
      >
        {str}
      </span>
    );
  }

  const _click = (e) => {
    e.stopPropagation();
    if (typeof onClick === "function") onClick(e);
  };

  const href =
    `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(str)}`;

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`${className} hover:underline text-blue-600`.trim()}
      data-testid={testid}
      onClick={_click}
    >
      {str}
    </a>
  );
}


export default ClickableAddress;
