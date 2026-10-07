/**
 * SummaryTile — Feb-2026 · QUOTES-SUMMARY + INVOICES-TILES-CLICKABLE.
 *
 * Small stats tile used in list-page dashboards (InvoicesList,
 * QuotesList, and any future admin surface that needs a compact
 * "icon + label + value + sub" summary card).
 *
 * Extracted from ``pages/invoices/InvoicesList.jsx`` where it
 * originally lived as a local helper.  The visual output and the
 * ``{ icon, tone, label, value, sub }`` prop shape are preserved
 * byte-for-byte from the original implementation so the extraction
 * is a zero-behavior-change refactor for Invoices.
 *
 * Backwards-compatible additions:
 *
 * * ``testid`` (optional) — stamps a ``data-testid`` on the outer
 *   card.  Existing InvoicesList callers omit it and keep their
 *   current DOM shape.
 * * ``children`` (optional) — when passed, renders in place of
 *   ``value`` so a tile can host bespoke content (e.g. QuotesList's
 *   Stage Breakdown wants a wrapping row of status pills, not a
 *   single numeric string).  When ``children`` is omitted the
 *   original ``value`` node renders in the same slot with the
 *   original ``text-xl font-bold`` styling.
 * * ``onClick`` + ``active`` + ``ariaLabel`` (Feb-2026 ·
 *   INVOICES-TILES-CLICKABLE) — opt-in clickable mode. When
 *   ``onClick`` is a function, the tile paints a button-shaped
 *   interactive surface with ``role="button"``, ``tabIndex=0``,
 *   ``aria-pressed`` reflecting ``active``, visible focus ring,
 *   Enter/Space keyboard activation, and a thicker tone-coloured
 *   border + soft ring when ``active`` is true. Callers that
 *   leave ``onClick`` undefined keep the pre-INVOICES-TILES
 *   non-interactive card (zero drift).
 */
import React from "react";
import { colors } from "@/theme";


export default function SummaryTile({
  icon: Icon, tone, label, value, sub, testid, children,
  onClick, active = false, ariaLabel,
}) {
  const clickable = typeof onClick === "function";

  // INVOICES-TILES-CLICKABLE · Feb-2026 — active-state styling.
  // Use the tone colour as a thicker border + soft outer ring so
  // selection is obvious across every tile without needing a
  // separate CSS stylesheet. Non-clickable tiles keep the original
  // 1 px border, zero ring.
  const baseBorder = active && clickable
    ? `2px solid ${tone || colors.border}`
    : `1px solid ${colors.border}`;
  const activeRing = active && clickable
    // ``tone`` is already an rgb-ish hex; append ``33`` (≈ 20% alpha)
    // so the ring reads as a soft wash without needing a theme hook.
    ? `0 0 0 3px ${tone || colors.border}33`
    : undefined;

  const _handleKey = clickable
    ? (e) => {
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.preventDefault();
          onClick();
        }
      }
    : undefined;

  const _commonProps = {
    className: clickable
      ? "rounded-2xl p-4 cursor-pointer transition-shadow focus:outline-none focus-visible:ring-2"
      : "rounded-2xl p-4",
    style: {
      backgroundColor: colors.surface,
      border: baseBorder,
      boxShadow: activeRing,
      // Button-reset so the native <button> doesn't force centre
      // alignment or the browser's default background.
      textAlign: "left",
      font: "inherit",
      width: "100%",
    },
    "data-testid": testid,
    "data-active": clickable && active ? "true" : undefined,
    "aria-pressed": clickable ? !!active : undefined,
    "aria-label": ariaLabel || label,
    onClick: clickable ? onClick : undefined,
    onKeyDown: _handleKey,
    role: clickable ? "button" : undefined,
    tabIndex: clickable ? 0 : undefined,
    type: clickable ? "button" : undefined,
  };

  // Render as a native <button> when clickable so screen-reader
  // + keyboard semantics are first-class, otherwise keep the
  // pre-existing <div> shape so the layout is byte-identical for
  // every existing caller.
  const Tag = clickable ? "button" : "div";

  return (
    <Tag {..._commonProps}>
      <div className="flex items-center gap-1.5" style={{ color: tone }}>
        {Icon ? <Icon size={14} /> : null}
        <span className="text-xs font-semibold">{label}</span>
      </div>
      {children != null ? (
        <div className="mt-1">{children}</div>
      ) : (
        <div className="text-xl font-bold mt-1"
             style={{ color: colors.onSurface }}>
          {value}
        </div>
      )}
      {sub ? (
        <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
          {sub}
        </div>
      ) : null}
    </Tag>
  );
}
