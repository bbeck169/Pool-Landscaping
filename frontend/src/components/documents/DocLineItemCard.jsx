/**
 * Feb-2026 · Universal mobile-responsive redesign ·
 * ``DocLineItemCard`` — RENAMED SEMANTICALLY to a compact
 * table-style row primitive per the Feb-2026 design reference
 * (was previously a card with shadow + rounded corners).
 *
 * Filename is preserved to avoid churning imports across the
 * ``mobile-responsive-doc-suite`` test suite; conceptually this
 * component is now ``DocLineItemRow``. Callers still pass the
 * same props / receive the same testids.
 *
 * Contract
 * --------
 *   line, index, testidPrefix, showDeclineButton, onDecline,
 *   onUndecline, busy, fmt
 *
 * Testids (unchanged)
 * -------------------
 *   ${testidPrefix}-line-item-card-${index}     row container
 *   ${testidPrefix}-line-item-declined-chip-${index}
 *   ${testidPrefix}-line-item-decline-reason-${index}
 *   ${testidPrefix}-line-item-decline-${index}   icon-only X btn
 *   ${testidPrefix}-line-item-undecline-${index}
 */
import React from "react";
import { X as XIcon, RotateCcw } from "lucide-react";


export default function DocLineItemCard({
  line = {},
  index = 0,
  testidPrefix = "doc",
  showDeclineButton = false,
  onDecline,
  onUndecline,
  busy = false,
  fmt = (n) => String(n ?? 0),
}) {
  const isDeclined = (line.customer_status || "pending") === "declined";
  const strike = isDeclined
    ? { textDecoration: "line-through", opacity: 0.55 }
    : undefined;

  return (
    <div
      className="doc-line-row"
      data-testid={`${testidPrefix}-line-item-card-${index}`}
      data-customer-status={line.customer_status || "pending"}
      style={{
        display: "grid",
        gridTemplateColumns: showDeclineButton
          ? "1fr 44px 72px 44px"
          : "1fr 44px 88px",
        alignItems: "center",
        columnGap: 8,
        padding: "10px 0",
        borderBottom: "1px solid #E5E7EB",
        fontSize: 14,
      }}
    >
      <div style={{ minWidth: 0, ...(strike || {}) }}>
        <div style={{
          fontWeight: 600, color: "#0F172A",
          overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {line.description || `Line ${index + 1}`}
        </div>
        {isDeclined ? (
          <span
            data-testid={`${testidPrefix}-line-item-declined-chip-${index}`}
            style={{
              display: "inline-block",
              marginTop: 4,
              fontSize: 11,
              padding: "2px 6px",
              borderRadius: 6,
              background: "#FEE2E2",
              color: "#7F1D1D",
              textDecoration: "none",
              fontWeight: 700,
            }}
          >
            Declined
          </span>
        ) : null}
        {isDeclined && line.customer_decline_reason ? (
          <div
            data-testid={`${testidPrefix}-line-item-decline-reason-${index}`}
            style={{
              marginTop: 2, fontSize: 12,
              color: "#7F1D1D", fontStyle: "italic",
            }}
          >
            Reason: {line.customer_decline_reason}
          </div>
        ) : null}
      </div>

      <div
        style={{
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
          color: "#374151",
          ...(strike || {}),
        }}
      >
        {line.qty_hr || line.quantity || 0}
      </div>

      <div
        style={{
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
          color: "#0F172A",
          fontWeight: 700,
          ...(strike || {}),
        }}
      >
        {typeof fmt === "function" ? fmt(line.total) : line.total}
      </div>

      {showDeclineButton ? (
        <div style={{ textAlign: "right" }}>
          {isDeclined ? (
            <button
              type="button"
              onClick={onUndecline}
              disabled={busy}
              aria-label="Undo decline"
              data-testid={`${testidPrefix}-line-item-undecline-${index}`}
              style={{
                minWidth: 32,
                minHeight: 32,
                padding: 8,     /* 8 + 32 = ≥ 44px tap target */
                borderRadius: 8,
                background: "transparent",
                border: "1px solid #94A3B8",
                color: "#0F172A",
                cursor: busy ? "not-allowed" : "pointer",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <RotateCcw size={14} />
            </button>
          ) : (
            <button
              type="button"
              onClick={onDecline}
              disabled={busy}
              aria-label="Decline this line"
              data-testid={`${testidPrefix}-line-item-decline-${index}`}
              style={{
                minWidth: 32,
                minHeight: 32,
                padding: 8,     /* ≥ 44px tap target via padding */
                borderRadius: 8,
                background: "transparent",
                border: "1px solid #DC2626",
                color: "#DC2626",
                cursor: busy ? "not-allowed" : "pointer",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <XIcon size={14} />
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}
