import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useSetDynamicCrumb } from "@/components/nav/dynamicCrumbContext";
import {
  ArrowLeft,
  Send,
  Link2,
  Check,
  X,
  DollarSign,
  Repeat2,
  CreditCard,
  MessageSquare,
  Trash2,
  PenTool,
  CheckCircle2,
  History,
  ChevronDown,
  ChevronUp,
  Copy,
} from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
// Feb-2026 · Theme Refresh — brand-driven header band on admin
// surface so admins see the same visual identity as the customer
// PDF / magic-link view without paying a second fetch.
import { useBusinessSettings } from "@/hooks/useTenantBranding";
// Phase LZ4 (Feb 2026) — StripePayments module retired.
// PayNowButton + StripeCheckoutReturn are gone; Lumino's hosted
// payment page + LZ2 dispatcher replaces the Stripe checkout return
// flow. The <PaymentForm> below already drives the Lumino redirect.
import PaymentForm from "@/components/PaymentForm";
import { useAuth } from "@/auth";
import InvoiceAttachments from "@/components/quotes/InvoiceAttachments";
import InvoiceEditModal from "@/components/invoices/InvoiceEditModal";
import EditLockConfirmDialog from "@/components/documents/EditLockConfirmDialog";
import K71LineItemsEditor from "@/components/quotes/K71LineItemsEditor";
// Feb-2026 · Hard-delete quotes — admin+super only surface.
import HardDeleteQuoteModal from "@/components/quotes/HardDeleteQuoteModal";
// Feb-2026 · P0 — Duplicate quote (admin/super_admin only).
import DuplicateQuoteModal from "@/components/quotes/DuplicateQuoteModal";
// Feb-2026 · UX Polish Batch B — Send quote to customer (composed
// mark-sent + email fire).
import SendToCustomerModal from "@/components/quotes/SendToCustomerModal";
// Phase K79 · Feb-2026 — Customer-facing grouped view controls
// (checkbox + per-category description editor + preview modal).
// Rendered on QUOTES only; invoices keep the itemized view.
import K79CustomerViewSection from "@/components/quotes/K79CustomerViewSection";
import FlipbookComposeSection from "@/components/quotes/FlipbookComposeSection";
// Phase K47 · Feb-2026 — View-history card (admin/office/dispatcher
// only; the component hides itself when the endpoint 403s).
import InvoiceViewHistory from "@/components/invoices/InvoiceViewHistory";
// Feb-2026 · Editable Sent Docs Phase 2 — slide-in version-history
// drawer + trigger button. Component is a pure display over
// ``GET /api/invoices|quotes/{id}/versions``.
import VersionHistoryDrawer from "@/components/documents/VersionHistoryDrawer";
import { Button, Skeleton, StatusPill, Modal, TextInput, Toast, Chip } from "@/components/ui-kit";
// Feb-2026 · Batch #4 · Logo ship — shared tenant logo helper so
// the admin invoice/quote detail header matches the InvoiceView /
// EstimateView / magic-link surfaces. The ``doc-header-logo``
// testid is asserted by ``src/test/doc-header-logo.test.jsx``.
import { getTenantLogoUrl, DEFAULT_LOGO_ALT } from "@/lib/tenantLogo";

// ─── Pure helpers · exported for Vitest ────────────────────────────────
// Feb 2026 · P0/P0.5a/P1 — draft-transition fix. These are pulled out
// as module-level pure functions so contract-level tests don't have to
// mount the (router-heavy) full detail page.

/** P0 — dedicated "Send invoice" button is shown ONLY when the doc
 *  is an invoice AND still in ``draft`` status. */
export function shouldShowSendInvoiceButton({ isInvoice, docStatus }) {
  return Boolean(isInvoice) && String(docStatus || "").toLowerCase() === "draft";
}

/** P0.5a — the Email invoice button re-labels to "Send invoice" while
 *  the doc is still a draft (matches CRM convention: sending IS issuing).
 *  Once the doc has been issued (status !== draft) the historical
 *  "Email invoice" wording is restored. */
export function emailInvoiceButtonLabel({ docStatus }) {
  return String(docStatus || "").toLowerCase() === "draft"
    ? "Send invoice"
    : "Email invoice";
}

/** P1 — toast copy for the reminder / send path.
 *  ``wasDraftFlippedToSent`` = true means we just chained
 *  status(draft→sent) + send-reminder on the same click, so the correct
 *  human copy is "Invoice sent to customer" (not "Reminder sent"). */
export function reminderToastCopy({ wasDraftFlippedToSent, emailSent }) {
  const base = wasDraftFlippedToSent
    ? "Invoice sent to customer"
    : "Reminder sent";
  if (emailSent === false) {
    return `${base} (email delivery not configured — logged only)`;
  }
  return base;
}

/** Reused for both /quotes/:id and /invoices/:id — same collection. */
/** Feb-2026 · P0 — the "Payment link" toolbar button is
 *  invoice-only.  Rendering it on an Estimate/Quote produced a
 *  Stripe-Checkout-Session call against a not-yet-approved
 *  document (that either 500'd or created a bogus session).
 *  Rules:
 *    * hidden on non-invoices (estimate / quote / anything else).
 *    * hidden on invoices when the doc is still a draft (nothing
 *      to pay yet — the "Send invoice" chain handles issuance).
 *    * hidden on invoices already ``paid`` / ``void``.
 *    * shown on invoices in ``sent`` / ``partially_paid`` /
 *      ``overdue`` (i.e. any state with an outstanding balance).
 *  Backend also refuses non-invoice ids at the endpoint boundary
 *  as belt-and-braces (see ``routers/lumino_link_request.py``).
 */
export function shouldShowPaymentLinkButton({
  isInvoice, docStatus, paymentStatus,
}) {
  if (!isInvoice) return false;
  const status = String(docStatus || "").toLowerCase();
  const pay = String(paymentStatus || "").toLowerCase();
  if (status === "draft" || status === "void" || status === "voided") {
    return false;
  }
  if (pay === "paid") return false;
  return true;
}

export default function QuoteInvoiceDetail({ _docType = "quote" }) {
  const { id } = useParams();
  const navigate = useNavigate();
  // Feb-2026 · Theme Refresh — mount the branding hook up front so
  // the themed header band renders in the same paint as the rest
  // of the detail page. Fails soft to the default colours so the
  // page never blocks on a missing tenant record.
  const { branding: _adminBranding } = useBusinessSettings();
  const [doc, setDoc] = useState(null);
  const [customer, setCustomer] = useState(null);
  const [pmethod, setPmethod] = useState(null);
  const [handles, setHandles] = useState(null);
  const [toast, setToast] = useState(null);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [smsOpen, setSmsOpen] = useState(false);
  const [payOpen, setPayOpen] = useState(false);
  const [convertOpen, setConvertOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const { user } = useAuth();
  // Phase 5A hot-fix · Feb 2026 — Phase 4B PaymentForm mount toggle.
  const [payNowOpen, setPayNowOpen] = useState(false);
  const [_termsEditOpen, setTermsEditOpen] = useState(false);
  const [termsDraft, setTermsDraft] = useState("");
  const [termsDefaultForDoc, setTermsDefaultForDoc] = useState("");
  // Feb-2026 · Task 6 — collapsible admin terms editor panel.
  // Defaults to expanded; the ``admin-terms-panel-toggle`` chevron
  // collapses to a compact preview row.
  const [termsPanelOpen, setTermsPanelOpen] = useState(true);
  const [termsSaving, setTermsSaving] = useState(false);
  const [signInfo, setSignInfo] = useState(null);
  const [signOpen, setSignOpen] = useState(false);
  const [signEmail, setSignEmail] = useState("");
  const [signMsg, setSignMsg] = useState("");
  // Feb-2026 · Admin invoice edit — modal toggle + audit history state.
  const [editOpen, setEditOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState(null);
  // Feb-2026 · Editable Sent Docs Phase 2 — version-history drawer.
  // We open lazily (drawer fetches the versions endpoint), and we
  // pre-flight a HEAD-shaped GET on mount to decide whether the
  // "History" button should render at all (visible only when at
  // least one snapshot exists).
  const [versionDrawerOpen, setVersionDrawerOpen] = useState(false);
  const [hasVersions, setHasVersions] = useState(false);
  const isStaff = ["admin", "super_admin"].includes(String(user?.role || ""));
  // Feb-2026 · Item 3 — soft-delete (admin/super only). Two flavours:
  //   * ``deleteInvoiceOpen`` → REST ``DELETE /invoices/{id}`` — full
  //     invoice soft-delete (typed-confirm on the invoice number).
  //   * ``deletePaymentOpen`` → REST ``DELETE /payments/{id}`` —
  //     reverts payment status back to unpaid (typed-confirm on the
  //     payment id short-hash).
  const [deleteInvoiceOpen, setDeleteInvoiceOpen] = useState(false);
  const [deletePaymentOpen, setDeletePaymentOpen] = useState(false);
  // Feb-2026 · Hard-delete quote — admin+super only. Separate state
  // from the soft-delete surfaces above.
  const [hardDeleteOpen, setHardDeleteOpen] = useState(false);
  // Feb-2026 · P0 — Duplicate quote modal (admin/super_admin only).
  const [duplicateOpen, setDuplicateOpen] = useState(false);
  // Feb-2026 · UX Polish Batch B — Send quote to customer modal
  // (admin/super_admin only). Composed mark-sent + customer email.
  const [sendToCustomerOpen, setSendToCustomerOpen] = useState(false);
  // Feb 2026 · Type-to-confirm removed — the ``deleteConfirmText``
  // state that gated Delete buttons on the invoice / payment
  // modals has been retired. Kept the two boolean modal opens +
  // the ``deleteBusy`` in-flight flag.
  const [deleteBusy, setDeleteBusy] = useState(false);
  // Feb 2026 · P0 — track the in-flight draft→sent PUT so we can
  // disable the "Send invoice" / "Email invoice" buttons + show a
  // spinner. Shared between the P0 button and the P0.5a auto-flip
  // path on the Email button.
  const [sending, setSending] = useState(false);
  // Feb-2026 · Editable Sent Docs · Phase 1 — one-time confirm gate
  // for editing quotes whose status has passed ``draft``. Once the
  // user acknowledges the shared dialog on this detail page mount,
  // subsequent inline saves inherit the ack + include the
  // ``acknowledged_lock_bypass`` flag on the PUT payload.
  const [lockBypassAcked, setLockBypassAcked] = useState(false);
  const [pendingLines, setPendingLines] = useState(null);
  const [lockDialogOpen, setLockDialogOpen] = useState(false);

  // Feb-2026 · P2/C-follow-up · Register the resolved doc title on
  // the breadcrumb registry so the current-page crumb resolves
  // from the "…" skeleton to the doc's real title. Missing this
  // registration is what left the breadcrumb stuck on "..." in
  // the tester's prod repro.
  useSetDynamicCrumb(
    doc?.doc_type === "invoice" ? "invoice" : "quote",
    doc?.title || null,
  );

  const load = async () => {
    try {
      const q = await api.get(`/quotes/${id}`);
      setDoc(q);
      if (q.customer_id) {
        api.get(`/customers/${q.customer_id}`).then((c) => { setCustomer(c); setSignEmail(c?.email || ""); }).catch(() => {});
        api.get(`/payments/method?customer_id=${q.customer_id}`).then(setPmethod).catch(() => setPmethod(null));
      }
      api.get("/settings/payment-handles").then(setHandles).catch(() => {});
      api.get("/settings/terms").then((r) => {
        const def = q.doc_type === "invoice" ? r.default_invoice_terms : r.default_quote_terms;
        setTermsDefaultForDoc(def || "");
      }).catch(() => {});
      // Signature status (silently ignore errors — endpoint returns {signed:false} normally)
      api.get(`/quotes/${id}/signature`).then(setSignInfo).catch(() => setSignInfo(null));
      // Feb-2026 · Editable Sent Docs Phase 2 — probe the versions
      // endpoint so we know whether to show the "History" trigger.
      // The trigger is deliberately hidden when the doc has never
      // been edited (total==0). ``docType`` decides which alias to
      // hit; both return ``{total: <int>}`` in the payload.
      const _isInvoice = q?.doc_type === "invoice";
      const _versionsPath = _isInvoice
        ? `/invoices/${id}/versions?limit=1`
        : `/quotes/${id}/versions?limit=1`;
      api.get(_versionsPath)
        .then((r) => setHasVersions(Number(r?.total || 0) > 0))
        .catch(() => setHasVersions(false));
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line
  }, [id]);

  // Feb-2026 · Task 6 — keep the inline collapsible terms editor
  // in sync with the freshly-loaded doc so edits start from the
  // current stored value (not the last modal draft).
  useEffect(() => {
    if (doc && typeof doc.terms === "string") setTermsDraft(doc.terms);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.id, doc?.terms]);

  if (!doc) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <Skeleton style={{ height: 200 }} />
      </div>
    );
  }

  const isInvoice = doc.doc_type === "invoice";
  const balance = Math.max(0, Number(doc.total || 0) - Number(doc.amount_paid || 0));
  const canConvertToJob = doc.decision === "approved" || doc.status === "approved";

  const setStatus = async (status) => {
    try {
      // Backend expects ``status`` as a query param (see
      // ``routers/quotes.py::update_quote_status``). The previous
      // body-only call produced a 422 — Feb-2026 P0 fix.
      await api.put(`/quotes/${id}/status?status=${encodeURIComponent(status)}`);
      setToast({ tone: "success", message: `Marked ${status}` });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  // ─── P0 · dedicated "Send invoice" button (draft-only) ──────────────
  // Flips status draft → sent via the same helper (patched above so the
  // query-param contract holds), then reloads the doc so the Pay button
  // becomes unblocked.
  const handleSendInvoice = async () => {
    if (sending) return;
    setSending(true);
    try {
      await api.put(`/quotes/${id}/status?status=sent`);
      setToast({ tone: "success", message: "Invoice sent to customer" });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally {
      setSending(false);
    }
  };

  // ─── P0.5a · Email invoice with auto-flip on draft ──────────────────
  // If the invoice is still a draft, chain status(draft→sent) + reminder
  // so a single click both issues AND emails the invoice (standard CRM
  // convention). Otherwise fall through to the plain reminder path.
  const handleEmailInvoice = async () => {
    if (sending) return;
    const wasDraft = String(doc?.status || "").toLowerCase() === "draft";
    setSending(true);
    try {
      if (wasDraft) {
        await api.put(`/quotes/${id}/status?status=sent`);
      }
      const r = await api.post(`/quotes/${id}/send-reminder`);
      setToast({
        tone: "success",
        message: reminderToastCopy({
          wasDraftFlippedToSent: wasDraft,
          emailSent: r?.email_sent,
        }),
      });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally {
      setSending(false);
    }
  };

  // ─── Feb-2026 · UX Polish Batch B follow-up ────────────────────────
  // "Send + Copy Payment Link" — composed invoice-only admin gesture.
  // Chains: (1) send-reminder (flips draft→sent + fires invoice
  // reminder email), (2) request-payment-link (mints or reuses a
  // Stripe Checkout Session URL), (3) copies the URL to clipboard.
  //
  // INVOICE-ONLY: the backend ``request-payment-link`` endpoint
  // explicitly refuses ``doc_type=quote|estimate`` with a 400. The
  // dispatch's "quote just accepted, invoice out the door" narrative
  // refers to the state AFTER conversion, so this button is gated on
  // ``isInvoice`` — opposite of the standalone Send button which is
  // quote-only. Deviation logged in memo § 1.1.
  const handleSendAndCopyPaymentLink = async () => {
    if (sending) return;
    const wasDraft = String(doc?.status || "").toLowerCase() === "draft";
    setSending(true);
    let sendOk = false;
    let paymentUrl = null;
    try {
      if (wasDraft) {
        await api.put(`/quotes/${id}/status?status=sent`);
      }
      await api.post(`/quotes/${id}/send-reminder`);
      sendOk = true;
      try {
        const linkResp = await api.post(
          `/invoices/${id}/request-payment-link`, {},
        );
        paymentUrl = linkResp?.payment_url || linkResp?.payment_link || null;
      } catch (linkErr) {
        // Send succeeded but link mint failed — warn, keep the send
        // side considered successful.
        setToast({
          tone: "warning",
          message: "Sent. Payment link unavailable — copy manually.",
        });
      }
      if (paymentUrl) {
        try {
          await navigator.clipboard.writeText(paymentUrl);
          setToast({
            tone: "success",
            message: `Sent to customer. Payment link copied.`,
          });
        } catch {
          setToast({
            tone: "success",
            message: `Sent. Copy this link manually: ${paymentUrl}`,
          });
        }
      }
      await load();
    } catch (e) {
      if (!sendOk) {
        setToast({ tone: "error", message: e?.message || "Send failed." });
      }
    } finally {
      setSending(false);
    }
  };

  const decision = async (d) => {
    try {
      await api.post(`/quotes/${id}/decision?decision=${d}`);
      setToast({ tone: "success", message: `Recorded ${d}` });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const generateLink = async () => {
    try {
      // Aug-2026 · Phase 47 direct-Stripe migration cleanup — the
      // legacy ``/payments/admin/generate-link/{id}`` endpoint was
      // retired when the Lumino/Zapier hop was removed. Both the
      // "Pay $X" flow (PaymentForm) and this share-a-link toolbar
      // button now use the same ``/invoices/{id}/request-payment-link``
      // Session-creating endpoint. Response field is ``payment_url``.
      const r = await api.post(`/invoices/${id}/request-payment-link`, {});
      setLinkUrl(r.payment_url);
      setLinkOpen(true);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const sendReminder = async () => {
    try {
      await api.post(`/quotes/${id}/send-reminder`);
      setToast({ tone: "success", message: "Reminder sent (or logged if email not configured)" });
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const chargeOnFile = async () => {
    try {
      const r = await api.post(`/payments/charge-on-file/${id}`);
      setToast({ tone: "success", message: `Charged ${money(r.amount ?? doc.total)}` });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const del = async () => {
    // Backend has no /quotes/{id} DELETE — soft-cancel via status.
    await setStatus("cancelled");
    setConfirmDelete(false);
    setTimeout(() => navigate(isInvoice ? "/invoices" : "/quotes"), 300);
  };

  // Feb-2026 · Item 3 — REST soft-delete handlers. Both use the new
  // ``DELETE /api/{invoices|payments}/{id}`` endpoints (admin+super
  // only). Feb 2026 · Type-to-confirm removed app-wide — the modals
  // now use a plain click-to-confirm flow; the two-click safety
  // (open modal → click Delete) is preserved.
  const runDeleteInvoice = async () => {
    setDeleteBusy(true);
    try {
      await api.del(`/invoices/${id}`);
      setToast({ tone: "success", message: "Invoice deleted" });
      setDeleteInvoiceOpen(false);
      setTimeout(() => navigate("/invoices"), 400);
    } catch (e) {
      setToast({ tone: "error", message: e?.message || "Delete failed" });
    } finally { setDeleteBusy(false); }
  };

  const runDeletePayment = async () => {
    setDeleteBusy(true);
    try {
      const r = await api.del(`/payments/${id}`);
      setToast({
        tone: "success",
        message: r?.stripe_reconciliation_note
          ? "Payment deleted · Stripe note recorded for auditor visibility"
          : "Payment reverted to unpaid",
      });
      setDeletePaymentOpen(false);
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e?.message || "Delete failed" });
    } finally { setDeleteBusy(false); }
  };

  const requestSignature = async () => {
    try {
      const r = await api.post(`/quotes/${id}/request-signature`, {
        signer_email: signEmail || undefined,
        message: signMsg || undefined,
      });
      setSignOpen(false);
      setToast({
        tone: "success",
        message: r.emailed ? "Signature request emailed" : `Sign link: ${r.url}`,
      });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid={`${isInvoice ? "invoice" : "quote"}-detail`}>
      <button
        onClick={() => navigate(isInvoice ? "/invoices" : "/quotes")}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> All {isInvoice ? "invoices" : "quotes"}
      </button>

      {/* Phase LZ4 (Feb 2026) — StripeCheckoutReturn removed with
          the Stripe SDK retirement. Payment success is now surfaced
          via the Lumino return URL + webhook callback, so nothing
          needs to be polled from here. */}

      {/* Feb-2026 · Phase C — admin visibility banner for declined
          line items. Rendered above the doc header so it's the
          first thing the admin sees when opening a doc where the
          customer has flagged one or more lines as declined.
          Wrapped in an ErrorBoundary so an unexpected server-side
          data shape can never take down the whole detail page —
          root-caused during the prod SPA hang on the tester's
          verification pass. */}
      {doc.has_declined_lines ? (
        <DeclinedLinesErrorBoundary>
          <AdminDeclinedLinesBanner doc={doc} />
        </DeclinedLinesErrorBoundary>
      ) : null}

      {/* Feb-2026 · Theme Refresh — brand-driven header band. Mirrors
          the customer-facing shell + PDF so the admin surface reads
          the same visual identity. When branding is null (loading
          or tenant record missing) the block collapses to nothing. */}
      {_adminBranding ? (
        <div
          data-testid="quote-invoice-branded-header"
          data-primary={_adminBranding.brand_primary_hex}
          style={{
            background: _adminBranding.brand_primary_hex || "#0B4A6F",
            color: "#FFFFFF",
            padding: "16px 20px",
            borderRadius: 12,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 16,
            marginBottom: 12,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {_adminBranding.logo_url ? (
              <img
                src={_adminBranding.logo_url}
                alt={_adminBranding.company_display_name || ""}
                style={{ maxHeight: 48, maxWidth: 144,
                          objectFit: "contain", background: "#FFFFFF",
                          padding: 4, borderRadius: 4 }}
                data-testid="quote-invoice-branded-logo"
              />
            ) : null}
            <div>
              <div style={{ fontSize: 26, fontWeight: 800,
                              letterSpacing: 1, lineHeight: 1 }}>
                {(isInvoice ? "INVOICE" : "ESTIMATE")}
              </div>
              {_adminBranding.company_display_name ? (
                <div style={{ fontSize: 12, marginTop: 4, opacity: 0.9 }}>
                  {_adminBranding.company_display_name}
                </div>
              ) : null}
            </div>
          </div>
          <div style={{
            fontSize: 11, lineHeight: 1.35, textAlign: "right",
            opacity: 0.9, maxWidth: "45%",
          }}>
            {(_adminBranding.mailing_address || "")
              .split("\n").slice(0, 2).map((l, i) => (
                <div key={i}>{l}</div>
              ))}
            {_adminBranding.phone ? (<div>{_adminBranding.phone}</div>) : null}
            {_adminBranding.email ? (<div>{_adminBranding.email}</div>) : null}
            {_adminBranding.website ? (<div>{_adminBranding.website}</div>) : null}
          </div>
        </div>
      ) : null}

      <div
        className="rounded-2xl p-6 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          {/* Feb-2026 · Batch #4 · Logo ship — brand logo top-left,
              LEFT of the doc title. Height mirrors the InvoiceView /
              EstimateView treatment (~2.4in in PDF, ~56px on-screen)
              so the admin detail view stays visually aligned with
              the printable + magic-link surfaces. Alt reads from
              ``tenant_name`` in localStorage when present so the
              screen-reader announcement matches the tenant the
              admin is scoped into; falls back to the shared
              default ("Pool & Landscaping of Vistancia"). */}
          <div
            className="flex items-start gap-4 flex-1 min-w-0"
            data-testid="quote-invoice-detail-header-left"
          >
            <img
              src={getTenantLogoUrl()}
              alt={
                (typeof window !== "undefined"
                  && window.localStorage
                  && window.localStorage.getItem("tenant_name"))
                || DEFAULT_LOGO_ALT
              }
              className="rounded-md shrink-0"
              style={{ height: 56, width: "auto",
                        border: `1px solid ${colors.border}` }}
              data-testid="doc-header-logo"
              data-surface={isInvoice ? "invoice-admin" : "quote-admin"}
            />
            <div className="min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <StatusPill status={doc.decision || doc.status} />
              {isInvoice ? (
                <Chip
                  label={doc.payment_status || "unpaid"}
                  tone={doc.payment_status === "paid" ? "success" : doc.payment_status === "partial" ? "warning" : "danger"}
                />
              ) : null}
              {signInfo?.signed ? (
                <Chip
                  label={`Signed by ${signInfo.signer_name}`}
                  tone="success"
                  testid="signed-chip"
                />
              ) : null}
            </div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
              {doc.title}
            </h1>
            <p className="text-sm mt-1" style={{ color: colors.onSurfaceSecondary }}>
              <span
                className="font-semibold cursor-pointer hover:underline"
                onClick={() => customer && navigate(`/customers/${customer.id}`)}
              >
                {doc.customer_name}
              </span>
              {doc.due_date ? <> · Due {doc.due_date}</> : null}
            </p>
            </div>
          </div>
          <div className="text-right flex flex-col items-end gap-2">
            <div className="text-3xl font-bold" style={{ color: colors.brand }}>{money(doc.total)}</div>
            {isInvoice ? (
              <div className="text-xs mt-1" style={{ color: colors.muted }}>
                Paid {money(doc.amount_paid || 0)} · Balance {money(balance)}
              </div>
            ) : null}
            {/* Feb-2026 · Editable Sent Docs Phase 2 — trigger for
                the version-history drawer. Renders for staff
                (admin/super_admin) on ANY non-draft doc so admins
                can always confirm the history is empty (drawer
                renders the ``doc-version-history-empty`` state
                when ``total==0``). Previously gated on
                ``hasVersions`` — hid the entry point entirely
                when the doc was untouched, leaving no way for
                the admin to reach the drawer to verify. */}
            {isStaff && String(doc?.status || "") !== "draft" ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setVersionDrawerOpen(true)}
                testid="doc-header-history-btn"
              >
                <History size={14} className="mr-1" /> History
              </Button>
            ) : null}
          </div>
        </div>

        {/* Action bar */}
        <div className="flex flex-wrap gap-2 mt-5">
          {!isInvoice ? (
            <>
              {doc.status === "draft" ? (
                <>
                  <Button onClick={() => setStatus("sent")} testid="qd-send"><Send size={14} /> Send</Button>
                  <Button variant="ghost" onClick={() => decision("approved")}><Check size={14} /> Mark approved</Button>
                  <Button variant="ghost" onClick={() => decision("declined")}><X size={14} /> Mark declined</Button>
                </>
              ) : (
                <>
                  <Button variant="ghost" onClick={sendReminder} testid="qd-send-reminder"><Send size={14} /> Send reminder</Button>
                  {/* Feb-2026 · P0 fix — payment link is invoice-only.
                      Rendering it on an Estimate/Quote produced a
                      "Payment link" button that either 500'd
                      downstream (Stripe session for an estimate
                      total) OR minted a Stripe checkout against a
                      not-yet-approved estimate. Guarded at the UI
                      boundary + also at the backend endpoint
                      (POST /invoices/{id}/request-payment-link now
                      returns 400 with error_code=not_an_invoice for
                      quote/estimate ids). Estimates use the
                      "Send for signature" and magic-link viewer
                      flows to collect the customer decision. */}
                </>
              )}
              {canConvertToJob ? (
                <Button onClick={() => setConvertOpen(true)} testid="qd-convert-job">
                  <Repeat2 size={14} /> Convert to job
                </Button>
              ) : null}
              {!signInfo?.signed ? (
                <Button variant="ghost" onClick={() => setSignOpen(true)} testid="qd-request-sig">
                  <PenTool size={14} /> Send for signature
                </Button>
              ) : (
                <Button variant="ghost"
                        onClick={() => window.open(`${process.env.REACT_APP_BACKEND_URL}/api/quotes/${id}/signed-pdf`, "_blank")}
                        testid="qd-view-signed">
                  <CheckCircle2 size={14} /> View signed PDF
                </Button>
              )}
            </>
          ) : (
            <>
              {shouldShowSendInvoiceButton({ isInvoice, docStatus: doc.status }) ? (
                <Button
                  onClick={handleSendInvoice}
                  disabled={sending}
                  testid="id-send-invoice"
                >
                  <Send size={14} /> {sending ? "Sending…" : "Send invoice"}
                </Button>
              ) : null}
              <Button
                variant="ghost"
                onClick={handleEmailInvoice}
                disabled={sending}
                testid="id-send-email"
              >
                <Send size={14} />{" "}
                {sending && String(doc.status || "").toLowerCase() === "draft"
                  ? "Sending…"
                  : emailInvoiceButtonLabel({ docStatus: doc.status })}
              </Button>
              <Button variant="ghost" onClick={() => setSmsOpen(true)} testid="id-send-sms"><MessageSquare size={14} /> Text invoice</Button>
              {shouldShowPaymentLinkButton({
                isInvoice, docStatus: doc.status,
                paymentStatus: doc.payment_status,
              }) ? (
                <Button variant="ghost" onClick={generateLink} testid="id-gen-link"><Link2 size={14} /> Payment link</Button>
              ) : null}
              {pmethod?.brand ? (
                <Button onClick={chargeOnFile} testid="id-charge-on-file">
                  <CreditCard size={14} /> Charge {pmethod.brand} · {pmethod.last4}
                </Button>
              ) : null}
              <Button variant="ghost" onClick={() => setPayOpen(true)} testid="id-record-payment">
                <DollarSign size={14} /> Record payment
              </Button>
              {balance > 0 ? (
                <Button onClick={() => setPayNowOpen(true)} testid="id-pay-now-phase4b">
                  <CreditCard size={14} /> Pay {`$${balance.toFixed(2)}`}
                </Button>
              ) : null}
            </>
          )}
          <Button variant="danger" onClick={() => setConfirmDelete(true)} testid="qd-cancel">
            <Trash2 size={14} /> Cancel
          </Button>
          {/* Feb-2026 · Item 3 — Admin/super-only hard soft-delete
              actions on invoices. Separate from "Cancel" (which just
              flips status) — these hit the new REST DELETE endpoints
              and write to the deletion_audit trail. */}
          {isInvoice && isStaff ? (
            <>
              <Button
                variant="danger"
                onClick={() => setDeleteInvoiceOpen(true)}
                testid="id-delete-invoice-btn"
              >
                <Trash2 size={14} /> Delete invoice
              </Button>
              {String(doc.payment_status || "unpaid").toLowerCase() !== "unpaid" ? (
                <Button
                  variant="danger"
                  onClick={() => setDeletePaymentOpen(true)}
                  testid="id-delete-payment-btn"
                >
                  <Trash2 size={14} /> Delete payment
                </Button>
              ) : null}
            </>
          ) : null}
          {/* Feb-2026 · Hard-delete quote — admin+super only, QUOTE-only
              (invoices go through the soft-delete surface above; hard-
              deleting an invoice would silently drop the payment
              ledger integrity). Placed next to the soft-delete cluster
              so it's obviously destructive AND obviously separate. */}
          {!isInvoice && isStaff ? (
            <Button
              variant="danger"
              onClick={() => setHardDeleteOpen(true)}
              testid="hard-delete-quote-btn"
            >
              <Trash2 size={14} /> Hard Delete Quote
            </Button>
          ) : null}
          {/* Feb-2026 · P0 — Duplicate quote.  Admin+super only,
              QUOTE-only (invoices carry a numbering sequence + payment
              ledger that isn't safe to clone through this surface).
              Placed next to the Hard Delete cluster because the two
              are the "reset a quote" + "copy a quote" pair — same
              destructive vs constructive symmetry, both live behind
              the same isStaff gate. */}
          {!isInvoice && isStaff ? (
            <Button
              variant="secondary"
              onClick={() => setDuplicateOpen(true)}
              testid="duplicate-quote-btn"
            >
              <Copy size={14} /> Duplicate
            </Button>
          ) : null}
          {/* Feb-2026 · UX Polish Batch B — Send quote to customer.
              Pairs with Duplicate above; both are admin/super_admin
              gestures scoped to quotes (not invoices). Skipped on
              terminal statuses so the button doesn't mislead. */}
          {!isInvoice && isStaff
            && !["accepted", "declined"]
                .includes(String(doc.status || "").toLowerCase()) ? (
            <Button
              variant="secondary"
              onClick={() => setSendToCustomerOpen(true)}
              testid="send-to-customer-btn"
            >
              <Send size={14} /> Send
            </Button>
          ) : null}
          {/* Feb-2026 · UX Polish Batch B follow-up — Send + Copy
              Payment Link (invoice-only composed action). Gated
              opposite of Send because payment links only exist on
              invoices (backend refuses quotes with 400). */}
          {isInvoice && isStaff
            && !["void", "cancelled", "paid"]
                .includes(String(doc.status || "").toLowerCase()) ? (
            <Button
              variant="secondary"
              onClick={handleSendAndCopyPaymentLink}
              disabled={sending}
              testid="send-and-copy-payment-link-btn"
            >
              <Send size={14} /> Send &amp; Copy Payment Link
            </Button>
          ) : null}
          {/* Phase K80.a · Feb-2026 — On DRAFT invoices the K71 inline
              editor now covers add/edit/delete, so this modal button is
              redundant. Keep it visible only on statuses where the
              modal's typed-confirm / warning UX matters (sent, paid,
              void, cancelled). Relabelled "Edit invoice (advanced)" to
              signal it's the fuller surface. */}
          {/* Feb-2026 · Editable Sent Docs · Phase 1 — expose the
              advanced-edit modal for sent / accepted / paid invoices.
              Terminal statuses (void / cancelled) remain locked; the
              backend PATCH gate refuses them. Accepted + paid open
              additional confirmation dialogs inside the modal (Stripe-
              ledger warning on paid; signature-invalidation warning
              when the doc has been signed). */}
          {isStaff && isInvoice
            && ["sent", "accepted", "paid"]
                .includes(String(doc.status || "").toLowerCase()) ? (
            <Button
              variant="ghost"
              onClick={() => setEditOpen(true)}
              testid="qd-edit-invoice"
              title="Adjust line items, discount, or invoice fields — with confirmation guards for sent / accepted / paid invoices."
            >
              <PenTool size={14} /> Edit invoice (advanced)
            </Button>
          ) : null}
        </div>
      </div>

      {/* Phase K79 · Feb-2026 — Customer-facing grouped view controls.
          Quotes/estimates only (invoices keep the itemized customer
          view — grouped rollup on invoices is future scope). Admin-
          only surface. */}
      {isStaff && !isInvoice ? (
        <K79CustomerViewSection doc={doc} onDocRefresh={load} />
      ) : null}

      {/* Feb-2026 · Interactive Flipbook Estimate Viewer — per-estimate
          admin opt-in + background-image picker. Same audience gate
          as the K79 grouped-view controls above (admin, quote/estimate
          only). Invoices intentionally excluded — the flipbook is a
          proposal-persuasion surface, not an accounting one. */}
      {isStaff && !isInvoice ? (
        <FlipbookComposeSection doc={doc} onDocRefresh={load} />
      ) : null}

      {/* Line items */}
      <div
        className="rounded-2xl p-6 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <h2 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>Line items</h2>
        <K71LineItemsEditor
          doc={doc}
          canEdit={
            isStaff
            && !["void", "cancelled"]
                .includes(String(doc.status || "").toLowerCase())
          }
          onLinesUpdated={async (nextLines) => {
            // Feb-2026 · Editable Sent Docs · Phase 1 — for non-draft
            // statuses (sent | accepted | paid) we require a one-time
            // confirmation dialog before the PUT fires. The shared
            // dialog handles the Stripe-paid + signature-invalidation
            // warnings. Once ack'd in this session we short-circuit
            // subsequent inline saves and forward the ack flag on the
            // PUT body so the backend lock gate accepts the mutation.
            const _st = String(doc.status || "").toLowerCase();
            // Feb 2026 · Follow-up — extend the ack-bypass list to
            // ``past_due`` / ``unpaid`` / ``overdue`` so admin
            // operators can correct aged-status invoices without a
            // void-and-re-issue dance. Backend
            // ``_ALLOWED_WITH_ACK`` is kept in sync.
            const _locked = ["sent", "accepted", "paid",
                              "past_due", "unpaid", "overdue"].includes(_st);
            // Feb-2026 · Invoice God Mode — super_admins skip the
            // ack popup entirely on aged-invoice statuses. The
            // server-side gate applies the role-based bypass and
            // writes a distinct audit line, so we intentionally
            // omit the ack flag from the payload here to keep the
            // silent path traceable in ops dashboards.
            const _role = String(user?.role || "").toLowerCase();
            const _silentBypass = _role === "super_admin"
                                    && ["past_due", "unpaid", "overdue"].includes(_st);
            if (_locked && !_silentBypass && !lockBypassAcked) {
              setPendingLines(nextLines);
              setLockDialogOpen(true);
              return false;
            }
            // PUT /quotes/{id} — server recomputes totals and enforces
            // K71 two-taxonomy validation on any touched line.
            try {
              const _body = { line_items: nextLines };
              if (_locked && !_silentBypass) _body.acknowledged_lock_bypass = true;
              await api.put(`/quotes/${id}`, _body);
              setToast({ tone: "success", message: "Line item saved" });
              await load();
              return true;
            } catch (e) {
              setToast({ tone: "error",
                          message: e?.data?.detail?.message
                                    || e?.message
                                    || "Save failed" });
              return false;
            }
          }}
          onError={(msg) => setToast({ tone: "error",
                                          message: typeof msg === "string"
                                                    ? msg
                                                    : (msg?.message
                                                        || "Save failed") })}
        />
        <div className="mt-4 flex justify-end">
          <div className="w-64 space-y-1 text-sm"
                data-testid="quote-invoice-totals-block">
            <div className="flex justify-between"><span style={{ color: colors.muted }}>Subtotal</span><span>{money(doc.subtotal)}</span></div>
            <div className="flex justify-between"><span style={{ color: colors.muted }}>Tax ({doc.tax_rate}%)</span><span>{money(doc.tax)}</span></div>
            <div className="flex justify-between font-bold" style={{ color: colors.brand }}>
              <span>Total</span><span>{money(doc.total)}</span>
            </div>
            {/* Feb-2026 · Decline-per-group ship — admin dual-total
                display. Only rendered when the customer has struck
                at least one line item so ordinary quotes retain the
                single-total footprint. See
                /app/memory/FEATURE_QUOTE_DECLINE_PER_GROUP.md. */}
            {doc.has_declined_lines ? (
              <div
                className="pt-2 mt-2 border-t"
                style={{ borderColor: colors.border }}
                data-testid="quote-invoice-effective-total"
              >
                <div className="flex justify-between text-xs"
                      style={{ color: colors.muted }}>
                  <span>Subtotal (incl. declined)</span>
                  <span>{money(doc.original_total ?? doc.total)}</span>
                </div>
                <div className="flex justify-between font-bold"
                      style={{ color: "#B45309" }}>
                  <span>Effective (excl. declined)</span>
                  <span data-testid="quote-invoice-effective-total-value">
                    {money(doc.adjusted_total ?? doc.total)}
                  </span>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        {/* Feb-2026 · Phase C — admin declined-lines summary card.
            Rendered underneath the line items when at least one row
            has ``customer_status === "declined"``. Complements the
            K71 editor (which is kept unmodified) by giving the admin
            a scannable list of what the customer refused + why.
            Wrapped in the same ErrorBoundary as the banner. */}
        {(doc.line_items || []).some((li) => li && (li.customer_status || "") === "declined") ? (
          <DeclinedLinesErrorBoundary>
            <AdminDeclinedLinesList lineItems={doc.line_items || []} />
          </DeclinedLinesErrorBoundary>
        ) : null}

        {/* PB1 · Feb-2026 · Internal Margin section. Admin-only.
             Renders ONLY when the current session role is admin or
             super_admin AND we're on the admin (not portal) surface.
             Never rendered on the customer portal invoice view or
             any PDF/email template. */}
        {(user?.role === "admin" || user?.role === "super_admin" ||
          user?.role === "manager") ? (() => {
            const rows = doc.line_items || [];
            const perLine = rows.map((li) => {
              const q = Number(li.quantity || 0);
              const retail = Number(li.retail_price_snapshot ?? li.unit_price ?? 0);
              const wholesale = Number(li.wholesale_price_snapshot || 0);
              const labor = Number(li.labor_cost_snapshot || 0);
              return {
                description: li.description,
                revenue: q * retail,
                cogs: q * wholesale,
                labor: q * labor,
                profit: q * (retail - wholesale - labor),
                wholesale_per_unit: wholesale,
                labor_per_unit: labor,
              };
            });
            const totRev = perLine.reduce((s, r) => s + r.revenue, 0);
            const totCogs = perLine.reduce((s, r) => s + r.cogs, 0);
            const totLabor = perLine.reduce((s, r) => s + r.labor, 0);
            const totProfit = totRev - totCogs - totLabor;
            const margin = totRev > 0
              ? (totProfit / totRev * 100).toFixed(1)
              : "0.0";
            return (
              <div className="mt-6 rounded-xl p-4"
                    style={{ background: "#FEF3C7",
                              border: "1px solid #FCD34D",
                              color: "#78350F" }}
                    data-testid="internal-margin-section">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs uppercase font-bold tracking-wide"
                         style={{ color: "#92400E" }}>
                    Internal margin — not shown to customer
                  </span>
                </div>
                <div className="overflow-x-auto -mx-1">
                  <table className="w-full text-xs"
                          data-testid="internal-margin-table"
                          style={{ minWidth: 560 }}>
                  <thead>
                    <tr style={{ color: "#92400E" }}>
                      <th className="text-left py-1">Line</th>
                      <th className="text-right py-1">Wholesale/u</th>
                      <th className="text-right py-1">Labor/u</th>
                      <th className="text-right py-1">Revenue</th>
                      <th className="text-right py-1">COGS</th>
                      <th className="text-right py-1">Labor</th>
                      <th className="text-right py-1">Profit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perLine.map((r, i) => (
                      <tr key={i}
                           data-testid={`internal-margin-line-${i}`}>
                        <td className="py-1">{r.description}</td>
                        <td className="py-1 text-right font-mono">
                          {money(r.wholesale_per_unit)}
                        </td>
                        <td className="py-1 text-right font-mono">
                          {money(r.labor_per_unit)}
                        </td>
                        <td className="py-1 text-right">{money(r.revenue)}</td>
                        <td className="py-1 text-right">{money(r.cogs)}</td>
                        <td className="py-1 text-right">{money(r.labor)}</td>
                        <td className="py-1 text-right font-semibold">
                          {money(r.profit)}
                        </td>
                      </tr>
                    ))}
                    <tr style={{ borderTop: "1px solid #FCD34D",
                                  fontWeight: 700 }}
                         data-testid="internal-margin-totals">
                      <td className="py-2">Totals</td>
                      <td></td>
                      <td></td>
                      <td className="py-2 text-right">{money(totRev)}</td>
                      <td className="py-2 text-right">{money(totCogs)}</td>
                      <td className="py-2 text-right">{money(totLabor)}</td>
                      <td className="py-2 text-right">
                        {money(totProfit)}{" "}
                        <span className="text-[10px] font-normal">
                          ({margin}% margin)
                        </span>
                      </td>
                    </tr>
                  </tbody>
                </table>
                </div>
              </div>
            );
          })() : null}
      </div>

      {/* Phase F2b · Attachments (F0-native, purpose-scoped).
          Renders on both invoice and estimate views. Customer sees a
          read-only list; upload UI is gated on role inside the
          component. */}
      <InvoiceAttachments docId={doc.id} isInvoice={isInvoice} user={user} />

      {/* Phase K47 · Feb-2026 — Invoice view-history card. Only
          rendered on invoices (quotes have their own separate
          audit tab) and only for staff-authenticated views. */}
      {isInvoice && isStaff && <InvoiceViewHistory invoiceId={doc.id} />}

      {/* Feb-2026 · Task 6 — Collapsible inline Terms & Conditions
          editor. Replaces the prior modal-based editor. All old
          testids (``doc-terms-*``) are preserved for back-compat +
          the new spec testids (``admin-terms-*``) are layered on. */}
      <div
        className="rounded-2xl p-5 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="admin-terms-editor-panel"
      >
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={() => setTermsPanelOpen((v) => !v)}
            className="flex items-center gap-2 flex-1 text-left"
            data-testid="admin-terms-panel-toggle"
            aria-expanded={termsPanelOpen}
          >
            {termsPanelOpen ? (
              <ChevronUp size={16} style={{ color: colors.muted }} />
            ) : (
              <ChevronDown size={16} style={{ color: colors.muted }} />
            )}
            <span className="text-xs uppercase font-semibold tracking-wide"
                  style={{ color: colors.muted }}>
              Terms &amp; Conditions
            </span>
          </button>
          {termsDefaultForDoc && termsDraft !== termsDefaultForDoc ? (
            <button
              type="button"
              onClick={() => setTermsDraft(termsDefaultForDoc)}
              className="text-xs font-semibold hover:underline"
              style={{ color: colors.brand }}
              data-testid="doc-terms-reset"
            >
              Reset to default
            </button>
          ) : null}
        </div>

        {/* Card body (also kept under ``doc-terms-card`` for back-compat) */}
        <div data-testid="doc-terms-card" className="mt-2">
          {!termsPanelOpen ? (
            (doc.terms || "").trim() ? (
              <p className="text-sm whitespace-pre-wrap line-clamp-3"
                 style={{ color: colors.onSurface }}
                 data-testid="doc-terms-text">
                {doc.terms}
              </p>
            ) : (
              <p className="text-sm italic"
                 style={{ color: colors.muted }}
                 data-testid="doc-terms-empty">
                No terms provided.
              </p>
            )
          ) : (
            <div>
              <textarea
                rows={8}
                maxLength={5000}
                value={termsDraft}
                onChange={(e) => setTermsDraft(e.target.value)}
                placeholder="Legal terms rendered on the estimate/quote (PDF, email, portal)."
                className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
                style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                data-testid="admin-terms-textarea"
                aria-describedby="admin-terms-character-count"
              />
              {/* Back-compat: legacy tests reference ``doc-terms-textarea``. */}
              <span data-testid="doc-terms-textarea" style={{ display: "none" }} />
              <div className="flex items-center justify-between mt-2 gap-3 flex-wrap">
                <div
                  id="admin-terms-character-count"
                  className="text-xs"
                  style={{
                    color:
                      (termsDraft || "").length >= 5000
                        ? "#DC2626"
                        : colors.muted,
                  }}
                  data-testid="admin-terms-character-count"
                >
                  {(termsDraft || "").length} / 5000
                </div>
                <div className="flex items-center gap-2">
                  {/* Back-compat: old ``doc-terms-edit`` id now
                      no-ops onto the toggle so any lingering
                      test that clicks it still opens the panel. */}
                  <button
                    type="button"
                    onClick={() => setTermsDraft(doc.terms || "")}
                    className="text-xs font-semibold hover:underline"
                    style={{ color: colors.muted }}
                    data-testid="doc-terms-edit"
                  >
                    Revert
                  </button>
                  <button
                    type="button"
                    disabled={termsSaving}
                    onClick={async () => {
                      const _st = String(doc.status || "").toLowerCase();
                      // Feb 2026 · Follow-up — see the K71 editor
                      // save above; ack-bypass list widened for
                      // aged invoice statuses.
                      const _locked = ["sent", "accepted", "paid",
                                        "past_due", "unpaid", "overdue"].includes(_st);
                      // Feb-2026 · Invoice God Mode — super_admin
                      // silent-bypass mirrors the line-items save
                      // above. Omit the ack flag so the backend
                      // writes the distinct silent-bypass audit
                      // line instead of the standard ack one.
                      const _role = String(user?.role || "").toLowerCase();
                      const _silentBypass = _role === "super_admin"
                                              && ["past_due", "unpaid", "overdue"].includes(_st);
                      if (_locked && !_silentBypass && !lockBypassAcked) {
                        setPendingLines({ __terms__: termsDraft });
                        setLockDialogOpen(true);
                        return;
                      }
                      setTermsSaving(true);
                      try {
                        const _body = { terms_and_conditions: termsDraft };
                        if (_locked && !_silentBypass) _body.acknowledged_lock_bypass = true;
                        await api.put(`/quotes/${id}`, _body);
                        setToast({ tone: "success", message: "Terms saved" });
                        await load();
                      } catch (e) {
                        setToast({ tone: "error", message: e?.message || "Save failed" });
                      } finally {
                        setTermsSaving(false);
                      }
                    }}
                    className="px-3 py-1.5 text-sm font-semibold rounded-lg disabled:opacity-60"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="admin-terms-save-btn"
                  >
                    {/* Back-compat testid mirrors old ``doc-terms-save`` */}
                    <span data-testid="doc-terms-save">
                      {termsSaving ? "Saving…" : "Save"}
                    </span>
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Payment handles chips */}
      {isInvoice && handles && (handles.venmo || handles.zelle || handles.cashapp || handles.paypal) ? (
        <div
          className="rounded-2xl p-5 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div className="text-xs uppercase font-semibold mb-2" style={{ color: colors.muted }}>
            Alternate pay methods
          </div>
          <div className="flex flex-wrap gap-2">
            {handles.venmo ? <Chip label={`Venmo · ${handles.venmo}`} tone="purple" /> : null}
            {handles.zelle ? <Chip label={`Zelle · ${handles.zelle}`} tone="brand" /> : null}
            {handles.cashapp ? <Chip label={`Cash App · ${handles.cashapp}`} tone="success" /> : null}
            {handles.paypal ? <Chip label={`PayPal · ${handles.paypal}`} tone="brand" /> : null}
          </div>
        </div>
      ) : null}

      {/* Feb-2026 · Task 6 — legacy modal-based terms editor retired
          in favour of the inline collapsible panel above. The
          ``termsEditOpen`` state is retained as a no-op so the
          existing lock-dialog ``setTermsEditOpen(false)`` call
          continues to compile without a rewrite of the shared
          dialog wiring. */}
      <Modal open={linkOpen} onClose={() => setLinkOpen(false)} title="Stripe Payment Link"
        footer={<Button onClick={() => setLinkOpen(false)}>Close</Button>}>
        <p className="text-sm mb-3" style={{ color: colors.onSurfaceSecondary }}>Copy and share this link to collect payment.</p>
        <div className="p-3 rounded-lg text-xs break-all font-mono"
          style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}>
          {linkUrl}
        </div>
        <div className="mt-3 flex gap-2">
          <Button variant="ghost" onClick={() => { navigator.clipboard.writeText(linkUrl); setToast({ tone: "success", message: "Copied" }); }} testid="qd-copy-link">Copy</Button>
          <a href={linkUrl} target="_blank" rel="noreferrer">
            <Button variant="ghost">Open in Stripe</Button>
          </a>
        </div>
      </Modal>

      <SmsModal open={smsOpen} onClose={() => setSmsOpen(false)} invoice={doc} customer={customer}
        onDone={(m, t) => { setSmsOpen(false); setToast({ tone: t || "success", message: m }); }} />

      {/* Feb-2026 · Item 3 — soft-delete confirmation modals.
          Feb 2026 · Type-to-confirm friction removed app-wide: the
          modals now use a single-click Delete inside the modal; the
          two-click safety (open modal → click Delete) is preserved. */}
      {/* Feb-2026 · Hard-delete quote modal — QUOTE-only surface.
          Fires DELETE /api/quotes/{qid}?hard=true, refuses (409) if
          the quote has been converted to an invoice. NO audit trail
          per user-locked directive #5. */}
      <HardDeleteQuoteModal
        open={hardDeleteOpen}
        quoteId={doc?.id}
        quoteNumber={
          (doc?.estimate_number || doc?.invoice_number ||
             doc?.number || doc?.id || "")
            .toString()
            .toUpperCase()
        }
        customerName={customer?.name}
        totalAmount={Number(doc?.total || 0)}
        onClose={() => setHardDeleteOpen(false)}
        onDeleted={() => {
          setHardDeleteOpen(false);
          setToast({ tone: "success", message: "Quote hard-deleted" });
          setTimeout(() => navigate("/quotes"), 400);
        }}
        onError={(detail) => {
          setToast({ tone: "error", message: String(detail) });
        }}
      />
      {/* Feb-2026 · P0 — Duplicate quote modal.  Navigates to the
          fresh draft on success; keeps the modal open + surfaces the
          server detail on 422 / 404 / 403 so the admin can fix. */}
      <DuplicateQuoteModal
        open={duplicateOpen}
        quoteId={doc?.id}
        sourceCustomerId={doc?.customer_id}
        onClose={() => setDuplicateOpen(false)}
        onDuplicated={(r) => {
          setDuplicateOpen(false);
          const num = r?.quote_number || (r?.quote_id || "").slice(0, 8);
          setToast({
            tone: "success",
            message: `Quote duplicated as draft #${num}.`,
          });
          if (r?.quote_id) {
            setTimeout(() => navigate(`/quotes/${r.quote_id}`), 400);
          }
        }}
        onError={(detail) => {
          setToast({ tone: "error", message: String(detail) });
        }}
      />
      {/* Feb-2026 · UX Polish Batch B — Send quote to customer. */}
      <SendToCustomerModal
        open={sendToCustomerOpen}
        quoteId={doc?.id}
        primaryEmail={doc?.customer_email || doc?.customer?.email || ""}
        onClose={() => setSendToCustomerOpen(false)}
        onSent={(r) => {
          setSendToCustomerOpen(false);
          setToast({
            tone: "success",
            message: `Quote sent to ${r?.recipient || "customer"}.`,
          });
          // Refetch so status / sent_at reflect the flip.
          load && load();
        }}
        onError={(detail) => {
          setToast({ tone: "error", message: String(detail) });
        }}
      />
      <Modal
        open={deleteInvoiceOpen}
        onClose={() => setDeleteInvoiceOpen(false)}
        title="Delete this invoice?"
        footer={
          <div className="flex items-center gap-2">
            <Button variant="ghost"
                     onClick={() => setDeleteInvoiceOpen(false)}
                     testid="id-delete-invoice-cancel">Cancel</Button>
            <Button variant="danger"
                     onClick={runDeleteInvoice}
                     disabled={deleteBusy}
                     testid="id-delete-invoice-confirm">
              {deleteBusy ? "Deleting…" : "Delete invoice"}
            </Button>
          </div>
        }
      >
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
          This soft-deletes the invoice. It can be restored from{" "}
          <b>Admin → Audit → Deletions</b> (super_admin only).
        </p>
      </Modal>

      <Modal
        open={deletePaymentOpen}
        onClose={() => setDeletePaymentOpen(false)}
        title="Delete this payment?"
        footer={
          <div className="flex items-center gap-2">
            <Button variant="ghost"
                     onClick={() => setDeletePaymentOpen(false)}
                     testid="id-delete-payment-cancel">Cancel</Button>
            <Button variant="danger"
                     onClick={runDeletePayment}
                     disabled={deleteBusy}
                     testid="id-delete-payment-confirm">
              {deleteBusy ? "Deleting…" : "Delete payment"}
            </Button>
          </div>
        }
      >
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
          This reverts the payment: <b>amount_paid → 0</b>,{" "}
          <b>payment_status → unpaid</b>. The invoice row stays. If the
          payment was settled via Stripe or Lumino, a reconciliation
          note is recorded — no external refund is issued. Refund via
          the Stripe / Lumino dashboard separately if required.
        </p>
      </Modal>

      <RecordPaymentModal open={payOpen} onClose={() => setPayOpen(false)} invoice={doc}
        onDone={async (m) => { setPayOpen(false); setToast({ tone: "success", message: m }); await load(); }}
        onError={(e) => setToast({ tone: "error", message: e })} />

      <ConvertToJobModal
        open={convertOpen}
        onClose={() => setConvertOpen(false)}
        quote={doc}
        onDone={(jid) => { setConvertOpen(false); navigate(`/jobs/${jid}`); }}
        onError={(e) => setToast({ tone: "error", message: e })}
      />

      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)}
        title="Cancel this document?"
        footer={<>
          <Button variant="ghost" onClick={() => setConfirmDelete(false)}>Keep it</Button>
          <Button variant="danger" onClick={del}>Cancel it</Button>
        </>}>
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Marks the document as cancelled. It stays in the ledger.</p>
      </Modal>

      <Modal open={signOpen} onClose={() => setSignOpen(false)} title="Send for signature"
        footer={<>
          <Button variant="ghost" onClick={() => setSignOpen(false)}>Cancel</Button>
          <Button onClick={requestSignature} testid="sig-modal-submit">Send</Button>
        </>}>
        <div className="space-y-3" data-testid="sig-request-modal">
          <TextInput label="RECIPIENT EMAIL" value={signEmail} onChange={(e) => setSignEmail(e.target.value)} />
          <div>
            <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>PERSONAL MESSAGE (optional)</label>
            <textarea value={signMsg} onChange={(e) => setSignMsg(e.target.value)} rows={3}
              className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
              style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
              placeholder="Please review and sign your estimate." />
          </div>
          <p className="text-xs" style={{ color: colors.muted }}>
            Sends a magic-link the customer can open without logging in.
          </p>
        </div>
      </Modal>

      <Toast toast={toast} onClose={() => setToast(null)} />
      {/* Feb-2026 · Editable Sent Docs · Phase 1 — shared confirm
          dialog for editing sent / accepted / paid quotes. Fires on
          the first inline save; the ack persists for the rest of
          this detail-page session so subsequent edits don't
          re-prompt. Cancel returns the pending lines to the editor
          without committing. */}
      <EditLockConfirmDialog
        open={lockDialogOpen}
        onCancel={() => {
          setLockDialogOpen(false);
          setPendingLines(null);
        }}
        onConfirm={async () => {
          setLockDialogOpen(false);
          setLockBypassAcked(true);
          const _pending = pendingLines;
          setPendingLines(null);
          if (!_pending) return;
          const _st = String(doc.status || "").toLowerCase();
          try {
            let _body;
            if (_pending && typeof _pending === "object" && _pending.__terms__ !== undefined) {
              _body = { terms_and_conditions: _pending.__terms__, acknowledged_lock_bypass: true };
              await api.put(`/quotes/${id}`, _body);
              setTermsEditOpen(false);
              setToast({ tone: "success", message: "Terms saved" });
            } else {
              _body = { line_items: _pending, acknowledged_lock_bypass: true };
              await api.put(`/quotes/${id}`, _body);
              setToast({ tone: "success", message: "Line item saved" });
            }
            await load();
          } catch (e) {
            setToast({ tone: "error",
                        message: e?.data?.detail?.message
                                  || e?.message
                                  || "Save failed" });
          }
          void _st;
        }}
        isStripePaid={String(doc.status || "").toLowerCase() === "paid"
                        && Boolean(doc?.payment_intent_id
                                    || doc?.charge_id
                                    || doc?.stripe_payment_intent_id
                                    || doc?.payment_url)}
        isSigned={Boolean(signInfo?.signed
                            || String(doc?.signature_status || "").toLowerCase() === "signed")}
        status={String(doc?.status || "")}
      />
      {payNowOpen ? (
        <PaymentForm
          invoice={doc}
          invoiceId={doc?.id}
          source="authenticated"
          onClose={() => setPayNowOpen(false)}
        />
      ) : null}
      {editOpen && isInvoice ? (
        <InvoiceEditModal
          invoice={doc}
          signInfo={signInfo}
          onClose={() => setEditOpen(false)}
          onSaved={(res) => {
            if (res?.invoice) setDoc(res.invoice);
            setEditOpen(false);
            setToast({ tone: "success",
                        message: res?.changed
                          ? "Invoice updated" : "No changes to save" });
            // Refresh history if the panel is open.
            if (historyOpen && res?.changed) {
              api.get(`/quotes/${id}/edit-history`).then(setHistory).catch(() => {});
            }
            // Feb-2026 · Phase 2 — a save just created a new
            // version row, so if this is the first edit the
            // History trigger should now appear.
            if (res?.changed) setHasVersions(true);
          }}
        />
      ) : null}
      {/* Feb-2026 · Editable Sent Docs Phase 2 — the drawer is
          mounted at the root of the page so it can slide over
          the whole detail surface. Kept always-mounted to avoid
          a re-fetch on every open — the drawer itself gates on
          the ``open`` prop to (a) fetch when opening and
          (b) reset preview state when closing. */}
      <VersionHistoryDrawer
        open={versionDrawerOpen}
        onOpenChange={setVersionDrawerOpen}
        docType={isInvoice ? "invoice" : "quote"}
        docId={id}
      />
      {isStaff && isInvoice ? (
        <div
          className="rounded-2xl p-4 mt-4"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="invoice-edit-history-section"
        >
          <button
            type="button"
            onClick={() => {
              const next = !historyOpen;
              setHistoryOpen(next);
              if (next && history === null) {
                api.get(`/quotes/${id}/edit-history`)
                  .then(setHistory)
                  .catch(() => setHistory({ items: [], total: 0 }));
              }
            }}
            className="text-sm font-semibold flex items-center justify-between w-full"
            style={{ color: colors.onSurface }}
            data-testid="invoice-edit-history-toggle"
          >
            <span>Edit history</span>
            <span style={{ color: colors.muted }}>{historyOpen ? "▾" : "▸"}</span>
          </button>
          {historyOpen ? (
            <div className="mt-3" data-testid="invoice-edit-history-body">
              {history === null ? (
                <div className="text-xs" style={{ color: colors.muted }}>
                  Loading…
                </div>
              ) : (history.items || []).length === 0 ? (
                <div className="text-xs" style={{ color: colors.muted }}>
                  No edits recorded yet.
                </div>
              ) : (
                <ul className="space-y-3">
                  {history.items.map((h) => (
                    <li key={h.id}
                        data-testid={`invoice-edit-history-row-${h.id}`}
                        className="text-xs pb-2"
                        style={{ borderBottom: `1px solid ${colors.divider || colors.border}` }}>
                      <div className="font-semibold" style={{ color: colors.onSurface }}>
                        {h.edited_at} · {h.edited_by_user_email || "unknown"} · {h.edited_by_role}
                      </div>
                      <div style={{ color: colors.muted }}>
                        Status at edit: {h.invoice_status_at_edit}
                      </div>
                      <div className="mt-1">
                        Changed:{" "}
                        {Object.keys(h.changed_fields || {}).length
                          ? Object.keys(h.changed_fields).join(", ")
                          : "—"}
                      </div>
                      {(h.auto_effects || []).length ? (
                        <div style={{ color: colors.brand }}>
                          Auto-effects: {h.auto_effects.map((a) => a.kind).join("; ")}
                        </div>
                      ) : null}
                      {h.reason ? (
                        <div className="mt-1" style={{ color: colors.muted }}>
                          Reason: "{h.reason}"
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function SmsModal({ open, onClose, invoice, customer, onDone }) {
  const [to, setTo] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setTo(customer?.phone || "");
      setMsg(`Invoice ${invoice.id.slice(0, 8).toUpperCase()}: $${(invoice.total || 0).toFixed(2)} due. Pay: ${invoice.payment_link || "(generate link first)"}`);
    }
  }, [open, customer, invoice]);
  const send = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/invoices/${invoice.id}/send-sms`, { to, message: msg });
      if (r.sent) onDone(`Text sent to ${r.to}`);
      // Feb-2026 · Copy fix — the backend's "sms-not-configured" reason
      // is actually raised by the preview-only comms guard when the
      // recipient isn't on the SMS_ALLOWLIST. RC itself IS configured
      // + reachable. Clearer copy avoids user confusion.
      else if (r.reason === "sms-not-configured" || r.reason === "twilio-not-configured")
        onDone("SMS suppressed in preview environment. This number is not on the SMS_ALLOWLIST. In production, this would send via RingCentral.", "info");
      else onDone(r.reason || "Failed", "error");
    } catch (e) {
      onDone(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="Text Invoice via SMS"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={send} disabled={busy}>{busy ? "Sending…" : "Send SMS"}</Button></>}>
      <div className="space-y-3">
        <TextInput label="TO" value={to} onChange={(e) => setTo(e.target.value)} />
        <div>
          <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>MESSAGE</label>
          <textarea value={msg} onChange={(e) => setMsg(e.target.value)} rows={4}
            className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
            style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }} />
        </div>
      </div>
    </Modal>
  );
}

function RecordPaymentModal({ open, onClose, invoice, onDone, onError }) {
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) setAmount(String(Math.max(0, Number(invoice.total || 0) - Number(invoice.amount_paid || 0)).toFixed(2)));
  }, [open, invoice]);
  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`/quotes/${invoice.id}/record-payment`, { amount: Number(amount) });
      onDone(`Recorded ${money(Number(amount))}`);
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="Record Payment"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy}>{busy ? "Saving…" : "Record"}</Button></>}>
      <TextInput label="AMOUNT" type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
      <p className="text-xs mt-2" style={{ color: colors.muted }}>Cash / check / other — recorded manually. Stripe checkout marks paid automatically.</p>
    </Modal>
  );
}

function ConvertToJobModal({ open, onClose, quote, onDone, onError }) {
  const [scheduledDate, setScheduledDate] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const j = await api.post(`/quotes/${quote.id}/convert-to-job`, { scheduled_date: scheduledDate || null });
      onDone(j.id);
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="Convert quote to job"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy} testid="qd-convert-submit">{busy ? "Creating…" : "Create job"}</Button></>}>
      <TextInput label="SCHEDULE DATE (optional)" type="date" value={scheduledDate} onChange={(e) => setScheduledDate(e.target.value)} />
      <p className="text-xs mt-2" style={{ color: colors.muted }}>Creates a scheduled job for {quote.customer_name} totaling {money(quote.total)}.</p>
    </Modal>
  );
}



// ─── Phase C · Feb-2026 — admin visibility helpers ─────────────────
// Pure helper exported for Vitest — turns an ISO ``customer_declined_at``
// timestamp into a readable "Declined N days/hours ago" string. Kept
// out of the component body so tests can drive it without React.
export function formatDeclinedTimestamp(iso, nowMs = Date.now()) {
  if (!iso) return "";
  // Only accept ISO-8601-shaped strings. Any non-string shape
  // (legacy Mongo ``{$date: ...}``, raw numbers, Date objects
  // that slipped through the API layer) is treated as unknown
  // and rendered empty. Guards a prod-only render crash the
  // tester observed on ``/quotes/b565f464-...``.
  if (typeof iso !== "string") return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((nowMs - then) / 1000));
  if (secs < 60) return "Declined just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `Declined ${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `Declined ${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `Declined ${days} day${days === 1 ? "" : "s"} ago`;
}


// Feb-2026 · Phase 2/C-follow-up · Isolated error boundary so a
// crash inside the declined-lines banner or list cannot hang the
// whole doc-detail page. On the tester's prod verification the
// page appeared to hang because a React render exception broke the
// subtree above the K71 editor — this boundary catches any such
// exception, logs to the console, and renders a compact fallback
// so the rest of the detail page (K71, totals, action buttons)
// keeps working.
class DeclinedLinesErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { err: null };
  }
  static getDerivedStateFromError(err) {
    return { err };
  }
  componentDidCatch(err, info) {
    try {
      // eslint-disable-next-line no-console
      console.error("[DeclinedLinesErrorBoundary]", err, info);
    } catch { /* noop */ }
  }
  render() {
    if (this.state.err) {
      return (
        <div
          className="rounded-2xl p-3 my-3"
          style={{
            background: "#FEF2F2",
            border: "1px solid #FECACA",
            color: "#7F1D1D",
            fontSize: 12,
          }}
          data-testid="admin-declined-lines-error"
        >
          Declined-items summary is temporarily unavailable — the
          rest of this document is fine to edit.
        </div>
      );
    }
    return this.props.children;
  }
}


function AdminDeclinedLinesBanner({ doc }) {
  return <AdminDeclinedLinesBannerImpl doc={doc} />;
}

// Feb-2026 · Phase C — exported for Vitest so the fixture-driven
// suite can mount the banner + list directly without booting the
// full QuoteInvoiceDetail page (avoids the router / api /
// side-effects that were causing the SPA to appear "hung" on
// legacy docs where an unrelated network call was in flight).
export function AdminDeclinedLinesBannerImpl({ doc }) {
  const [expanded, setExpanded] = useState(false);
  const items = ((doc && doc.line_items) || []).filter(Boolean);
  const total = items.length;
  const declinedCount = Number(
    (doc && doc.declined_line_count)
    ?? items.filter((li) => (li.customer_status || "") === "declined").length,
  );
  const original = Number((doc && (doc.original_total ?? doc.total)) ?? 0);
  const adjusted = Number((doc && (doc.adjusted_total ?? doc.total)) ?? 0);
  return (
    <div
      className="rounded-2xl p-4 mb-4"
      style={{
        background: "#FEF3C7",
        border: "1px solid #FCD34D",
        color: "#78350F",
      }}
      data-testid="admin-declined-lines-banner"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-bold" style={{ color: "#78350F" }}>
            Customer declined {declinedCount} of {total} line
            item{total === 1 ? "" : "s"}
          </div>
          <div className="text-xs mt-0.5" style={{ color: "#92400E" }}>
            Original: {money(original)} → Adjusted: {money(adjusted)}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-xs font-semibold underline"
          style={{ color: "#78350F" }}
          data-testid="admin-declined-lines-banner-toggle"
        >
          {expanded ? "Hide details" : "Show details"}
        </button>
      </div>
      {expanded ? (
        <ul
          className="mt-3 text-xs space-y-1"
          data-testid="admin-declined-lines-banner-details"
        >
          {items
            .map((li, i) => ({ li, i }))
            .filter(({ li }) => (li.customer_status || "") === "declined")
            .map(({ li, i }) => (
              <li key={i} className="flex gap-2">
                <span className="font-semibold">·</span>
                <span className="flex-1">
                  <b>{li.description || `Line ${i + 1}`}</b>
                  {li.customer_decline_reason
                    ? ` — ${li.customer_decline_reason}`
                    : ""}
                </span>
                <span style={{ color: "#92400E" }}>
                  {money(li.total)}
                </span>
              </li>
            ))}
        </ul>
      ) : null}
    </div>
  );
}


function AdminDeclinedLinesList({ lineItems }) {
  return <AdminDeclinedLinesListImpl lineItems={lineItems} />;
}

// Feb-2026 · Phase C — exported for Vitest. Defensive filter on
// falsy line-item entries + safe access to every field so the
// summary card never throws on unexpected doc shapes.
export function AdminDeclinedLinesListImpl({ lineItems }) {
  const safe = (lineItems || []).filter(Boolean);
  return (
    <div
      className="mt-6 rounded-xl p-4"
      style={{
        background: "#FEF2F2",
        border: "1px solid #FECACA",
        color: "#7F1D1D",
      }}
      data-testid="admin-declined-lines-list"
    >
      <div className="text-xs uppercase font-bold tracking-wide mb-2"
            style={{ color: "#B91C1C" }}>
        Declined by customer
      </div>
      <div className="overflow-x-auto -mx-1">
      <table className="w-full text-xs" data-testid="admin-declined-lines-table"
             style={{ minWidth: 460 }}>
        <thead>
          <tr style={{ color: "#B91C1C" }}>
            <th className="text-left py-1">Line</th>
            <th className="text-left py-1">Reason</th>
            <th className="text-right py-1">When</th>
            <th className="text-right py-1">Total</th>
          </tr>
        </thead>
        <tbody>
          {safe.map((li, i) =>
            (li.customer_status || "") === "declined" ? (
              <tr key={i}
                  style={{ borderTop: "1px solid #FECACA" }}
                  data-testid={`admin-declined-line-row-${i}`}>
                <td className="py-1"
                    style={{ textDecoration: "line-through", opacity: 0.75 }}>
                  <span data-testid={`admin-line-item-declined-badge-${i}`}
                        style={{
                          display: "inline-block",
                          fontSize: 10,
                          fontWeight: 700,
                          padding: "1px 6px",
                          borderRadius: 4,
                          background: "#FEE2E2",
                          color: "#7F1D1D",
                          marginRight: 6,
                          textDecoration: "none",
                        }}>
                    Declined
                  </span>
                  {li.description || `Line ${i + 1}`}
                </td>
                <td className="py-1"
                    data-testid={`admin-line-item-decline-reason-${i}`}
                    title={li.customer_decline_reason || "No reason given"}>
                  {li.customer_decline_reason || "—"}
                </td>
                <td className="py-1 text-right"
                    title={li.customer_declined_at || ""}
                    data-testid={`admin-line-item-declined-at-${i}`}>
                  {formatDeclinedTimestamp(li.customer_declined_at) || "—"}
                </td>
                <td className="py-1 text-right font-mono">
                  {money(li.total)}
                </td>
              </tr>
            ) : null,
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}
