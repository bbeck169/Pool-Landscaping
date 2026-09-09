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
  XCircle,
} from "lucide-react";
import { api, TOKEN_KEY } from "@/api";
import "@/components/InvoiceView.css";
import "./EstimateView.css";
// Feb-2026 · Batch #4 · Logo ship — shared tenant logo helper so
// every doc surface renders the same asset the PDF pipeline uses.
import { getTenantLogoUrl, DEFAULT_LOGO_ALT } from "@/lib/tenantLogo";

const BACKEND = process.env.REACT_APP_BACKEND_URL;

function fmt(n) {
  return Number(n || 0).toFixed(2);
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

  const load = useCallback(() => {
    setErr("");
    const p = token
      ? api.get(`/portal/quotes/via-token?token=${encodeURIComponent(token)}`)
      : api.get(`/quotes/${estimateId}/full`);
    p.then(setData).catch((e) => setErr(e?.message || "Failed to load."));
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

  if (err) return <div className="p-4 rounded" style={{ background: "#FEE2E2", color: "#991B1B" }}>{err}</div>;
  if (!data) return <div className="p-8 text-center"><Loader2 className="animate-spin inline" size={24}/></div>;

  const {
    company, bill_to, property_address, header, line_items, totals,
    notes, title, decision, accepted_at, declined_at, sent_at, sent_via,
    as_customer, customer_view, status,
  } = data;

  // Feb-2026 · Phase A — actionable window (customer can approve /
  // decline whole doc + decline/undecline individual lines) is
  // ``status ∈ {sent, viewed}``. Once decision is set (accepted or
  // declined) the doc is locked as before.
  const _statusLc = String(status || "").toLowerCase();
  const actionable = _statusLc === "sent" || _statusLc === "viewed";

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

  const locked = decision === "accepted" || decision === "declined";

  // Phase K79 · Feb-2026 — Grouped customer-facing view fork.
  // The customer/portal caller renders the grouped rollup rows when
  // ``customer_group_display`` is on. Admin/printable views keep the
  // fully-itemized surface unchanged.
  //
  // Feb-2026 · Batch #4 · Item 1 fix — on the magic-link surface
  // (``token`` present) the grouped rollup HIDES the per-line
  // decline buttons because it collapses individual ``line_items``
  // into category-level rows. Phase A's whole point is customer
  // per-line action, so force itemized rendering whenever the doc
  // is actionable via a magic link. Once the doc is locked
  // (accepted/declined) we fall back to the grouped rollup so the
  // customer's post-decision view stays consistent with the rest
  // of the portal.
  const showGrouped = Boolean(
    as_customer
    && customer_view
    && customer_view.customer_group_display
    && !(token && actionable && !locked),
  );
  const showAdminToolbar = isAdmin && !printable;
  const showCustomerToolbar = !isAdmin && !printable;

  return (
    <div className={`ev-shell iv-shell ${printable ? "iv-printable" : ""}`} data-testid="estimate-view">
      {/* ── Toolbar ─────────────────────────────────────────── */}
      {!printable ? (
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
                disabled={busy}
                data-testid="estimate-toolbar-customer-approve"
                data-legacy-testid="estimate-toolbar-accept-btn"
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

      {sent_at && !printable ? (
        <div className="ev-banner" data-testid="estimate-status-banner">
          Estimate #{header.estimate_number} was sent to customer by {sent_via || "email"}
        </div>
      ) : null}

      {/* ── Body ────────────────────────────────────────────── */}
      <div className="iv-doc ev-doc">
        <div className="iv-header ev-header" data-testid="estimate-header">
          <div className="iv-header-left">
            {/* Phase 34 · Feb 2026 — brand logo header. Falls back to
                the shared /logo-full.png bundled with the frontend so
                every estimate preview matches PDFs, invoices + emails.
                Feb-2026 · Batch #4 · Logo ship — routed through
                ``getTenantLogoUrl`` so per-tenant overrides work
                without touching this JSX. ``doc-header-logo`` is the
                cross-surface testid (invoice / quote / estimate). */}
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
          </div>
          <div className="ev-title" data-testid="estimate-title">Estimate</div>
          <div className="ev-header-details">
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
        </div>

        <div className="iv-divider"/>

        <div className="iv-bill-to">
          <div className="iv-bill-name">{bill_to.name || "—"}</div>
          {bill_to.address ? <div>{bill_to.address}</div> : null}
        </div>

        {title ? <div className="ev-est-title">{title}</div> : null}
        {property_address ? (
          <div className="iv-prop-addr">
            <b>Property Address:</b> {property_address}
          </div>
        ) : null}

        <div className="iv-lines-wrap ev-lines-wrap">
          {showGrouped ? (
            <table className="iv-lines"
                    data-testid="estimate-grouped-lines-table">
              <thead>
                <tr>
                  <th>Service</th>
                  <th className="iv-num">Subtotal</th>
                </tr>
              </thead>
              <tbody>
                {(customer_view.groups || []).length === 0 ? (
                  <tr><td colSpan={2} className="iv-empty">
                    No services on this estimate.
                  </td></tr>
                ) : (customer_view.groups || []).map((g, i) => (
                  <tr key={g.category_id || `other-${i}`}
                      data-testid={
                        `estimate-grouped-row-${g.category_id || "other"}`
                      }>
                    <td>
                      <div><b>{g.label}</b></div>
                      {g.description ? (
                        <div className="ev-group-desc"
                              data-testid={
                                `estimate-grouped-desc-${g.category_id || "other"}`
                              }>
                          {g.description}
                        </div>
                      ) : null}
                    </td>
                    <td className="iv-num">{fmt(g.subtotal)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
          <table className="iv-lines" data-testid="estimate-line-items-table">
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
                  <td className="iv-num" style={rowStyle}>{li.qty_hr || li.quantity || 0}</td>
                  <td className="iv-num" style={rowStyle}>{li.visits || 1}</td>
                  {!as_customer ? <td className="iv-num" style={rowStyle}>{fmt(li.m_rate)}</td> : null}
                  {!as_customer ? <td className="iv-num" style={rowStyle}>{fmt(li.bh)}</td> : null}
                  {!as_customer ? <td className="iv-num" style={rowStyle}>{fmt(li.t_bh)}</td> : null}
                  {!as_customer ? <td className="iv-num" style={rowStyle}>{fmt(li.t_b_cost)}</td> : null}
                  {!as_customer ? <td className="iv-num" style={rowStyle}>{fmt(li.margin_pct)}</td> : null}
                  <td className="iv-num" style={rowStyle}>{fmt(li.total)}</td>
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
          )}
        </div>

        {notes ? (
          <div className="iv-notes ev-notes" data-testid="estimate-notes">
            <div className="iv-notes-body">{notes}</div>
          </div>
        ) : null}

        <div className="ev-totals-wrap">
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
        </div>

        <div className="ev-disclaimer" data-testid="estimate-disclaimer">
          This estimate is a good faith estimate only and is not a guarantee of final cost.
          It is based on anticipated labor, materials, and conditions known at the time of
          estimating. Unforeseen conditions, hidden issues, design changes, or client-requested
          modifications may result in additional costs beyond this estimate. Any additional
          charges will be documented and communicated for approval as soon as reasonably possible.
        </div>
      </div>

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
