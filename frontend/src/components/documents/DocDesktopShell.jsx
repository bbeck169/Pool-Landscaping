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
  // INVOICE-STATUS-STAMP · Feb-2026 — optional slot that renders as
  // the first child of ``.iv-header`` so a caller can overlay a
  // PAID / PAST DUE rubber-stamp (or any other absolutely-positioned
  // badge) in the header's top-right. CSS pairs this with
  // ``position: relative`` on ``.iv-header`` so the overlay's
  // ``position: absolute`` works. Default null → zero behaviour
  // change for callers that don't opt in (``EstimateView``,
  // ``QuoteView``).
  headerOverlay = null,
  // Extension slots — anything above/below the shell.
  banner = null,
  belowToolbar = null,
  belowStub = null,
  // Feb-2026 · Theme Refresh — optional branded header band that
  // renders above the standard two-column header. When supplied
  // the band paints a full-width strip using ``brandingPrimary``
  // with the uppercase doc title on the left and the tenant
  // company-name / contact block on the right. Skipped when the
  // caller doesn't opt in so surfaces that haven't wired
  // ``useTenantBranding`` yet keep their existing layout.
  //
  // Shape: { primary, secondary, logoUrl, companyName,
  //          contactLines: [str], footerNote }
  brandingHeader = null,
}) {
  const stubMode = docType === "invoice" ? "payment" : "approval";
  const _bandColor = brandingHeader && brandingHeader.primary;
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
      {brandingHeader ? (
        <div
          className="doc-branded-header-band"
          data-testid="doc-branded-header-band"
          data-primary={_bandColor || ""}
          style={{
            background: _bandColor || "#0B4A6F",
            color: "#FFFFFF",
            padding: "18px 20px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 16,
            borderTopLeftRadius: 8,
            borderTopRightRadius: 8,
            marginBottom: 0,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {brandingHeader.logoUrl ? (
              <img
                src={brandingHeader.logoUrl}
                alt={brandingHeader.companyName || docType}
                style={{ maxHeight: 56, maxWidth: 160,
                          objectFit: "contain", background: "#FFFFFF",
                          padding: 4, borderRadius: 4 }}
                data-testid="doc-branded-header-logo"
              />
            ) : null}
            <div>
              <div
                style={{
                  fontSize: 30, fontWeight: 800, letterSpacing: 1,
                  lineHeight: 1,
                }}
                data-testid="doc-branded-header-title"
              >
                {(docType || "").toUpperCase()}
              </div>
              {!brandingHeader.logoUrl && brandingHeader.companyName ? (
                <div
                  style={{ fontSize: 12, marginTop: 4, opacity: 0.85 }}
                  data-testid="doc-branded-header-company"
                >
                  {brandingHeader.companyName}
                </div>
              ) : null}
            </div>
          </div>
          <div
            style={{
              fontSize: 11, lineHeight: 1.35, textAlign: "right",
              opacity: 0.9, maxWidth: "45%",
            }}
            data-testid="doc-branded-header-contact"
          >
            {(brandingHeader.contactLines || [])
              .filter(Boolean)
              .slice(0, 6)
              .map((line, i) => (
                <div key={i}>{line}</div>
              ))}
          </div>
        </div>
      ) : null}
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
          {headerOverlay}
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
      {/* Feb-2026 · Theme Refresh — footer band matches the header
          band's primary colour and echoes the tenant's footer_note
          (falls back to a generic thank-you). Rendered outside the
          .iv-doc container so it stretches the full container width
          on desktop AND mobile. */}
      {brandingHeader ? (
        <div
          className="doc-branded-footer-band"
          data-testid="doc-branded-footer-band"
          style={{
            background: _bandColor || "#0B4A6F",
            color: "#FFFFFF",
            padding: "14px 20px",
            textAlign: "center",
            fontSize: 12,
            fontWeight: 600,
            marginTop: 12,
            borderBottomLeftRadius: 8,
            borderBottomRightRadius: 8,
          }}
        >
          {(brandingHeader.footerNote || "").trim()
            || "Thank you for your business!"}
        </div>
      ) : null}
      {belowStub}
    </>
  );
}
