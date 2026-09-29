/**
 * SummaryTile — Feb-2026 · QUOTES-SUMMARY.
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
 * Two additions for QUOTES-SUMMARY consumers, both fully backwards
 * compatible:
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
 */
import React from "react";
import { colors } from "@/theme";

export default function SummaryTile({
  icon: Icon, tone, label, value, sub, testid, children,
}) {
  return (
    <div
      className="rounded-2xl p-4"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={testid}
    >
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
    </div>
  );
}
