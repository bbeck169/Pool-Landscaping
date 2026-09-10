/**
 * Feb-2026 · Universal mobile-responsive redesign · SHARED
 * customer-facing doc top-of-page block (per Feb-2026 design ref).
 *
 * Renders three stacked sections on mobile viewports:
 *
 *   1. Dark banner (slate-800) — full-width, centered white
 *      uppercase doc-type label: ``INVOICE`` / ``ESTIMATE`` /
 *      ``QUOTE``.
 *   2. Prominent primary CTA — full-width bright button whose
 *      label includes the doc amount, e.g.
 *      ``Pay Invoice ($42.82)`` / ``Approve Estimate ($X.XX)``.
 *      NOT sticky. Signature-gate: disables + surfaces an amber
 *      "Sign to enable" hint when the tenant has flipped the
 *      Phase C gate on. Below the primary CTA on estimate / quote
 *      surfaces we render a smaller full-width red outlined
 *      ``Decline`` button + a plain "Request Changes" text link.
 *   3. Two-column business info block — left column: tenant
 *      logo + brand-colored company name + address + tel-linked
 *      phone; right column: doc # + Due / Valid-until date in
 *      an amber highlight.
 *
 * Testids
 * -------
 *   mobile-doc-header (root)
 *   mobile-doc-banner
 *   mobile-doc-title            (banner label — ``Invoice`` etc)
 *   mobile-doc-primary-cta      (primary green button)
 *   mobile-doc-primary-hint     (amber "Sign to enable" hint)
 *   mobile-doc-decline-cta      (red outlined decline button)
 *   mobile-doc-request-changes  (plain text link)
 *   mobile-doc-business-info    (two-column info block)
 *   mobile-doc-doc-number       (right-column doc #)
 *   mobile-doc-due-date         (right-column due / valid-until)
 *   estimate-toolbar-customer-approve  (LEGACY-PRESERVED alias)
 *   estimate-toolbar-customer-decline  (LEGACY-PRESERVED alias)
 *   approve-blocked-by-signature-hint  (LEGACY-PRESERVED alias)
 *   approve-sign-now-cta               (LEGACY-PRESERVED alias)
 *   doc-header-logo                    (LEGACY-PRESERVED alias)
 */
import React from "react";
import { getTenantLogoUrl, DEFAULT_LOGO_ALT } from "@/lib/tenantLogo";


const BANNER_BG = "#1F2937";           // slate-800
const CTA_GREEN = "#10B981";           // emerald-500
const DECLINE_RED = "#DC2626";         // red-600
const AMBER_HINT_BG = "#FEF3C7";
const AMBER_HINT_BR = "#FCD34D";
const AMBER_HINT_FG = "#92400E";
const DUE_HIGHLIGHT = "#B45309";       // amber-700
const DEFAULT_BRAND = "#0F172A";       // slate-900 fallback


function fmtMoney(n) {
  const v = Number(n || 0);
  try {
    return v.toLocaleString("en-US", {
      style: "currency", currency: "USD",
    });
  } catch {
    return `$${v.toFixed(2)}`;
  }
}


function TypeLabel({ docType }) {
  const label = docType === "invoice" ? "INVOICE"
    : docType === "quote" ? "QUOTE"
    : "ESTIMATE";
  return (
    <span
      data-testid="mobile-doc-title"
      style={{
        color: "#FFFFFF",
        fontSize: 16,
        fontWeight: 800,
        letterSpacing: 1,
        textTransform: "uppercase",
      }}
    >
      {label}
    </span>
  );
}


function PrimaryCta({
  docType, amount, onPrimaryAction, disabled, testid, legacyTestid,
}) {
  const verb = docType === "invoice" ? "Pay Invoice"
    : docType === "quote" ? "Approve Quote"
    : "Approve Estimate";
  return (
    <button
      type="button"
      onClick={onPrimaryAction}
      disabled={disabled}
      data-testid={testid}
      data-legacy-testid={legacyTestid || undefined}
      data-signature-blocked={disabled ? "true" : "false"}
      style={{
        width: "100%",
        minHeight: 48,
        border: "none",
        background: CTA_GREEN,
        color: "#FFFFFF",
        fontSize: 16,
        fontWeight: 800,
        borderRadius: 10,
        padding: "12px 16px",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.55 : 1,
        letterSpacing: 0.2,
      }}
    >
      {verb} ({fmtMoney(amount)})
    </button>
  );
}


function DeclineCta({ onDecline, testid, legacyTestid, docType }) {
  const label = docType === "quote" ? "Decline Quote" : "Decline Estimate";
  return (
    <button
      type="button"
      onClick={onDecline}
      data-testid={testid}
      data-legacy-testid={legacyTestid || undefined}
      style={{
        width: "100%",
        minHeight: 44,
        marginTop: 10,
        background: "transparent",
        color: DECLINE_RED,
        border: `1.5px solid ${DECLINE_RED}`,
        fontSize: 14,
        fontWeight: 700,
        borderRadius: 10,
        padding: "10px 14px",
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );
}


function SignatureHint({ hint, onSignNow }) {
  return (
    <div
      data-testid="mobile-doc-primary-hint"
      data-legacy-testid="approve-blocked-by-signature-hint"
      style={{
        marginTop: 10,
        padding: "10px 12px",
        background: AMBER_HINT_BG,
        border: `1px solid ${AMBER_HINT_BR}`,
        color: AMBER_HINT_FG,
        borderRadius: 8,
        fontSize: 13,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
      }}
    >
      <span>{hint || "Sign to enable"}</span>
      {onSignNow ? (
        <button
          type="button"
          onClick={onSignNow}
          data-testid="mobile-approve-sign-now-cta"
          data-legacy-testid="approve-sign-now-cta"
          style={{
            padding: "6px 12px",
            background: "#0EA5E9",
            color: "#FFFFFF",
            border: "none",
            borderRadius: 6,
            fontSize: 12,
            fontWeight: 700,
            cursor: "pointer",
          }}
        >
          Sign now
        </button>
      ) : null}
    </div>
  );
}


function BusinessInfoBlock({ company, docMeta, docType, brandColor }) {
  const brand = brandColor || DEFAULT_BRAND;
  const isInvoice = docType === "invoice";
  const isQuote = docType === "quote";
  const docNumberLabel = isInvoice ? "Invoice #"
    : isQuote ? "Quote #" : "Estimate #";
  const dateLabel = isInvoice ? "Due" : "Valid until";

  return (
    <div
      data-testid="mobile-doc-business-info"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 12,
        padding: "16px",
        background: "#FFFFFF",
        borderBottom: "1px solid #E5E7EB",
      }}
    >
      {/* Left column */}
      <div style={{ minWidth: 0 }}>
        <img
          src={getTenantLogoUrl(company)}
          alt={(company && company.name) || DEFAULT_LOGO_ALT}
          data-testid="mobile-doc-header-logo"
          data-legacy-testid="doc-header-logo"
          data-surface={docType}
          style={{
            maxHeight: 40,
            maxWidth: 140,
            display: "block",
            marginBottom: 6,
            objectFit: "contain",
          }}
        />
        <div
          data-testid="mobile-doc-brand-name"
          style={{
            color: brand,
            fontWeight: 800,
            fontSize: 14,
            lineHeight: 1.25,
            marginBottom: 4,
            wordBreak: "break-word",
          }}
        >
          {(company && company.name) || "\u00A0"}
        </div>
        {company && company.address ? (
          <div style={{
            fontSize: 12, color: "#4B5563",
            lineHeight: 1.35, marginBottom: 4,
            wordBreak: "break-word",
          }}>
            {company.address}
          </div>
        ) : null}
        {company && company.phone ? (
          <div style={{ fontSize: 12, color: "#4B5563" }}>
            Tel:{" "}
            <a
              href={`tel:${String(company.phone).replace(/\s+/g, "")}`}
              data-testid="mobile-doc-phone-link"
              style={{ color: "#2563EB", textDecoration: "none" }}
            >
              {company.phone}
            </a>
          </div>
        ) : null}
      </div>
      {/* Right column */}
      <div style={{
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-end",
        textAlign: "right",
      }}>
        <div
          data-testid="mobile-doc-doc-number"
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: "#0F172A",
            marginBottom: 6,
            wordBreak: "break-word",
          }}
        >
          {docNumberLabel}: {docMeta?.number || "—"}
        </div>
        {docMeta?.date ? (
          <div
            data-testid="mobile-doc-due-date"
            style={{
              fontSize: 13,
              color: "#4B5563",
              wordBreak: "break-word",
            }}
          >
            {dateLabel}:{" "}
            <span style={{ color: DUE_HIGHLIGHT, fontWeight: 700 }}>
              {docMeta.date}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}


export default function DocMobileHeader({
  docType = "estimate",
  amount = 0,
  hasDeclinedLines = false,
  adjustedAmount = null,
  company = {},
  docMeta = {},
  brandColor = null,
  onPrimaryAction,
  primaryActionDisabled = false,
  primaryActionHint = null,
  onSignNow,
  onDecline,
  onRequestChanges,
  hideActions = false,
}) {
  const isInvoice = docType === "invoice";
  const effectiveAmount = hasDeclinedLines && adjustedAmount != null
    ? adjustedAmount : amount;

  // Preserve the legacy testids EstimateView customers rely on so
  // Phase C automation + magic-link e2e tests keep resolving.
  const approveTestid = "mobile-doc-primary-cta";
  const approveLegacy = "estimate-toolbar-customer-approve";
  const declineTestid = "mobile-doc-decline-cta";
  const declineLegacy = "estimate-toolbar-customer-decline";

  return (
    <div
      data-testid="mobile-doc-header"
      data-doc-type={docType}
      data-mobile-only="true"
      className="doc-mobile-top-block"
    >
      {/* 1 — Dark banner */}
      <div
        data-testid="mobile-doc-banner"
        style={{
          background: BANNER_BG,
          width: "100%",
          minHeight: 52,
          padding: "14px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <TypeLabel docType={docType} />
      </div>

      {/* 2 — Primary CTA block */}
      {!hideActions ? (
        <div
          style={{
            background: "#FFFFFF",
            padding: "14px 16px",
            borderBottom: "1px solid #E5E7EB",
          }}
        >
          <PrimaryCta
            docType={docType}
            amount={effectiveAmount}
            onPrimaryAction={onPrimaryAction}
            disabled={primaryActionDisabled}
            testid={approveTestid}
            legacyTestid={approveLegacy}
          />
          {primaryActionDisabled && primaryActionHint ? (
            <SignatureHint
              hint={primaryActionHint}
              onSignNow={onSignNow}
            />
          ) : null}
          {!isInvoice && onDecline ? (
            <DeclineCta
              docType={docType}
              onDecline={onDecline}
              testid={declineTestid}
              legacyTestid={declineLegacy}
            />
          ) : null}
          {!isInvoice && onRequestChanges ? (
            <div style={{ textAlign: "center", marginTop: 10 }}>
              <button
                type="button"
                onClick={onRequestChanges}
                data-testid="mobile-doc-request-changes"
                data-legacy-testid="estimate-toolbar-request-changes-btn"
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#2563EB",
                  fontSize: 13,
                  fontWeight: 700,
                  textDecoration: "underline",
                  cursor: "pointer",
                  padding: 6,
                }}
              >
                Request Changes
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* 3 — Two-column business info */}
      <BusinessInfoBlock
        company={company}
        docMeta={docMeta}
        docType={docType}
        brandColor={brandColor}
      />
    </div>
  );
}
