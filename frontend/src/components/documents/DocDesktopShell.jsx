/**
 * Feb-2026 · Desktop-unification — shared shell that renders the
 * common invoice / estimate / quote skeleton so all three surfaces
 * present the same visual layout at ≥ 768 px:
 *
 *   1. Toolbar row (right-aligned actions)
 *   2. Doc container (padded card)
 *   3. Two-column header (brand + doc title/meta)
 *   4. Bill-to + property address block
 *   5. Line-items table (caller-owned slot)
 *   6. Notes card + right-aligned Totals block (side-by-side)
 *   7. Optional Due-marker (invoices) / Disclaimer (estimates)
 *   8. Terms & Conditions (Feb-2026 · queue #5 slot)
 *   9. Payment / Approval stub — perforation-style bottom card
 *      renamed by doc-type per the Feb-2026 design ref.
 *
 * The shell OWNS the structural markup + CSS class contract but
 * DOES NOT own any content — callers pass rendered JSX into each
 * slot so surface-specific behavior (per-line decline, credit
 * applied, admin toolbar variants) stays in the caller.
 *
 * Testid contract
 * ---------------
 *   ${testId}                     shell root (from caller)
 *   doc-desktop-shell             invariant hook for snapshot lock
 *   doc-desktop-shell-toolbar     toolbar container
 *   doc-desktop-shell-header      two-column header
 *   doc-desktop-shell-title       the "Invoice" / "Estimate" / "Quote" label
 *   doc-desktop-shell-meta        right-column meta table
 *   doc-desktop-shell-bill-to     bill-to block
 *   doc-desktop-shell-property    property-address block
 *   doc-desktop-shell-lines       line-items slot wrapper
 *   doc-desktop-shell-notes       notes slot wrapper
 *   doc-desktop-shell-totals      totals slot wrapper
 *   doc-desktop-shell-stub        payment / approval stub
 *   doc-desktop-shell-stub-title  stub label ("PAYMENT STUB" / "APPROVAL STUB")
 *   doc-desktop-shell-stub-mode   attribute — "payment" | "approval"
 *
 * Mobile
 * ------
 * The shared mobile treatment shipped earlier (``DocMobileHeader`` +
 * ``docMobile.css``) still hides ``.iv-toolbar`` / desktop header
 * below 768 px, so the mobile experience is unaffected by this
 * shell. The shell class ``.doc-desktop-shell`` is a no-op — all
 * real styling still comes from ``InvoiceView.css`` + ``EstimateView.css``.
 */
import React from "react";


export default function DocDesktopShell({
  docType,
  testId = "doc-desktop-shell",
  printable = false,
  // Slots (all optional except lines).
  toolbar = null,
  headerLeft = null,
  title = null,
  headerMeta = null,
  billTo = null,
  propertyAddress = null,
  midTitle = null,           // e.g. estimate ``.ev-est-title`` line
  lines,
  notes = null,
  totals = null,
  dueMarker = null,
  termsSection = null,
  stub = null,
  disclaimer = null,
  // Extension slots — anything above/below the shell.
  banner = null,
  belowToolbar = null,
  belowStub = null,
}) {
  const stubMode = docType === "invoice" ? "payment" : "approval";
  return (
    <>
      {toolbar ? (
        <div
          className="iv-toolbar"
          data-testid="doc-desktop-shell-toolbar"
          data-doc-type={docType}
        >
          {toolbar}
        </div>
      ) : null}
      {belowToolbar}
      {banner}
      <div
        className={`iv-doc doc-desktop-shell ${
          docType === "estimate" || docType === "quote" ? "ev-doc" : ""
        } ${printable ? "iv-printable-body" : ""}`}
        data-testid={testId}
        data-desktop-shell="true"
        data-doc-type={docType}
        data-stub-mode={stubMode}
      >
        {/* ── Header ─────────────────────────────────────────── */}
        <div
          className="iv-header"
          data-testid="doc-desktop-shell-header"
        >
          <div className="iv-header-left">
            {headerLeft}
          </div>
          <div className="iv-header-right">
            {title ? (
              <div
                className="iv-title"
                data-testid="doc-desktop-shell-title"
                data-doc-type={docType}
              >
                {title}
              </div>
            ) : null}
            <div data-testid="doc-desktop-shell-meta">
              {headerMeta}
            </div>
          </div>
        </div>

        <div className="iv-divider" />

        {/* ── Bill-to + property ─────────────────────────────── */}
        {billTo ? (
          <div
            className="iv-bill-to"
            data-testid="doc-desktop-shell-bill-to"
          >
            {billTo}
          </div>
        ) : null}
        {midTitle}
        {propertyAddress ? (
          <div
            className="iv-prop-addr"
            data-testid="doc-desktop-shell-property"
          >
            {propertyAddress}
          </div>
        ) : null}

        {/* ── Line items ─────────────────────────────────────── */}
        <div
          className="iv-lines-wrap"
          data-testid="doc-desktop-shell-lines"
        >
          {lines}
        </div>

        {/* ── Notes + Totals row ─────────────────────────────── */}
        <div className="iv-totals-row">
          <div
            className="iv-notes"
            data-testid="doc-desktop-shell-notes"
          >
            {notes}
          </div>
          <div
            className="iv-totals-slot"
            data-testid="doc-desktop-shell-totals"
          >
            {totals}
          </div>
        </div>

        {dueMarker}

        {termsSection}

        {disclaimer}

        {/* ── Stub ──────────────────────────────────────────── */}
        {stub ? (
          <>
            <div className="iv-stub-divider" />
            <div
              className="iv-stub"
              data-testid="doc-desktop-shell-stub"
              data-stub-mode={stubMode}
            >
              <div
                className="iv-stub-title"
                data-testid="doc-desktop-shell-stub-title"
              >
                {stubMode === "payment" ? "PAYMENT STUB" : "APPROVAL STUB"}
              </div>
              {stub}
            </div>
          </>
        ) : null}
      </div>
      {belowStub}
    </>
  );
}
