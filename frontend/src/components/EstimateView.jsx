/**
 * Slice R · <EstimateView> — shared estimate viewer.
 *
 * Feb-2026 · Outcome C — Canonical API paths are now /api/quotes/{qid}/*
 * (backing collection is db.quotes). The old /api/estimates/{eid}/*
 * aliases still work for one release cycle. Portal magic-link is
 * likewise /api/portal/quotes/via-token* (canonical) with the /portal
 * /estimates/via-token* alias retained.
 *
 * Reads /api/quotes/{qid}/full (authenticated) OR
 * /api/portal/quotes/via-token (magic-link) and renders:
 *
 *   • Admin toolbar (send/print/duplicate/archive/create-invoice/
 *     create-visit + request-changes/accept/decline + delete/edit)
 *   • Customer minimal toolbar (accept/decline + request-changes)
 *   • Status banner (when sent_at exists)
 *   • Estimate body identical for both roles — but the API strips
 *     margin/BH columns and rows for customers server-side.
 *
 * When accepted/declined the toolbar collapses to a locked status pill.
 */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Printer, Download, Send, Copy, Archive, FilePlus, CalendarPlus,
  MessageSquare, Check, X as XIcon, Trash2, Edit3, Loader2, CheckCircle2,
  XCircle, FileText, File as FileIcon,
} from "lucide-react";
import { api, TOKEN_KEY } from "@/api";
import "@/components/InvoiceView.css";
import "./EstimateView.css";
import "@/components/documents/docMobile.css";
// Feb-2026 · Batch #4 · Logo ship — shared tenant logo helper so
// every doc surface renders the same asset the PDF pipeline uses.
import { getTenantLogoUrl, DEFAULT_LOGO_ALT } from "@/lib/tenantLogo";
// Feb-2026 · Universal mobile-responsive redesign — mobile top
// block + terms slot. Both are gated to mobile viewports via
// docMobile.css (``.doc-mobile-top-block`` is display:none by
// default and only visible ≤ 767.98px), so desktop layout is
// unchanged.
import DocMobileHeader from "@/components/documents/DocMobileHeader";
import DocTermsSection from "@/components/documents/DocTermsSection";
// Feb-2026 · Desktop-unification — shared shell so invoice /
// estimate / quote all render the same skeleton at ≥ 768 px.
import DocDesktopShell from "@/components/documents/DocDesktopShell";
// Feb-2026 · Theme Refresh — customer surface reads the public
// branding endpoint via the magic-link token so the header /
// footer bands paint in the tenant's brand primary. Admin
// preview mode consumes the admin surface hook instead.
import { useTenantBranding, useBusinessSettings } from "@/hooks/useTenantBranding";
import EstimateFlipbook from "@/components/estimates/EstimateFlipbook";

const BACKEND = process.env.REACT_APP_BACKEND_URL;

function fmt(n) {
  return Number(n || 0).toFixed(2);
}

// Feb-2026 · Public Quote Attachments — human-readable byte size
// for the customer-facing Attachments list. Mirrors the backend
// ``emailer._human_size`` formatter so the size string next to
// each file in the reminder email + the on-page list stay in sync.
function _fmtAttachmentSize(nbytes) {
  const n = Math.max(0, Number(nbytes) || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// The estimate can be loaded via two paths:
//   { estimateId, isAdmin }        — authenticated fetch of /full
//   { token }                       — public magic-link
export default function EstimateView({
  estimateId,
  token,
  isAdmin = false,
  printable = false,
  _onDeleted,
}) {
  const _navigate = useNavigate();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [changesOpen, setChangesOpen] = useState(false);
  const [changesMsg, setChangesMsg] = useState("");
  const [declineOpen, setDeclineOpen] = useState(false);
  const [declineMsg, setDeclineMsg] = useState("");
  const [toast, setToast] = useState("");
  // Feb-2026 · Phase A — per-line decline UX state. Hooks live at
  // the top of the component so they're never conditionally called.
  const [busyLineIdx, setBusyLineIdx] = useState(null);
  const [lineDeclineOpen, setLineDeclineOpen] = useState(null);
  const [lineDeclineReason, setLineDeclineReason] = useState("");
  // Feb-2026 · Decline-per-group ship — one busy indicator keyed by
  // the group_key so clicking Decline / Restore on group A doesn't
  // freeze the button on group B while the network round-trips.
  const [busyGroupKey, setBusyGroupKey] = useState(null);

  // Feb-2026 · Theme Refresh — pull the tenant's brand primary +
  // logo so the shared shell paints the header/footer bands. The
  // customer magic-link surface (token present) reads from the
  // public branding endpoint; the admin preview surface reads
  // from the admin endpoint. Falls back silently on error so the
  // page still renders with default colours.
  const { branding: _brandingCust } = useTenantBranding(token || null);
  const { branding: _brandingAdmin } = useBusinessSettings({ skip: !!token });
  const _branding = token ? _brandingCust : _brandingAdmin;

  const load = useCallback(() => {
    setErr("");
    const outboundPath = token
      ? `/portal/quotes/via-token?token=${encodeURIComponent(token)}`
      : `/quotes/${estimateId}/full`;
    const p = api.get(outboundPath);
    p.then(setData).catch((e) => {
      setErr(e?.message || "Failed to load.");
    });
  }, [estimateId, token]);

  useEffect(() => { load(); }, [load]);

  const call = async (path, body) => {
    setBusy(true);
    try {
      const url = token
        ? `${path}?token=${encodeURIComponent(token)}`
        : path;
      const r = await api.post(url, body || {});
      setData(r);
      setToast("Saved");
      setTimeout(() => setToast(""), 2000);
    } catch (e) {
      setToast(e?.message || "Failed");
      setTimeout(() => setToast(""), 3000);
    } finally {
      setBusy(false);
    }
  };

  const accept = () => {
    if (!window.confirm("Approve this estimate?")) return;
    // Feb-2026 · Phase A — customer path uses the new path-based
    // token endpoint (approve/decline), which is idempotent + emits
    // ``quote_accepted`` for downstream Phase-B notification wiring.
    if (token) call2(`/portal/quotes/via-token/${encodeURIComponent(token)}/approve`);
    else call(`/quotes/${estimateId}/accept`);
  };
  const submitDecline = () => {
    if (token) {
      // Phase A path-based token endpoint (no ``?token=`` query).
      call2(
        `/portal/quotes/via-token/${encodeURIComponent(token)}/decline`,
        { reason: declineMsg },
      );
    } else {
      call(`/quotes/${estimateId}/decline`, { reason: declineMsg });
    }
    setDeclineOpen(false); setDeclineMsg("");
  };
  const submitChanges = () => {
    if (!changesMsg.trim()) return;
    if (token) call("/portal/quotes/via-token/request-changes", { message: changesMsg });
    else call(`/quotes/${estimateId}/request-changes`, { message: changesMsg });
    setChangesOpen(false); setChangesMsg("");
  };

  // Feb-2026 · Phase A — the new path-based approve/decline endpoints
  // do NOT accept a ``?token=`` query, so we bypass the shared
  // ``call()`` helper that auto-appends the token.
  const call2 = async (path, body) => {
    setBusy(true);
    try {
      const r = await api.post(path, body || {});
      setData(r); setToast("Saved");
      setTimeout(() => setToast(""), 2000);
    } catch (e) {
      setToast(e?.message || "Failed");
      setTimeout(() => setToast(""), 3000);
    } finally { setBusy(false); }
  };

  const openPdf = () => {
    const tok = localStorage.getItem(TOKEN_KEY);
    const url = `${BACKEND}/api/quotes/${estimateId}/pdf`;
    if (!tok) { window.open(url, "_blank"); return; }
    fetch(url, { headers: { Authorization: `Bearer ${tok}` } })
      .then((r) => r.blob())
      .then((blob) => window.open(URL.createObjectURL(blob), "_blank"))
      .catch(() => window.open(url, "_blank"));
  };

  if (err) return (
    <div
      className="p-4 rounded"
      style={{ background: "#FEE2E2", color: "#991B1B" }}
      data-testid="estimate-view-error"
      data-error-source={
        // Feb-2026 · Tester diag — distinguish the failure modes
        // the "Invalid estimate link" branch can surface:
        //   * ``backend-401``    → server rejected the token
        //   * ``backend-404``    → estimate not found for that tenant
        //   * ``backend-other``  → any other non-2xx (500, 503, etc.)
        //   * ``network``        → fetch itself failed (offline, CORS)
        //   * ``empty-payload``  → 200 with no body / malformed JSON
        err.toLowerCase().includes("invalid estimate")
          || err.toLowerCase().includes("expired")
          ? "backend-401"
          : err.toLowerCase().includes("not found")
          ? "backend-404"
          : err.toLowerCase().includes("network")
          ? "network"
          : err.toLowerCase().includes("request failed")
          ? "backend-other"
          : "unknown"
      }
    >
      {err}
    </div>
  );
  if (!data) return <div className="p-8 text-center"><Loader2 className="animate-spin inline" size={24}/></div>;

  const {
    company, bill_to, property_address, header, line_items, totals,
    notes, title, decision, accepted_at, declined_at, sent_at, sent_via,
    as_customer, customer_view, status,
    signature_status, require_signature_before_approve,
  } = data;

  // Feb-2026 · Phase A — actionable window (customer can approve /
  // decline whole doc + decline/undecline individual lines) is
  // ``status ∈ {sent, viewed}``. Once decision is set (accepted or
  // declined) the doc is locked as before.
  const _statusLc = String(status || "").toLowerCase();
  const actionable = _statusLc === "sent" || _statusLc === "viewed";

  // Feb-2026 · Phase C — signature-before-approve gate. When the
  // tenant has flipped ``require_signature_before_approve`` on AND
  // the doc is not yet signed, disable the Approve button + surface
  // a "Sign to enable" hint + a "Sign now" CTA. Decline is NOT
  // gated — customers can always decline without signing.
  const signatureGateBlocked = Boolean(
    require_signature_before_approve
    && String(signature_status || "").toLowerCase() !== "signed",
  );

  const openSignNowFlow = () => {
    // The existing signature capture flow is hosted separately;
    // this CTA emits a DOM custom event so the surrounding shell
    // (customer portal / magic-link page) can open its signature
    // widget without EstimateView needing to know about the shell.
    const eid = estimateId || data?.estimate_id || null;
    try {
      window.dispatchEvent(new CustomEvent("open-signature-flow", {
        detail: { estimateId: eid, token },
      }));
    } catch {
      /* SSR safety */
    }
    setToast("Opening signature capture…");
    setTimeout(() => setToast(""), 2500);
  };

  // Phase A · per-line decline via path-based token endpoint.
  const submitLineDecline = async () => {
    const idx = lineDeclineOpen;
    if (idx === null || idx === undefined) return;
    setBusyLineIdx(idx);
    try {
      const r = await api.post(
        `/portal/quotes/via-token/${encodeURIComponent(token || "")}` +
          `/line-items/${idx}/decline`,
        { reason: lineDeclineReason || "" },
      );
      setData(r);
      setToast("Line item declined");
      setTimeout(() => setToast(""), 2000);
    } catch (e) {
      setToast(e?.message || "Failed to decline");
      setTimeout(() => setToast(""), 3000);
    } finally {
      setBusyLineIdx(null);
      setLineDeclineOpen(null);
      setLineDeclineReason("");
    }
  };
  const undeclineLine = async (idx) => {
    setBusyLineIdx(idx);
    try {
      const r = await api.post(
        `/portal/quotes/via-token/${encodeURIComponent(token || "")}` +
          `/line-items/${idx}/undecline`,
        {},
      );
      setData(r);
      setToast("Line item restored");
      setTimeout(() => setToast(""), 2000);
    } catch (e) {
      setToast(e?.message || "Failed to restore");
      setTimeout(() => setToast(""), 3000);
    } finally {
      setBusyLineIdx(null);
    }
  };

  // Feb-2026 · Customer decline-per-group ship — magic-link + admin
  // group decline/restore. Server is authoritative — we render from
  // the returned payload rather than optimistically flipping local
  // state. Actor path chooses the correct route family:
  //   * ``token`` present → magic-link PATCH under /portal/... /groups/
  //   * ``token`` absent  → admin PATCH under /quotes/{qid}/groups/
  const declineGroup = async (groupKey) => {
    if (!groupKey) return;
    setBusyGroupKey(groupKey);
    try {
      const path = token
        ? `/portal/quotes/via-token/${encodeURIComponent(token)}` +
          `/groups/${encodeURIComponent(groupKey)}/decline`
        : `/quotes/${estimateId}/groups/${encodeURIComponent(groupKey)}/decline`;
      const r = await api.patch(path, {});
      setData(r);
      setToast("Group declined");
      setTimeout(() => setToast(""), 2000);
    } catch (e) {
      setToast(e?.message || "Failed to decline group");
      setTimeout(() => setToast(""), 3000);
    } finally {
      setBusyGroupKey(null);
    }
  };
  const restoreGroup = async (groupKey) => {
    if (!groupKey) return;
    setBusyGroupKey(groupKey);
    try {
      const path = token
        ? `/portal/quotes/via-token/${encodeURIComponent(token)}` +
          `/groups/${encodeURIComponent(groupKey)}/undecline`
        : `/quotes/${estimateId}/groups/${encodeURIComponent(groupKey)}/undecline`;
      const r = await api.patch(path, {});
      setData(r);
      setToast("Group restored");
      setTimeout(() => setToast(""), 2000);
    } catch (e) {
      setToast(e?.message || "Failed to restore group");
      setTimeout(() => setToast(""), 3000);
    } finally {
      setBusyGroupKey(null);
    }
  };

  const locked = decision === "accepted" || decision === "declined";

  // Phase K79 · Feb-2026 — Grouped customer-facing view fork.
  // The customer/portal caller renders the grouped rollup rows when
  // ``customer_group_display`` is on. Admin/printable views keep the
  // fully-itemized surface unchanged.
  //
  // Feb-2026 · Grouped-layout LOCK-ON ship — grouped layout is now
  // the SOLE customer-facing render mode. The historical toggle
  // ``customer_group_display`` and the magic-link "force-itemized
  // to allow per-line decline" carve-out are BOTH retired. Customer
  // still gets a doc-level Decline (top toolbar + a fresh
  // bottom-of-view "Decline Quote" button) — per-line decline is
  // no longer part of the customer surface. Admin itemized view is
  // untouched (``as_customer`` is false there).
  // See /app/memory/FEATURE_QUOTE_CUSTOMER_VIEW_GROUPED.md.
  const showGrouped = Boolean(as_customer && customer_view);
  const showAdminToolbar = isAdmin && !printable;
  const showCustomerToolbar = !isAdmin && !printable;

  // Feb-2026 · Universal mobile-responsive redesign — customer-only
  // top block. Rendered unconditionally; ``docMobile.css`` gates
  // its visibility to < 768px so desktop is unchanged. Admin +
  // printable surfaces skip it to keep the admin toolbar untouched
  // and the printable rendering PDF-parity intact.
  const showCustomerMobileHeader = !isAdmin && !printable;
  // Feb-2026 · Interactive Flipbook Estimate Viewer — customer-facing
  // branch. Admin previews + printable / PDF surfaces intentionally
  // stay on the classic renderer so PDF export, print, and the
  // admin toolbar keep parity. Flipbook is a customer-persuasion
  // surface, not an operations surface.
  if (data?.flipbook_enabled && !isAdmin && !printable) {
    return (
      <div className={`ev-shell iv-shell`} data-testid="estimate-view">
        <EstimateFlipbook
          data={data}
          onAccept={accept}
          onDeclineClick={() => setDeclineOpen(true)}
          onDownloadPdf={openPdf}
          signatureGateBlocked={signatureGateBlocked}
          onSignNow={openSignNowFlow}
          actionable={actionable}
          busy={busy}
          toast={toast}
          magicToken={token || null}
        />
        {/* Decline modal remains owned by the classic
            EstimateView because the flipbook accept page only
            needs to trigger it. */}
        {declineOpen ? (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
            role="dialog"
            data-testid="flipbook-decline-modal"
          >
            <div className="bg-white rounded-2xl p-6 w-full max-w-md" style={{ fontFamily: "Inter, system-ui, sans-serif" }}>
              <div className="text-lg font-bold mb-2">Decline proposal</div>
              <textarea
                className="w-full h-32 rounded border p-2 text-sm"
                placeholder="Optional — tell us why so we can improve"
                value={declineMsg}
                onChange={(e) => setDeclineMsg(e.target.value)}
                data-testid="flipbook-decline-reason"
              />
              <div className="flex justify-end gap-2 mt-3">
                <button
                  type="button"
                  className="px-4 py-2 rounded-full"
                  style={{ border: "1px solid #cbd5e1" }}
                  onClick={() => { setDeclineOpen(false); setDeclineMsg(""); }}
                  data-testid="flipbook-decline-cancel"
                >Cancel</button>
                <button
                  type="button"
                  className="px-4 py-2 rounded-full text-white"
                  style={{ backgroundColor: "#dc2626" }}
                  onClick={submitDecline}
                  data-testid="flipbook-decline-submit"
                >Decline proposal</button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    );
  }
  return (
    <div className={`ev-shell iv-shell ${printable ? "iv-printable" : ""}`} data-testid="estimate-view">
      {showCustomerMobileHeader ? (
        <DocMobileHeader
          docType="estimate"
          amount={totals?.total_estimated_cost || totals?.total || 0}
          hasDeclinedLines={Boolean(totals?.has_declined_lines)}
          adjustedAmount={totals?.adjusted_total}
          company={company || {}}
          docMeta={{
            number: header?.estimate_number,
            date: header?.expiration_date || header?.estimate_date,
          }}
          onPrimaryAction={locked || !actionable ? undefined : accept}
          primaryActionDisabled={
            Boolean(busy) || signatureGateBlocked || locked || !actionable
          }
          primaryActionHint={
            signatureGateBlocked ? "Sign to enable Approve" : null
          }
          onSignNow={signatureGateBlocked ? openSignNowFlow : undefined}
          onDecline={locked || !actionable
            ? undefined : () => setDeclineOpen(true)}
          onRequestChanges={locked || !actionable
            ? undefined : () => setChangesOpen(true)}
          hideActions={locked || !actionable}
        />
      ) : null}
      <DocDesktopShell
        docType="estimate"
        testId="estimate-desktop-shell"
        printable={printable}
        brandingHeader={printable ? null : {
          primary: _branding?.brand_primary_hex,
          secondary: _branding?.brand_secondary_hex,
          logoUrl: _branding?.logo_url,
          companyName: _branding?.company_display_name || company?.name,
          contactLines: [
            (_branding?.mailing_address || "").split("\n")[0]
              || company?.address,
            _branding?.phone || company?.phone,
            _branding?.email,
            _branding?.website || company?.website,
          ].filter(Boolean),
          footerNote: _branding?.footer_note,
        }}
        belowToolbar={!printable ? (
          <div
            className="ev-toolbar"
            data-testid={showAdminToolbar ? "estimate-toolbar-admin" : "estimate-toolbar-customer"}
          >
            {showAdminToolbar ? (
              <>
                <div className="ev-tool-group">
                  <button className="iv-btn" data-testid="estimate-toolbar-send-btn">
                    <Send size={14}/> Send
                  </button>
                  <button className="iv-btn" onClick={() => window.print()} data-testid="estimate-toolbar-print-btn">
                    <Printer size={14}/> Print
                  </button>
                  <button className="iv-btn" onClick={openPdf} data-testid="invoice-download-pdf-btn">
                    <Download size={14}/> PDF
                  </button>
                  <button className="iv-btn" data-testid="estimate-toolbar-duplicate-btn">
                    <Copy size={14}/> Duplicate
                  </button>
                  <button className="iv-btn" data-testid="estimate-toolbar-archive-btn">
                    <Archive size={14}/> Archive
                  </button>
                  <button className="iv-btn" data-testid="estimate-toolbar-create-invoice-btn">
                    <FilePlus size={14}/> Create Invoice
                  </button>
                  <button className="iv-btn" data-testid="estimate-toolbar-create-visit-btn">
                    <CalendarPlus size={14}/> + Create Visit
                  </button>
                </div>
                <div className="ev-tool-group">
                  {!locked ? (
                    <>
                      <button
                        className="iv-btn"
                        onClick={() => setChangesOpen(true)}
                        disabled={busy}
                        data-testid="estimate-toolbar-request-changes-btn"
                      >
                        <MessageSquare size={14}/> Request Changes
                      </button>
                      <button
                        className="iv-btn ev-btn-accept"
                        onClick={accept}
                        disabled={busy}
                        data-testid="estimate-toolbar-accept-btn"
                      >
                        <Check size={14}/> Accept
                      </button>
                      <button
                        className="iv-btn ev-btn-decline"
                        onClick={() => setDeclineOpen(true)}
                        disabled={busy}
                        data-testid="estimate-toolbar-decline-btn"
                      >
                        <XIcon size={14}/> Decline
                      </button>
                    </>
                  ) : null}
                </div>
                <div className="ev-tool-group ev-right">
                  <button className="iv-btn ev-btn-danger" data-testid="estimate-toolbar-delete-btn">
                    <Trash2 size={14}/> Delete
                  </button>
                  <button className="iv-btn" data-testid="estimate-toolbar-edit-btn">
                    <Edit3 size={14}/> Edit
                  </button>
                </div>
              </>
            ) : null}
            {showCustomerToolbar && !locked && actionable ? (
              <div className="ev-tool-group ev-customer-cta">
                <button
                  className="iv-btn"
                  onClick={() => setChangesOpen(true)}
                  disabled={busy}
                  data-testid="estimate-toolbar-request-changes-btn"
                >
                  <MessageSquare size={14}/> Request Changes
                </button>
                <button
                  className="iv-btn ev-btn-accept"
                  onClick={accept}
                  disabled={busy || signatureGateBlocked}
                  data-testid="estimate-toolbar-customer-approve"
                  data-legacy-testid="estimate-toolbar-accept-btn"
                  data-signature-blocked={signatureGateBlocked ? "true" : "false"}
                  title={signatureGateBlocked ? "Sign to enable" : undefined}
                >
                  <Check size={14}/> Approve
                </button>
                <button
                  className="iv-btn ev-btn-decline"
                  onClick={() => setDeclineOpen(true)}
                  disabled={busy}
                  data-testid="estimate-toolbar-customer-decline"
                  data-legacy-testid="estimate-toolbar-decline-btn"
                >
                  <XIcon size={14}/> Decline
                </button>
                {signatureGateBlocked ? (
                  <div
                    className="ev-signature-gate-hint"
                    data-testid="approve-blocked-by-signature-hint"
                    style={{
                      fontSize: 12,
                      color: "#92400E",
                      background: "#FEF3C7",
                      border: "1px solid #FCD34D",
                      padding: "6px 10px",
                      borderRadius: 8,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                      marginLeft: 8,
                    }}
                  >
                    <span>Sign to enable Approve</span>
                    <button
                      type="button"
                      className="iv-btn"
                      style={{
                        fontSize: 12,
                        padding: "4px 10px",
                        background: "#0EA5E9",
                        color: "#fff",
                        border: "none",
                      }}
                      onClick={openSignNowFlow}
                      data-testid="approve-sign-now-cta"
                    >
                      Sign now
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}
            {/* Feb-2026 · Phase A — legacy testid preservation. Any
                caller still querying the old ``estimate-toolbar-accept
                -btn`` / ``estimate-toolbar-decline-btn`` testids will
                hit these hidden spans (display: none) so lookups don't
                silently fail. Delete when Phase C ships. */}
            {showCustomerToolbar && !locked && actionable ? (
              <>
                <span style={{ display: "none" }} data-testid="estimate-toolbar-accept-btn" aria-hidden />
                <span style={{ display: "none" }} data-testid="estimate-toolbar-decline-btn" aria-hidden />
              </>
            ) : null}

            {locked ? (
              <div
                className={`ev-locked-pill ${decision === "accepted" ? "ev-locked-accept" : "ev-locked-decline"}`}
                data-testid={decision === "accepted" ? "estimate-accepted-pill" : "estimate-declined-pill"}
              >
                {decision === "accepted" ? <CheckCircle2 size={16}/> : <XCircle size={16}/>}
                {decision === "accepted"
                  ? `Accepted on ${String(accepted_at || "").slice(0, 10)}`
                  : `Declined on ${String(declined_at || "").slice(0, 10)}`}
              </div>
            ) : null}
          </div>
        ) : null}
        banner={sent_at && !printable ? (
          <div className="ev-banner" data-testid="estimate-status-banner">
            Estimate #{header.estimate_number} was sent to customer by {sent_via || "email"}
          </div>
        ) : null}
        headerLeft={(
          <>
            {/* Phase 34 · Feb 2026 — brand logo header. Falls back to
                the shared /logo-full.png bundled with the frontend so
                every estimate preview matches PDFs, invoices + emails. */}
            <img
              src={getTenantLogoUrl(company)}
              alt={company.name || DEFAULT_LOGO_ALT}
              className="iv-brand-logo"
              data-testid="doc-header-logo"
              data-surface="estimate"
            />
            <div className="iv-company-name">{company.name}</div>
            {company.address ? <div>{company.address}</div> : null}
            {company.phone ? <div><a href={`tel:${company.phone}`} className="iv-link">{company.phone}</a></div> : null}
            {company.website ? (
              <div>
                <a href={`https://${String(company.website).replace(/^https?:\/\//, "")}`}
                    target="_blank" rel="noopener noreferrer" className="iv-link">
                  {company.website}
                </a>
              </div>
            ) : null}
          </>
        )}
        title={<span data-testid="estimate-title">Estimate</span>}
        headerMeta={(
          <div data-testid="estimate-header">
            <table className="iv-kv">
              <tbody>
                <tr><td className="iv-kv-label">Customer #</td><td className="iv-kv-value">{header.customer_number || "—"}</td></tr>
                <tr><td className="iv-kv-label">Estimate #</td><td className="iv-kv-value">{header.estimate_number}</td></tr>
                <tr><td className="iv-kv-label">Estimate Date</td><td className="iv-kv-value">{header.estimate_date}</td></tr>
                {header.expiration_date ? (
                  <tr><td className="iv-kv-label">Expires</td><td className="iv-kv-value">{header.expiration_date}</td></tr>
                ) : null}
                <tr><td className="iv-kv-label">Status</td><td className="iv-kv-value">{data.status}</td></tr>
              </tbody>
            </table>
          </div>
        )}
        billTo={(
          <>
            <div className="iv-bill-name">{bill_to.name || "—"}</div>
            {bill_to.address ? <div>{bill_to.address}</div> : null}
          </>
        )}
        midTitle={title ? <div className="ev-est-title">{title}</div> : null}
        propertyAddress={property_address ? (
          <span><b>Property Address:</b> {property_address}</span>
        ) : null}
        lines={(
          <div className="ev-lines-wrap">
            {showGrouped ? (
              <>
              <table className="iv-lines hidden sm:table"
                      data-testid="estimate-grouped-lines-table">
                <thead>
                  <tr>
                    <th>Service</th>
                    <th className="iv-num">Subtotal</th>
                    {/* Feb-2026 · Decline-per-group ship — action
                        column rendered when the quote is actionable
                        (customer surface) OR when an admin is
                        viewing and can decline on behalf. Header
                        stays hidden otherwise so the print layout
                        matches the current PDF (2 columns). */}
                    {(actionable && !locked) || (!as_customer && !printable)
                      ? <th className="iv-num" style={{ width: 140 }}></th>
                      : null}
                  </tr>
                </thead>
                <tbody>
                  {(customer_view.groups || []).length === 0 ? (
                    <tr><td colSpan={3} className="iv-empty">
                      No services on this estimate.
                    </td></tr>
                  ) : (customer_view.groups || []).map((g, i) => {
                    const gKey = g.group_key || g.category_id || `other-${i}`;
                    const isDeclined = Boolean(g.declined);
                    const rowStyle = isDeclined
                      ? { textDecoration: "line-through", opacity: 0.55 }
                      : undefined;
                    const showActionCol =
                      (actionable && !locked)
                      || (!as_customer && !printable);
                    const isBusy = busyGroupKey === gKey;
                    return (
                    <tr key={gKey}
                        data-testid={
                          `estimate-grouped-row-${g.category_id || "other"}`
                        }
                        data-group-declined={isDeclined ? "true" : "false"}>
                      <td style={rowStyle}>
                        <div><b>{g.label}</b></div>
                        {g.description ? (
                          <div className="ev-group-desc"
                                data-testid={
                                  `estimate-grouped-desc-${g.category_id || "other"}`
                                }>
                            {g.description}
                          </div>
                        ) : null}
                        {isDeclined && g.declined_at ? (
                          <div
                            style={{
                              fontSize: 11,
                              color: "#7F1D1D",
                              marginTop: 2,
                              textDecoration: "none",
                            }}
                            data-testid={
                              `estimate-grouped-declined-label-${g.category_id || "other"}`
                            }
                          >
                            Declined {String(g.declined_at).slice(0, 10)}
                          </div>
                        ) : null}
                      </td>
                      <td className="iv-num" style={rowStyle}>
                        {fmt(g.subtotal)}
                      </td>
                      {showActionCol ? (
                        <td className="iv-num">
                          {isDeclined ? (
                            <button
                              type="button"
                              onClick={() => restoreGroup(gKey)}
                              disabled={isBusy}
                              className="ev-group-btn"
                              style={{
                                padding: "4px 10px",
                                fontSize: 12,
                                borderRadius: 6,
                                border: "1px solid #D4D4D8",
                                background: "#FFFFFF",
                                cursor: isBusy ? "wait" : "pointer",
                              }}
                              data-testid={
                                `estimate-grouped-restore-btn-${g.category_id || "other"}`
                              }
                            >
                              Restore
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => declineGroup(gKey)}
                              disabled={isBusy}
                              className="ev-group-btn"
                              style={{
                                padding: "4px 10px",
                                fontSize: 12,
                                borderRadius: 6,
                                border: "1px solid #DC2626",
                                background: "#FFFFFF",
                                color: "#DC2626",
                                cursor: isBusy ? "wait" : "pointer",
                              }}
                              data-testid={
                                `estimate-grouped-decline-btn-${g.category_id || "other"}`
                              }
                            >
                              Decline
                            </button>
                          )}
                        </td>
                      ) : null}
                    </tr>
                    );
                  })}
                </tbody>
              </table>
              {/* Feb-2026 · Responsive quote/estimate ship — stacked
                  card layout for < sm (640px). Same server-truth data
                  as the grouped table above, distinct testids
                  (``-mobile`` suffix) so per-suite duplicates don't
                  break existing table-based assertions. */}
              <ul className="ev-lines-cards sm:hidden"
                  data-testid="estimate-grouped-lines-cards">
                {(customer_view.groups || []).length === 0 ? (
                  <li className="ev-line-card ev-line-card-empty">
                    No services on this estimate.
                  </li>
                ) : (customer_view.groups || []).map((g, i) => {
                  const gKey = g.group_key || g.category_id || `other-${i}`;
                  const isDeclined = Boolean(g.declined);
                  const cardStyle = isDeclined
                    ? { textDecoration: "line-through", opacity: 0.55 }
                    : undefined;
                  const showActionCol =
                    (actionable && !locked)
                    || (!as_customer && !printable);
                  const isBusy = busyGroupKey === gKey;
                  return (
                    <li key={gKey}
                        className="ev-line-card"
                        data-testid={
                          `estimate-grouped-card-${g.category_id || "other"}`
                        }
                        data-group-declined={isDeclined ? "true" : "false"}>
                      <div className="ev-line-card-desc" style={cardStyle}>
                        <div><b>{g.label}</b></div>
                        {g.description ? (
                          <div className="ev-group-desc">{g.description}</div>
                        ) : null}
                        {isDeclined && g.declined_at ? (
                          <div style={{
                                  fontSize: 11,
                                  color: "#7F1D1D",
                                  marginTop: 2,
                                  textDecoration: "none",
                                }}>
                            Declined {String(g.declined_at).slice(0, 10)}
                          </div>
                        ) : null}
                      </div>
                      <div className="ev-line-card-row" style={cardStyle}>
                        <span className="ev-line-card-label">Subtotal</span>
                        <span className="ev-line-card-value">
                          {fmt(g.subtotal)}
                        </span>
                      </div>
                      {showActionCol ? (
                        <div className="ev-line-card-action">
                          {isDeclined ? (
                            <button
                              type="button"
                              onClick={() => restoreGroup(gKey)}
                              disabled={isBusy}
                              className="ev-group-btn"
                              style={{
                                padding: "10px 14px",
                                fontSize: 13,
                                borderRadius: 8,
                                border: "1px solid #D4D4D8",
                                background: "#FFFFFF",
                                cursor: isBusy ? "wait" : "pointer",
                                width: "100%",
                                minHeight: 44,
                              }}
                              data-testid={
                                `estimate-grouped-restore-btn-mobile-${g.category_id || "other"}`
                              }
                            >
                              Restore
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => declineGroup(gKey)}
                              disabled={isBusy}
                              className="ev-group-btn"
                              style={{
                                padding: "10px 14px",
                                fontSize: 13,
                                borderRadius: 8,
                                border: "1px solid #DC2626",
                                background: "#FFFFFF",
                                color: "#DC2626",
                                cursor: isBusy ? "wait" : "pointer",
                                width: "100%",
                                minHeight: 44,
                              }}
                              data-testid={
                                `estimate-grouped-decline-btn-mobile-${g.category_id || "other"}`
                              }
                            >
                              Decline
                            </button>
                          )}
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
              </>
            ) : (
            <>
            <table className="iv-lines hidden sm:table" data-testid="estimate-line-items-table">
              <thead>
                <tr>
                  <th>Description</th>
                  {!as_customer ? <th className="iv-num">Calc</th> : null}
                  {!as_customer ? <th className="iv-num">Cost/Rate</th> : null}
                  <th className="iv-num">Qty/Hr</th>
                  <th className="iv-num">Visits</th>
                  {!as_customer ? <th className="iv-num">M.Rate</th> : null}
                  {!as_customer ? <th className="iv-num">BH</th> : null}
                  {!as_customer ? <th className="iv-num">T.BH</th> : null}
                  {!as_customer ? <th className="iv-num">T.B.Cost</th> : null}
                  {!as_customer ? <th className="iv-num">Margin %</th> : null}
                  <th className="iv-num">Total</th>
                  {/* Feb-2026 · Phase A — per-line decline column
                      (customer + magic-link only, actionable window). */}
                  {as_customer && actionable && !locked ? <th></th> : null}
                </tr>
              </thead>
              <tbody>
                {line_items.length === 0 ? (
                  <tr><td colSpan={11} className="iv-empty">No line items.</td></tr>
                ) : line_items.map((li, i) => {
                  const isDeclined = (li.customer_status || "pending") === "declined";
                  const rowStyle = isDeclined
                    ? { textDecoration: "line-through", opacity: 0.55 }
                    : undefined;
                  return (
                  <tr key={i} data-testid={`estimate-line-item-row-${i}`}
                       data-customer-status={li.customer_status || "pending"}>
                    <td style={rowStyle}>
                      {li.description}
                      {isDeclined ? (
                        <span style={{
                                marginLeft: 8, fontSize: 11,
                                padding: "2px 6px",
                                borderRadius: 6,
                                background: "#FEE2E2",
                                color: "#7F1D1D",
                                textDecoration: "none",
                              }}
                              data-testid={`estimate-line-item-declined-chip-${i}`}>
                          Declined
                        </span>
                      ) : null}
                    </td>
                    {!as_customer ? <td className="iv-num" style={rowStyle}>{li.calc || "—"}</td> : null}
                    {!as_customer ? <td className="iv-num" style={rowStyle}>{fmt(li.cost_rate)}</td> : null}
                    <td className="iv-num" style={rowStyle} data-mlabel="Qty/Hr">{li.qty_hr || li.quantity || 0}</td>
                    <td className="iv-num" style={rowStyle} data-mlabel="Visits">{li.visits || 1}</td>
                    {!as_customer ? <td className="iv-num" style={rowStyle}>{fmt(li.m_rate)}</td> : null}
                    {!as_customer ? <td className="iv-num" style={rowStyle}>{fmt(li.bh)}</td> : null}
                    {!as_customer ? <td className="iv-num" style={rowStyle}>{fmt(li.t_bh)}</td> : null}
                    {!as_customer ? <td className="iv-num" style={rowStyle}>{fmt(li.t_b_cost)}</td> : null}
                    {!as_customer ? <td className="iv-num" style={rowStyle}>{fmt(li.margin_pct)}</td> : null}
                    <td className="iv-num" style={rowStyle} data-mlabel="Total">{fmt(li.total)}</td>
                    {as_customer && actionable && !locked ? (
                      <td className="iv-num">
                        {isDeclined ? (
                          <button
                            className="iv-btn"
                            style={{ fontSize: 12 }}
                            disabled={busyLineIdx === i}
                            onClick={() => undeclineLine(i)}
                            data-testid={`estimate-line-item-undecline-${i}`}
                          >
                            Undo decline
                          </button>
                        ) : (
                          <button
                            className="iv-btn ev-btn-decline"
                            style={{ fontSize: 12 }}
                            disabled={busyLineIdx === i}
                            onClick={() => setLineDeclineOpen(i)}
                            data-testid={`estimate-line-item-decline-${i}`}
                          >
                            Decline
                          </button>
                        )}
                      </td>
                    ) : null}
                  </tr>
                );})}
              </tbody>
            </table>
            {/* Feb-2026 · Responsive quote/estimate ship — itemized
                stacked-card fallback for < sm. */}
            <ul className="ev-lines-cards sm:hidden"
                data-testid="estimate-line-items-cards">
              {line_items.length === 0 ? (
                <li className="ev-line-card ev-line-card-empty">No line items.</li>
              ) : line_items.map((li, i) => {
                const isDeclined = (li.customer_status || "pending") === "declined";
                const cardStyle = isDeclined
                  ? { textDecoration: "line-through", opacity: 0.55 }
                  : undefined;
                return (
                  <li key={i}
                      className="ev-line-card"
                      data-testid={`estimate-line-item-card-${i}`}
                      data-customer-status={li.customer_status || "pending"}>
                    <div className="ev-line-card-desc" style={cardStyle}>
                      {li.description}
                      {isDeclined ? (
                        <span style={{
                                marginLeft: 8, fontSize: 11,
                                padding: "2px 6px",
                                borderRadius: 6,
                                background: "#FEE2E2",
                                color: "#7F1D1D",
                                textDecoration: "none",
                              }}
                              data-testid={`estimate-line-item-declined-chip-mobile-${i}`}>
                          Declined
                        </span>
                      ) : null}
                    </div>
                    <div className="ev-line-card-row" style={cardStyle}>
                      <span className="ev-line-card-label">Subtotal</span>
                      <span className="ev-line-card-value">{fmt(li.total)}</span>
                    </div>
                    {as_customer && actionable && !locked ? (
                      <div className="ev-line-card-action">
                        {isDeclined ? (
                          <button
                            className="iv-btn"
                            style={{ fontSize: 13, width: "100%", minHeight: 44 }}
                            disabled={busyLineIdx === i}
                            onClick={() => undeclineLine(i)}
                            data-testid={`estimate-line-item-undecline-mobile-${i}`}
                          >
                            Undo decline
                          </button>
                        ) : (
                          <button
                            className="iv-btn ev-btn-decline"
                            style={{ fontSize: 13, width: "100%", minHeight: 44 }}
                            disabled={busyLineIdx === i}
                            onClick={() => setLineDeclineOpen(i)}
                            data-testid={`estimate-line-item-decline-mobile-${i}`}
                          >
                            Decline
                          </button>
                        )}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
            </>
            )}
          </div>
        )}
        notes={notes ? (
          <div data-testid="estimate-notes">
            <div className="iv-notes-body">{notes}</div>
          </div>
        ) : null}
        totals={(
          <table className="ev-totals" data-testid="estimate-totals-table">
            <tbody>
              <tr><td>Subtotal</td><td data-testid="estimate-totals-subtotal">{fmt(totals.subtotal)}</td></tr>
              <tr><td>Taxes</td><td data-testid="estimate-totals-taxes">{fmt(totals.taxes)}</td></tr>
              <tr><td>Amount Paid</td><td data-testid="estimate-totals-amount-paid">{fmt(totals.amount_paid)}</td></tr>
              <tr className="ev-total-highlight">
                <td>Total Estimated Cost</td>
                <td data-testid="estimate-totals-cost">{fmt(totals.total_estimated_cost)}</td>
              </tr>
              {/* Feb-2026 · Phase A — Original / Adjusted summary.
                  Only shown when the customer has flagged at least
                  one line as declined. Server-truth values from
                  ``recompute_customer_adjusted_totals``. */}
              {totals.has_declined_lines ? (
                <tr data-testid="estimate-totals-adjusted-row">
                  <td>Adjusted for declined items</td>
                  <td>
                    <span style={{
                            textDecoration: "line-through",
                            color: "#9CA3AF",
                            marginRight: 8,
                          }}
                          data-testid="estimate-totals-original">
                      ${fmt(totals.original_total)}
                    </span>
                    <span style={{ fontWeight: 700 }}
                          data-testid="estimate-totals-adjusted">
                      ${fmt(totals.adjusted_total)}
                    </span>
                  </td>
                </tr>
              ) : null}
              {!as_customer ? (
                <>
                  <tr><td>Estimated Profit</td><td data-testid="estimate-totals-profit">{fmt(totals.estimated_profit)}</td></tr>
                  <tr><td>Total B.Hrs</td><td data-testid="estimate-totals-b-hrs">{fmt(totals.total_b_hrs)}</td></tr>
                  <tr><td>Total B.Hrs Revenue</td><td>{fmt(totals.total_b_hrs_revenue)}</td></tr>
                </>
              ) : null}
            </tbody>
          </table>
        )}
        termsSection={(
          <>
            {/* Feb-2026 · Public Quote Attachments — customer-facing
                downloads section. Renders only when the viewer payload
                carries ≥ 1 attachment. Each row is a full-width
                tappable button below sm (44px min tap target) and a
                compact horizontal row at ≥ sm. The ``url`` on each
                entry is already absolute + tokenised by the backend
                (see routers/estimate_viewer.py::_build_payload), so
                the anchor here is just a passthrough. */}
            {(data?.attachments || []).length > 0 ? (
              <div
                className="ev-attachments-wrap"
                data-testid="estimate-attachments-section"
              >
                <div className="ev-attachments-title">Attachments</div>
                <ul className="ev-attachments-list">
                  {(data.attachments || []).map((att, i) => {
                    // Feb-2026 · Attachment thumbnails — branch on the
                    // ``content_type`` field the backend already emits
                    // (see FEATURE_PUBLIC_QUOTE_ATTACHMENTS.md). Image
                    // types render an <img> preview (lazy-loaded); PDF
                    // + everything else render a lucide glyph inside a
                    // matching 64px square. The wrapping <a> mirrors
                    // the existing Download button so a click on the
                    // preview still opens the same tokenised URL in a
                    // new tab.
                    const ct = String(att.content_type || "").toLowerCase();
                    const isImg = ct.startsWith("image/");
                    const isPdf = ct === "application/pdf";
                    const iconTile = (
                      <div
                        className="w-16 h-16 rounded-md border border-gray-200 bg-white flex items-center justify-center text-gray-500 shrink-0"
                        aria-hidden="true"
                      >
                        {isPdf
                          ? <FileText size={28} />
                          : <FileIcon size={28} />}
                      </div>
                    );
                    return (
                    <li
                      key={att.id || i}
                      className="ev-attachment-row"
                      data-testid={`estimate-attachment-row-${i}`}
                    >
                      <a
                        href={att.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block shrink-0 self-start sm:self-auto"
                        aria-label={`Open ${att.filename} in a new tab`}
                        data-testid={`estimate-attachment-thumb-${i}`}
                      >
                        {isImg ? (
                          <img
                            src={att.url}
                            alt={att.filename}
                            loading="lazy"
                            className="w-16 h-16 object-cover rounded-md border border-gray-200 bg-white"
                          />
                        ) : iconTile}
                      </a>
                      <div className="ev-attachment-meta">
                        <span className="ev-attachment-name">
                          {att.filename}
                        </span>
                        <span className="ev-attachment-size">
                          {_fmtAttachmentSize(att.size)}
                        </span>
                      </div>
                      <a
                        href={att.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="ev-attachment-btn"
                        data-testid={`estimate-attachment-download-${i}`}
                      >
                        Download
                      </a>
                    </li>
                    );
                  })}
                </ul>
              </div>
            ) : null}
            <DocTermsSection
              terms={data?.terms_and_conditions}
              testidPrefix="estimate"
            />
          </>
        )}
        disclaimer={(
          <div className="ev-disclaimer" data-testid="estimate-disclaimer">
            This estimate is a good faith estimate only and is not a guarantee of final cost.
            It is based on anticipated labor, materials, and conditions known at the time of
            estimating. Unforeseen conditions, hidden issues, design changes, or client-requested
            modifications may result in additional costs beyond this estimate. Any additional
            charges will be documented and communicated for approval as soon as reasonably possible.
          </div>
        )}
      />

      {/* Feb-2026 · Grouped-layout LOCK-ON ship — single bottom-of-
          view Decline button for customer-facing surfaces. Replaces
          the per-line decline buttons (which are now dead code on
          the customer view since grouped layout is always on).
          Admin + printable + locked + non-actionable states hide it. */}
      {as_customer && actionable && !locked && !isAdmin && !printable ? (
        <div
          className="ev-bottom-actions"
          style={{
            marginTop: 16,
            display: "flex",
            justifyContent: "flex-end",
          }}
          data-testid="estimate-bottom-actions"
        >
          <button
            className="iv-btn ev-btn-decline"
            onClick={() => setDeclineOpen(true)}
            disabled={busy}
            data-testid="estimate-bottom-decline-quote-btn"
          >
            <XIcon size={14}/> Decline Quote
          </button>
        </div>
      ) : null}

      {/* Modals for decline/request-changes */}
      {/* Feb-2026 · Phase A — per-line decline confirm dialog. */}
      {lineDeclineOpen !== null ? (
        <ModalScrim onClose={() => { setLineDeclineOpen(null); setLineDeclineReason(""); }}>
          <h3 className="ev-modal-title" data-testid="estimate-line-item-decline-dialog">
            Decline this line item?
          </h3>
          <p className="ev-modal-help">
            You're telling us you don't want{" "}
            <b>{line_items[lineDeclineOpen]?.description || "this item"}</b>{" "}
            (${fmt(line_items[lineDeclineOpen]?.total)}). Your total will
            adjust automatically. You can undo this until you approve or
            decline the whole estimate.
          </p>
          <textarea
            rows={2}
            placeholder="Optional reason"
            value={lineDeclineReason}
            onChange={(e) => setLineDeclineReason(e.target.value.slice(0, 200))}
            className="ev-modal-input"
            data-testid="estimate-line-item-decline-reason"
          />
          <div className="ev-modal-actions">
            <button className="iv-btn"
                    onClick={() => { setLineDeclineOpen(null); setLineDeclineReason(""); }}
                    data-testid="estimate-line-item-decline-cancel">
              Cancel
            </button>
            <button className="iv-btn ev-btn-decline"
                    onClick={submitLineDecline}
                    disabled={busyLineIdx !== null}
                    data-testid="estimate-line-item-decline-confirm">
              Decline this line
            </button>
          </div>
        </ModalScrim>
      ) : null}
      {declineOpen ? (
        <ModalScrim onClose={() => setDeclineOpen(false)}>
          <h3 className="ev-modal-title">Decline this estimate</h3>
          <p className="ev-modal-help">Optional — let us know why so we can improve.</p>
          <textarea
            rows={3}
            value={declineMsg}
            onChange={(e) => setDeclineMsg(e.target.value)}
            className="ev-modal-input"
            data-testid="estimate-decline-reason"
          />
          <div className="ev-modal-actions">
            <button className="iv-btn" onClick={() => setDeclineOpen(false)}>Cancel</button>
            <button className="iv-btn ev-btn-decline" onClick={submitDecline} data-testid="estimate-decline-confirm">
              Decline
            </button>
          </div>
        </ModalScrim>
      ) : null}
      {changesOpen ? (
        <ModalScrim onClose={() => setChangesOpen(false)}>
          <h3 className="ev-modal-title">Request changes</h3>
          <p className="ev-modal-help">Tell us what you'd like changed on this estimate.</p>
          <textarea
            rows={4}
            value={changesMsg}
            onChange={(e) => setChangesMsg(e.target.value)}
            className="ev-modal-input"
            data-testid="estimate-changes-message"
          />
          <div className="ev-modal-actions">
            <button className="iv-btn" onClick={() => setChangesOpen(false)}>Cancel</button>
            <button
              className="iv-btn iv-btn-primary"
              onClick={submitChanges}
              disabled={!changesMsg.trim()}
              data-testid="estimate-changes-confirm"
            >
              Send
            </button>
          </div>
        </ModalScrim>
      ) : null}

      {/* Feb-2026 · Theme Refresh — sticky mobile action bar.
          Visible only below 768px (via CSS media query on the wrapper)
          and only when the quote is actionable + the customer hasn't
          locked in a decision. Approve + Decline are the primary
          customer actions on the magic-link surface. */}
      {token && !printable && actionable && !locked ? (
        <div
          className="ev-mobile-action-bar md:hidden flex items-stretch"
          data-testid="estimate-mobile-action-bar"
          style={{
            position: "fixed",
            left: 0, right: 0, bottom: 0,
            padding: "10px 12px",
            paddingBottom: "calc(10px + env(safe-area-inset-bottom, 0px))",
            background: "#FFFFFF",
            borderTop: "1px solid #E5E7EB",
            boxShadow: "0 -4px 14px rgba(15,23,42,0.06)",
            // Feb-2026 · Tester fix — inline ``display: flex`` used to
            // override Tailwind's non-``!important`` ``md:hidden`` at
            // ≥ 768 px, leaking the sticky bar to desktop. Display is
            // now driven entirely by Tailwind utilities on the
            // className above (``flex`` sets ``display:flex``,
            // ``md:hidden`` wins at ≥ 768 px). Gap + z-index stay
            // inline — they don't clash with any responsive class.
            gap: 8,
            zIndex: 45,
          }}
        >
          <button
            type="button"
            onClick={() => setDeclineOpen(true)}
            className="iv-btn ev-btn-decline"
            style={{
              flex: 1, minHeight: 40,
              border: `1px solid ${_branding?.brand_secondary_hex || "#DC2626"}`,
              color: _branding?.brand_secondary_hex || "#DC2626",
              background: "#FFFFFF",
              fontWeight: 600,
            }}
            data-testid="estimate-mobile-decline-btn"
          >
            Decline
          </button>
          <button
            type="button"
            onClick={() => call2(`/quotes/${estimateId || ""}/accept`)}
            className="iv-btn"
            style={{
              flex: 1, minHeight: 40,
              background: _branding?.brand_primary_hex || "#0B4A6F",
              color: "#FFFFFF",
              fontWeight: 700,
            }}
            data-testid="estimate-mobile-approve-btn"
          >
            Approve
          </button>
        </div>
      ) : null}

      {toast ? <div className="ev-toast">{toast}</div> : null}
    </div>
  );
}

function ModalScrim({ children, onClose }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.5)" }}
      onClick={onClose}
    >
      <div
        className="ev-modal"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
