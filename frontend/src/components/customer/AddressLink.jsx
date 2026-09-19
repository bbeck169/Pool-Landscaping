/**
 * Feb-2026 · Clickable Customer Data — `<AddressLink>`.
 *
 * Wraps a street address (string or structured `{line1,city,state,
 * zip,...}` object) in an anchor that opens the correct native maps
 * app for the current platform:
 *   • iOS UAs (iPhone / iPad / iPod)     → Apple Maps (better native
 *                                          handoff, ties into
 *                                          address book).
 *   • Everything else (macOS, Windows,
 *     Android, Linux, unknown)           → Google Maps universal URL.
 *
 * Empty / invalid input renders a plain span so we never emit a
 * link to `?q=` with no query. Click always stops propagation so
 * anchor-in-clickable-row surfaces (Customers list, Schedule board)
 * don't double-navigate.
 */
import React from "react";

import { isIOS } from "../../services/platform/isIOS";


function _stringify(address) {
  if (address == null) return "";
  if (typeof address === "string") return address.trim();
  if (typeof address !== "object") return String(address).trim();
  // Ordered assembly — line1, line2 (optional), city, state, zip,
  // country (optional). Filter falsy so the join doesn't collapse
  // to ", , ,".
  const parts = [
    address.line1,
    address.line2,
    address.city,
    address.state,
    address.zip,
    address.country,
  ];
  return parts
    .map((p) => (p == null ? "" : String(p).trim()))
    .filter((p) => p.length > 0)
    .join(", ");
}


function _mapsUrl(query, useApple) {
  const q = encodeURIComponent(query);
  if (useApple) {
    return `https://maps.apple.com/?q=${q}`;
  }
  return `https://www.google.com/maps/search/?api=1&query=${q}`;
}


export const AddressLink = ({ address, className, children, ...rest }) => {
  const flat = _stringify(address);
  if (!flat) {
    return (
      <span
        className={className}
        data-testid="customer-address-link"
        data-invalid="true"
        {...rest}
      >
        {children ?? ""}
      </span>
    );
  }
  const href = _mapsUrl(flat, isIOS());
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={
        `hover:underline focus:underline ` + (className || "")
      }
      aria-label={`Open in maps: ${flat}`}
      data-testid="customer-address-link"
      onClick={(e) => e.stopPropagation()}
      {...rest}
    >
      {children ?? flat}
    </a>
  );
};

export default AddressLink;
