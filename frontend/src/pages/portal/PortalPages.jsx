import React, { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  CreditCard,
  Waves,
  Check,
  X as XIcon,
  Send,
  Download,
  FileText,
  Plus,
} from "lucide-react";
import { api } from "@/api";
// DTP-2 · Feb-2026 — module-level ``colors`` binds to the portal
// dark palette so every export in this file (PortalServices,
// PortalInvoices, PortalPayments, PortalDocuments, PortalMessages,
// PortalProfile, PortalRequestService, PortalPaymentComplete, …)
// renders inside the ``.dark portal-dark`` scope without a per-
// export shadow line. The pilot-era ``const colors = portalColors``
// shadows in the four already-migrated exports have been dropped
// below now that the module-level import IS the dark palette.
import { portalColors as colors, money, gradients } from "@/theme";
// TD-71 · Feb-2026 — customer-portal invoice-row display helpers:
// (a) ``resolvePortalInvoiceTitle`` rewrites imported invoices'
//     ``Import #<n>`` placeholder titles to a customer-friendly
//     fallback chain (``service_description`` → first line item →
//     ``notes`` truncated to 80 → ``"Invoice"``). Non-imported
//     titles pass through untouched.
// (b) ``formatInvoiceCreatedDate`` surfaces an additive ``Created
//     MM/DD/YYYY`` line below the title — the pre-TD-71 "No due
//     date" row left customers with no temporal context at all.
import {
  resolvePortalInvoiceTitle,
  formatInvoiceCreatedDate,
} from "@/lib/portalInvoiceTitle";
// DTP-1 · Feb-2026 — Shared portal lightbox for PortalServiceDetail
// (pilot). Other exports in this file keep their light ``colors``
// binding untouched.
import Lightbox from "@/components/portal/Lightbox";
import { useAuth } from "@/auth";
import InvoiceView from "@/components/InvoiceView";
import EstimateView from "@/components/EstimateView";
import PortalBookingPhotos from "@/components/portal/PortalBookingPhotos";
// Phase 5A hot-fix · Feb 2026 — replace the legacy hosted-checkout
// redirect with the Phase 4B <PaymentForm> modal (Card + ACH + wallets).
import PaymentForm from "@/components/PaymentForm";
// Phase I5 · Wave B · Feb-2026 — shared payment-method tiles.
import PaymentMethodTiles from "@/components/customers/PaymentMethodTiles";
// Phase I7 · Wave B · Feb-2026 — shared per-customer comms timeline.
// Feb-2026 · replaced by ``CustomerFullTimeline`` below; legacy
// ``CommunicationTimeline`` import removed to keep the module lint-clean.
import CustomerFullTimeline from "@/components/customers/CustomerFullTimeline";
// Phase 30 · Feb-2026 — shared TechAvatar for tech identity chips.
import TechAvatar from "@/components/common/TechAvatar";
import { PageHeader, Button, Skeleton, Chip, StatusPill, TextInput, EmptyState, Toast } from "@/components/ui-kit";
// Phase 18b · Feb-2026 — Portal white-card shell. Wraps every
// export in this file so the sub-page content renders inside the
// Phase 3d-portal white dashboard card on the deep-navy page
// background (same chrome as PortalHome).
import PortalPageShell from "@/components/portal/PortalPageShell";

// ──────────────── /portal/services ────────────────
export function PortalServices() {
  const navigate = useNavigate();
  const [tab, setTab] = useState("upcoming");
  const [jobs, setJobs] = useState(null);
  useEffect(() => {
    api.get("/portal/home").then((_d) => {
      api.get("/jobs").then((all) => {
        // /jobs already filters by customer on backend for customer role
        setJobs(all || []);
      }).catch(() => setJobs([]));
    });
  }, []);
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = (jobs || []).filter((j) =>
    ["scheduled", "active", "pending", "requested"].includes(j.status) &&
    (!j.scheduled_date || j.scheduled_date >= today)
  );
  const past = (jobs || []).filter(
    (j) => j.status === "completed" || j.status === "cancelled" || (j.scheduled_date && j.scheduled_date < today)
  );
  const list = tab === "upcoming" ? upcoming : past;

  return (
    <PortalPageShell>
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-services">
      <PageHeader title="My Services" subtitle="Upcoming visits and history." />
      <div className="flex gap-2 mb-4">
        {[
          { k: "upcoming", label: `Upcoming (${upcoming.length})` },
          { k: "past", label: `Past (${past.length})` },
        ].map((t) => (
          <button
            key={t.k}
            onClick={() => setTab(t.k)}
            className="px-4 py-2 rounded-full text-sm font-semibold"
            style={{
              backgroundColor: tab === t.k ? colors.brandTertiary : colors.surface,
              color: tab === t.k ? colors.onBrandTertiary : colors.muted,
              border: `1px solid ${tab === t.k ? colors.brandTertiary : colors.border}`,
            }}
            data-testid={`svc-tab-${t.k}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {jobs === null ? <Skeleton style={{ height: 180 }} /> :
       list.length === 0 ? <EmptyState icon={Waves} title="Nothing here yet" /> :
       <ul className="space-y-2">
         {list.map((j) => (
           <li key={j.id} onClick={() => navigate(`/portal/services/${j.id}`)}
             className="cursor-pointer flex items-center gap-3 p-4 rounded-xl transition hover:brightness-95"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid={`svc-${j.id}`}>
             <div className="w-11 h-11 rounded-xl flex items-center justify-center" style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}>
               <Waves size={18} />
             </div>
             <div className="flex-1 min-w-0">
               <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{j.title}</div>
               <div className="text-xs flex items-center gap-1.5" style={{ color: colors.muted }}>
                 {j.technician_name ? (
                   <TechAvatar user={{ name: j.technician_name }} size="xs" testid={`portal-tech-avatar-${j.id}`} />
                 ) : null}
                 <span>{j.scheduled_date || "TBD"} · {j.technician_name || "Unassigned"}</span>
               </div>
             </div>
             <StatusPill status={j.status} />
           </li>
         ))}
       </ul>}
    </div>
      </PortalPageShell>
  );
}

export function PortalServiceDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [j, setJ] = useState(null);
  const [lightboxIdx, setLightboxIdx] = useState(null);
  useEffect(() => { api.get(`/jobs/${id}`).then(setJ).catch(() => {}); }, [id]);
  if (!j) return <div className="max-w-3xl mx-auto p-6"><Skeleton style={{ height: 200 }} /></div>;
  const lightboxItems = (j.photos || []).map((p, i) => ({
    url:   p.url || p.data_url || p,
    kind:  "image",
    title: j.title ? `${j.title} · ${i + 1}` : `Photo ${i + 1}`,
  }));
  return (
    <PortalPageShell>
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-svc-detail">
      <button onClick={() => navigate("/portal/services")} className="flex items-center gap-1 text-sm font-semibold mb-4" style={{ color: colors.muted }}>
        <ArrowLeft size={14} /> My services
      </button>
      <div className="rounded-2xl p-6 mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <StatusPill status={j.status} />
        <h1 className="text-2xl font-bold mt-2" style={{ color: colors.onSurface }}>{j.title}</h1>
        <p className="text-sm mt-1 flex items-center gap-1.5" style={{ color: colors.muted }}>
          {j.technician_name ? (
            <TechAvatar user={{ name: j.technician_name }} size="sm" testid={`portal-tech-avatar-${j.id}`} />
          ) : null}
          <span>{j.scheduled_date} · {j.technician_name}</span>
        </p>
      </div>
      {(j.checklist || []).length ? (
        <div className="rounded-2xl p-5 mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <h3 className="font-bold mb-2" style={{ color: colors.onSurface }}>Service checklist</h3>
          <ul className="space-y-1 text-sm">
            {j.checklist.map((c) => (
              <li key={c.id} style={{ color: c.done ? colors.muted : colors.onSurface, textDecoration: c.done ? "line-through" : "none" }}>
                {c.done ? "✓ " : "○ "}{c.label}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {(j.chemical_readings && Object.keys(j.chemical_readings).length) ? (
        <div className="rounded-2xl p-5 mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <h3 className="font-bold mb-2" style={{ color: colors.onSurface }}>Water readings</h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(j.chemical_readings).map(([k, v]) => <Chip key={k} label={`${k.toUpperCase()} · ${v}`} tone="brand" />)}
          </div>
        </div>
      ) : null}
      {(j.photos || []).length ? (
        <div className="rounded-2xl p-5" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <h3 className="font-bold mb-2" style={{ color: colors.onSurface }}>Photos</h3>
          <div className="grid grid-cols-3 gap-2">
            {j.photos.map((p, i) => (
              <button
                type="button"
                key={i}
                onClick={() => setLightboxIdx(i)}
                className="rounded-lg overflow-hidden focus:outline-none focus:ring-2 focus:ring-blue-500"
                style={{ border: `1px solid ${colors.border}` }}
                data-testid={`portal-service-detail-photo-${i}`}
                aria-label={`Open photo ${i + 1}`}
              >
                <img src={p.url || p.data_url || p} alt="" className="w-full aspect-square object-cover" />
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <Lightbox
        items={lightboxItems}
        initialIndex={lightboxIdx == null ? 0 : lightboxIdx}
        open={lightboxIdx !== null}
        onClose={() => setLightboxIdx(null)}
        testidPrefix="portal-service-detail-lightbox"
      />
    </div>
      </PortalPageShell>
  );
}

// ──────────────── /portal/invoices ────────────────
export function PortalInvoices() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  useEffect(() => {
    api.get("/quotes?doc_type=invoice").then(setRows).catch(() => setRows([]));
  }, []);
  const total = (rows || []).reduce(
    (s, r) => s + Math.max(0, Number(r.total || 0) - Number(r.amount_paid || 0)),
    0
  );
  return (
    <PortalPageShell>
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-invoices" data-tour-id="invoices-list">
      <PageHeader title="My Invoices" subtitle="Pay online, download receipts." />
      <div className="rounded-2xl p-5 mb-4" style={{ background: gradients.navyToGreen.css, color: "#fff" }}>
        <div className="text-sm opacity-85">Total outstanding</div>
        <div className="text-3xl font-bold mt-1" data-testid="port-outstanding">{money(total)}</div>
      </div>
      {rows === null ? <Skeleton style={{ height: 220 }} /> :
       rows.length === 0 ? <EmptyState icon={FileText} title="No invoices yet" /> :
       <ul className="space-y-2">
         {rows.map((r) => {
           const balance = Math.max(0, Number(r.total || 0) - Number(r.amount_paid || 0));
           // TD-71 · Feb-2026 — customer-friendly title (rewrites
           // ``Import #<n>`` on imported invoices only, else
           // passthrough) + additive ``Created MM/DD/YYYY`` line
           // below the title. The pre-TD-71 "No due date" row
           // stays as the SECOND line (unchanged).
           const _displayTitle = resolvePortalInvoiceTitle(r);
           const _createdLine = formatInvoiceCreatedDate(r);
           return (
             <li key={r.id} onClick={() => navigate(`/portal/invoices/${r.id}`)}
               className="cursor-pointer flex items-center gap-3 p-4 rounded-xl"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid={`port-inv-${r.id}`}>
               <div className="flex-1 min-w-0">
                 <div
                   className="text-sm font-semibold"
                   style={{ color: colors.onSurface }}
                   data-testid={`port-inv-title-${r.id}`}
                 >{_displayTitle}</div>
                 {_createdLine ? (
                   <div
                     className="text-xs"
                     style={{ color: colors.muted }}
                     data-testid={`port-inv-created-${r.id}`}
                   >{_createdLine}</div>
                 ) : null}
                 <div className="text-xs" style={{ color: colors.muted }}>{r.due_date ? `Due ${r.due_date}` : "No due date"}</div>
               </div>
               <div className="text-right">
                 <div className="font-semibold" style={{ color: colors.onSurface }}>{money(r.total)}</div>
                 <Chip label={r.payment_status || "unpaid"} tone={r.payment_status === "paid" ? "success" : balance > 0 ? "danger" : "warning"} />
               </div>
             </li>
           );
         })}
       </ul>}
    </div>
      </PortalPageShell>
  );
}

export function PortalInvoiceDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth() || {};
  const [params] = useSearchParams();
  const printable = params.get("format") === "printable";
  const [doc, setDoc] = useState(null);
  const [toast, setToast] = useState(null);
  // Phase 5A hot-fix · Feb 2026 — Portal Pay Now now uses the Phase 4B
  // <PaymentForm> (Card + ACH + wallets). The legacy
  // /api/payments/checkout/{id} endpoint returned "Stripe not
  // configured" whenever the older Phase-53 SDK path hit an exception.
  const [payNowOpen, setPayNowOpen] = useState(false);
  // Feb-2026 · Task 3 · Invoices bypass portal — a logged-in customer
  // hitting the portal invoice detail is bounced to the canonical
  // magic-link viewer at ``/i/:token`` so the pay experience is
  // identical whether they landed via email/SMS or a portal
  // bookmark. Staff (admin / manager / super_admin) preview access
  // and printable exports keep the in-portal render.
  const [redirecting, setRedirecting] = useState(false);
  useEffect(() => {
    if (printable) return;
    const role = (user && user.role) || "";
    if (role !== "customer") return;
    setRedirecting(true);
    api.get(`/invoices/${id}/magic-link`)
      .then((r) => {
        const token = (r && r.token) || "";
        if (token) {
          navigate(`/i/${token}`, { replace: true });
        } else {
          setRedirecting(false);
        }
      })
      .catch(() => setRedirecting(false));
  }, [id, printable, user, navigate]);
  useEffect(() => { api.get(`/quotes/${id}`).then(setDoc).catch(() => {}); }, [id]);

  const balance = doc
    ? Math.max(0, Number(doc.total || 0) - Number(doc.amount_paid || 0))
    : 0;

  return (
    <PortalPageShell>
    <div
      className={printable ? "" : "max-w-4xl mx-auto px-2 sm:px-4 lg:px-6 py-4"}
      data-testid="portal-inv-detail"
    >
      {redirecting ? (
        <div
          className="text-sm text-center py-8"
          style={{ color: colors.muted }}
          data-testid="portal-inv-detail-redirecting"
        >
          Opening your invoice…
        </div>
      ) : null}
      {!printable && !redirecting ? (
        <div className="max-w-4xl mx-auto mb-3 px-2">
          <button
            onClick={() => navigate("/portal/invoices")}
            className="flex items-center gap-1 text-sm font-semibold mb-3"
            style={{ color: colors.muted }}
          >
            <ArrowLeft size={14} /> My invoices
          </button>
          {/* Feb-2026 · P0 Bug B — top-right Pay CTA. Previously
              only gated on ``balance > 0``, which allowed the CTA
              to show on invoices with ``payment_status="paid"``
              but stale ``amount_paid`` (seed / imported data
              artifact). We now also require the invoice to not
              be terminally paid so the CTA is honest. Matches
              the ``InvoiceView.canPay`` gate one level deeper.
              Feb 2026 · Invoice Pay Now restyle — full-width red
              CTA (design-system red tokens; no raw hex) dominates
              the top of the customer-facing portal invoice page. */}
          {doc && balance > 0
              && (doc?.payment_status || "").toLowerCase() !== "paid" ? (
            <button
              type="button"
              onClick={() => setPayNowOpen(true)}
              data-testid="port-pay"
              className="w-full bg-red-600 hover:bg-red-700 text-white font-semibold rounded-xl inline-flex items-center justify-center gap-2 px-5 py-3 transition"
            >
              <CreditCard size={16} /> {`Pay ${money(balance)}`}
            </button>
          ) : null}
        </div>
      ) : null}
      {!redirecting ? (
        <InvoiceView invoiceId={id} printable={printable} />
      ) : null}
      {payNowOpen ? (
        <PaymentForm
          invoice={doc}
          invoiceId={id}
          source="authenticated"
          onClose={() => setPayNowOpen(false)}
        />
      ) : null}
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
      </PortalPageShell>
  );
}

// ──────────────── /portal/estimates ────────────────
export function PortalEstimates() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/quotes?doc_type=quote").then(setRows).catch(() => setRows([])); }, []);
  return (
    <PortalPageShell>
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-estimates" data-tour-id="estimates-list">
      <PageHeader title="Estimates" subtitle="Approve or decline proposals." />
      {rows === null ? <Skeleton style={{ height: 180 }} /> :
       rows.length === 0 ? <EmptyState icon={FileText} title="No estimates yet" /> :
       <ul className="space-y-2">
         {rows.map((r) => (
           <li key={r.id} onClick={() => navigate(`/portal/estimates/${r.id}`)}
             className="cursor-pointer flex items-center gap-3 p-4 rounded-xl"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid={`port-est-${r.id}`}>
             <div className="flex-1 min-w-0">
               <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{r.title}</div>
               <div className="text-xs" style={{ color: colors.muted }}>{money(r.total)}</div>
             </div>
             <StatusPill status={r.decision || r.status} />
           </li>
         ))}
       </ul>}
    </div>
      </PortalPageShell>
  );
}

export function PortalEstimateDetail() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const printable = params.get("format") === "printable";
  const [toast, setToast] = useState(null);
  // Feb-2026 · Phase A · Item 1 — read the magic-link token from the
  // URL so the Phase A path-based endpoints on ``EstimateView`` fire
  // against ``/portal/quotes/via-token/{token}/…``. The AppLayout
  // auth guard has a matching bypass (see ``ProtectedShell``) that
  // allows this route to render for anonymous visitors when
  // ``?token=`` is present. Log a WARN so we can pick which wiring
  // path (this route vs the newly-added ``/e/estimate``) survives
  // long-term.
  const token = params.get("token") || null;
  if (token && typeof window !== "undefined"
      && !window.__phaseA_portal_estimates_id_warned) {
    // eslint-disable-next-line no-console
    console.warn(
      "[phase-a] token-bearing /portal/estimates/:id hit. Consider "
      + "consolidating on /e/estimate.",
    );
    window.__phaseA_portal_estimates_id_warned = true;
  }
  return (
    <PortalPageShell>
    <div
      className={printable ? "" : "max-w-4xl mx-auto px-2 sm:px-4 lg:px-6 py-4"}
      data-testid="portal-est-detail"
    >
      <EstimateView
        estimateId={id}
        isAdmin={false}
        printable={printable}
        token={token}
      />
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
      </PortalPageShell>
  );
}

// ──────────────── /portal (rest) ────────────────

// ──────────────── /portal/payments + /portal/payment-method ────────────────
export function PortalPayments() {
  const navigate = useNavigate();
  const [payments, setPayments] = useState(null);
  const [pm, setPm] = useState(null);
  useEffect(() => {
    // Phase 34 · Feb-2026 · bug-fix — the ``/me/payments`` endpoint returns
    // ``{total_paid, count, payments: [...]}`` (an aggregation envelope),
    // NOT a bare array. The previous code called ``.map()`` on the whole
    // response and crashed with "payments.map is not a function". We now
    // normalize to an array so we're tolerant to either shape (bare array
    // OR any of the common envelope keys).
    api.get("/me/payments").then((resp) => {
      const list = Array.isArray(resp)
        ? resp
        : (resp?.payments || resp?.items || resp?.data || resp?.rows || []);
      setPayments(list);
    }).catch(() => setPayments([]));
    // Feb-2026 P0 fix (Bug 2 · Item A) — was ``/payments/method``
    // which returns 404 on this deployment. The portal-scoped list
    // endpoint returns ``{methods: [...]}``; pick the default (or
    // first) entry for the summary chip on this page.
    api
      .get("/customer-portal/payment-methods")
      .then((r) => {
        const list = Array.isArray(r?.methods) ? r.methods : [];
        const chosen = list.find((m) => m?.is_default) || list[0] || null;
        setPm(chosen);
      })
      .catch(() => setPm(null));
  }, []);
  return (
    <PortalPageShell>
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-payments">
      <PageHeader title="Payments" subtitle="History + saved card." />
      <div className="rounded-2xl p-5 mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>Card on file</div>
            {pm?.brand ? (
              <div className="text-base font-semibold mt-1" style={{ color: colors.onSurface }} data-testid="pm-summary">
                {pm.brand} · •••• {pm.last4}
              </div>
            ) : (
              <div className="text-sm mt-1" style={{ color: colors.muted }}>No saved card</div>
            )}
          </div>
          <Button variant="ghost" onClick={() => navigate("/portal/payment-method")}>Manage</Button>
        </div>
      </div>
      {payments === null ? <Skeleton style={{ height: 200 }} /> :
       !Array.isArray(payments) || payments.length === 0 ? (
         <EmptyState
           icon={CreditCard}
           title="No payments yet"
           message="Once you make a payment, your history will appear here."
           data-testid="portal-payments-empty"
         />
       ) :
       <ul className="space-y-2" data-testid="portal-payments-list">
         {payments.map((p, i) => (
           <li key={p.id || i} className="flex items-center gap-3 p-3 rounded-xl" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid={`portal-payment-row-${i}`}>
             <div className="flex-1">
               <div className="text-sm font-semibold">{money(p.amount)}</div>
               <div className="text-xs" style={{ color: colors.muted }}>{p.paid_at || p.created_at}</div>
             </div>
             <Chip label={p.method || "Stripe"} tone="brand" />
           </li>
         ))}
       </ul>}
    </div>
      </PortalPageShell>
  );
}

export function PortalPaymentMethod() {
  const navigate = useNavigate();
  const { user } = useAuth();
  // Phase I5 · Wave B · Feb-2026 — the portal Billing Method tab
  // now delegates the entire card + ACH surface to the shared
  // ``PaymentMethodTiles`` component so the customer-facing view
  // stays visually aligned with the admin Customer Detail page.
  //
  // The shared component hits ``GET /api/payments/stripe/payment-
  // methods/{customer_id}``.  RBAC on that endpoint (verified in
  // Wave A · ``test_i5_rbac_customer_own_pm_allowed``) permits
  // ``role="customer"`` to see + delete their own methods, so we
  // pass the JWT-scoped ``user.customer_id`` and rely on the same
  // TypedConfirmModal-gated delete flow the admin variant uses.
  return (
    <PortalPageShell>
    <div
      className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
      data-testid="portal-pm"
      data-tour-id="payment-method-panel"
    >
      <button
        onClick={() => navigate("/portal/payments")}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> Payments
      </button>
      <PageHeader
        title="Payment Methods"
        subtitle="Save a card or connect a bank account so admin can charge you for approved services without another checkout."
      />
      <PaymentMethodTiles
        customerId={user?.customer_id}
        variant="portal"
      />
    </div>
      </PortalPageShell>
  );
}


// ──────────────── /portal/documents ────────────────
export function PortalDocuments() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/me/documents").then(setRows).catch(() => setRows([])); }, []);
  return (
    <PortalPageShell>
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-docs">
      <PageHeader title="Documents" subtitle="Contracts, receipts, warranties." />
      {rows === null ? <Skeleton style={{ height: 180 }} /> :
       rows.length === 0 ? <EmptyState icon={FileText} title="No documents yet" /> :
       <ul className="space-y-2">
         {rows.map((d) => (
           <li key={d.id} className="flex items-center gap-3 p-4 rounded-xl" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
             <FileText size={22} color={colors.muted} />
             <div className="flex-1">
               <div className="text-sm font-semibold">{d.name}</div>
               <div className="text-xs" style={{ color: colors.muted }}>{d.uploaded_at}</div>
             </div>
             <a href={d.url} download><Button variant="ghost"><Download size={14} /> Download</Button></a>
           </li>
         ))}
       </ul>}
    </div>
      </PortalPageShell>
  );
}

// ──────────────── /portal/messages ────────────────
export function PortalMessages() {
  // Feb-2026 — the per-conversation AI sparkles toggle used to live
  // here (data-testid="msg-ai-toggle"). It has been removed from the
  // customer portal per product guardrail: no AI-adjacent UI on
  // customer-facing surfaces. Message text is now sent verbatim.
  //
  // Phase I7 · Wave B · Feb-2026 — the shared
  // ``CommunicationTimeline`` is appended below the chat thread so
  // the customer can see every outbound SMS + email the business
  // has sent them alongside the live 2-way conversation. Server
  // strips admin-only fields (``actor_user_id`` +
  // ``delivery_error``) for the portal caller.
  // Feb-2026 · PortalMessages does not read the current user off
  // ``useAuth`` — server scopes ``/me/messages`` by JWT — so the
  // hook is dropped to keep the module lint-clean. Chat bubbles
  // side by role on ``m.from_role === "customer"`` alone.
  const [threads, setThreads] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  const load = async () => {
    try {
      const r = await api.get("/me/messages");
      setThreads(Array.isArray(r) ? r : (r?.threads || []));
    } catch { setThreads([]); }
  };
  useEffect(() => { load(); }, []);

  const send = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await api.post("/me/messages", { message: text });
      setText("");
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally { setBusy(false); }
  };

  return (
    <PortalPageShell>
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-messages" data-tour-id="communications-list">
      <PageHeader title="Messages" subtitle="Talk to your service team." />
      <div className="rounded-2xl overflow-hidden mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, minHeight: 320 }}>
        <div className="p-4 space-y-2 max-h-[50vh] overflow-y-auto">
          {threads === null ? <Skeleton style={{ height: 60 }} /> :
           threads.length === 0 ? <p className="text-sm text-center py-8" style={{ color: colors.muted }}>No messages yet. Start the conversation below.</p> :
           threads.map((m, i) => {
             const mine = m.from_role === "customer";
             return (
               <div key={i} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                 <div className="max-w-[75%] rounded-2xl px-3 py-2 text-sm"
                   style={{
                     backgroundColor: mine ? colors.brand : colors.surfaceSecondary,
                     color: mine ? "#fff" : colors.onSurface,
                   }}>
                   {m.message || m.text}
                 </div>
               </div>
             );
           })}
        </div>
      </div>
      <div className="rounded-2xl p-3 flex items-center gap-2" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Write a message…" rows={1}
          className="portal-input flex-1 px-3 py-2 text-sm rounded-lg outline-none resize-none focus:ring-2"
          data-testid="msg-input" />
        <Button onClick={send} disabled={busy || !text.trim()} testid="msg-send"><Send size={14} /></Button>
      </div>

      {/* Phase I7 · Wave B · Feb-2026 — historical outbound comms
          (SMS + email dispatch log) appended below the live thread. */}
      <section
        className="mt-6"
        data-testid="portal-messages-comm-timeline-section"
      >
        <h2
          className="text-base font-bold mb-3 flex items-center gap-2"
          style={{ color: colors.onSurface }}
        >
          Communication History
        </h2>
        {/* Feb-2026 · Full-history timeline (marketing deliveries +
            invoices + estimates). Replaces the legacy
            ``CommunicationTimeline`` in the portal chat surface. */}
        <CustomerFullTimeline scope="portal" />
      </section>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
      </PortalPageShell>
  );
}

// ──────────────── /portal/profile ────────────────
export function PortalProfile() {
  const { user, refreshMe } = useAuth();
  const [form, setForm] = useState({
    first_name: "", last_name: "", email: "", phone: "", address: "",
    // Feb-2026 · portal-profile extension — secondary email is a
    // separate optional slot in the customer's ``emails[]`` multi-
    // contact array. Empty string → clear.
    secondary_email: "",
  });
  const [initial, setInitial] = useState(null);
  // Feb-2026 · Phase 3c-portal — current-email confirmation gate.
  // ``initialEmail`` is the server-stored primary email captured on
  // hydration; the confirmation input renders only when the form's
  // email drifts from this value.
  const [initialEmail, setInitialEmail] = useState("");
  const [confirmCurrentEmail, setConfirmCurrentEmail] = useState("");
  const [confirmEmailError, setConfirmEmailError] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    // Phase 34 · Task N — load the customer's current profile from
    // /me so we start with the freshest linked values.
    //
    // Feb-2026 · portal-profile extension — also hydrate the
    // secondary email slot by picking the first non-primary entry
    // from ``customer.emails[]``. Missing / single-entry arrays
    // resolve to an empty string (clear slot).
    api.get(`/me`)
      .then((c) => {
        const emails = Array.isArray(c?.emails) ? c.emails : [];
        const sec = emails.find(
          (e) => e && e.address && !e.is_primary,
        );
        const nx = {
          first_name: c?.first_name || (user?.name || "").split(" ")[0] || "",
          last_name: c?.last_name || (user?.name || "").split(" ").slice(1).join(" ") || "",
          email: c?.email || user?.email || "",
          phone: c?.phone || "",
          address: c?.address || "",
          secondary_email: sec ? sec.address : "",
        };
        setForm(nx);
        setInitial(JSON.stringify(nx));
        // Phase 3c-portal — capture the server-authoritative
        // primary email so the confirmation gate knows whether the
        // user is actually changing it.
        setInitialEmail(nx.email || "");
      })
      .catch(() => {});
    // Depend on user?.id to prevent reset-on-every-render; see PortalProfile.emailChange.test.jsx failure trace
  }, [user?.id]);

  const dirty = initial && JSON.stringify(form) !== initial;
  // Feb-2026 · portal-profile extension — reuse the same RFC-lite
  // pattern the primary email uses for the secondary slot. Empty
  // string is valid (clears the slot); non-empty must match the
  // pattern AND differ from the primary.
  const _emailRe = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  const secTrimmed = form.secondary_email.trim().toLowerCase();
  const primaryTrimmed = form.email.trim().toLowerCase();
  const secondaryEmailValid = (
    secTrimmed === ""
      ? true
      : (_emailRe.test(secTrimmed) && secTrimmed !== primaryTrimmed)
  );
  const secondaryEmailError = (
    secTrimmed === "" ? "" :
    !_emailRe.test(secTrimmed)
      ? "Please enter a valid secondary email address."
      : secTrimmed === primaryTrimmed
        ? "Secondary email must differ from primary."
        : ""
  );
  // Feb-2026 · Phase 3c-portal — the email is "changed" iff the
  // trimmed/lowercased form value differs from the hydrated
  // ``initialEmail``. Confirmation input renders + is required
  // only when this flag is true.
  const emailChanged = (
    initialEmail.trim().toLowerCase() !== ""
    && primaryTrimmed !== initialEmail.trim().toLowerCase()
  );
  const confirmEmailValid = (
    !emailChanged
      ? true
      : confirmCurrentEmail.trim().length > 0
  );
  const valid = (
    form.first_name.trim() &&
    form.email.trim() && _emailRe.test(form.email) &&
    ("" + form.phone).replace(/\D/g, "").length >= 10 &&
    form.address.trim().length >= 5 &&
    secondaryEmailValid &&
    confirmEmailValid
  );
  const canSave = dirty && valid && !saving;

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async (e) => {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true); setError(""); setConfirmEmailError("");
    try {
      // Feb-2026 · portal-profile extension — send the secondary
      // email as an explicit key so the backend can distinguish
      // "no change" (field omitted) from "clear the slot"
      // (empty string).  Trim + lowercase before wire so a stray
      // typing space can't reject the payload server-side.
      // Phase 3c-portal — include ``confirm_current_email`` ONLY
      // when the primary email is being changed (otherwise the
      // backend gate skips, and sending the field would just
      // waste bytes).
      const payload = {
        ...form,
        secondary_email: form.secondary_email.trim().toLowerCase(),
        ...(emailChanged
          ? { confirm_current_email: confirmCurrentEmail.trim() }
          : {}),
      };
      await api.patch("/customer-portal/profile", payload);
      setToast({ tone: "success", message: "Profile updated" });
      // Snapshot the saved values so the form becomes clean again.
      setInitial(JSON.stringify(form));
      // Phase 3c-portal — advance the server-stored baseline so a
      // subsequent email change starts a fresh confirmation gate
      // from the just-saved value.
      setInitialEmail(form.email || "");
      setConfirmCurrentEmail("");
      // Refresh cached user context so the header / other surfaces
      // pick up the new name/email.
      try { await refreshMe?.(); } catch (_) { /* best-effort */ }
    } catch (err) {
      const msg = err?.message || "Could not save. Please try again.";
      // Phase 3c-portal — route the confirmation-mismatch 400 into
      // the inline input's error slot (not the page-level banner)
      // so the user can retype directly on the field that failed.
      // Prefix match pins to the server's exact string ("Current
      // email confirmation does not match.") and tolerates any
      // future server-side suffix.
      if (msg.toLowerCase().startsWith("current email confirmation")) {
        setConfirmEmailError(msg);
      } else {
        setError(msg);
      }
    } finally {
      setSaving(false);
    }
  };

  const cancel = () => {
    if (!initial) return;
    setForm(JSON.parse(initial));
    setError("");
    setConfirmCurrentEmail("");
    setConfirmEmailError("");
  };

  const changePw = async () => {
    setBusy(true);
    try {
      // Phase 34 · Task O — endpoint expects ``current_password`` /
      // ``new_password``. Prior code used ``old_password`` which
      // silently 400'd server-side.
      await api.post("/auth/change-password", { current_password: oldPw, new_password: newPw });
      setToast({ tone: "success", message: "Password changed" });
      setOldPw(""); setNewPw("");
    } catch (e) { setToast({ tone: "error", message: e.message }); }
    finally { setBusy(false); }
  };

  return (
    <PortalPageShell>
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-profile">
      <PageHeader title="Profile" subtitle="Keep your contact info up to date so your service team can reach you." />
      <form onSubmit={save} className="rounded-2xl p-5 mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }} data-testid="portal-profile-form">
        {error ? (
          <div className="rounded-lg p-3 mb-3 text-sm"
                style={{ background: "#FEF2F2", border: "1px solid #FCA5A5", color: "#991B1B" }}
                data-testid="portal-profile-error">{error}</div>
        ) : null}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <TextInput label="FIRST NAME" value={form.first_name} onChange={set("first_name")} testid="portal-profile-first-name" />
          <TextInput label="LAST NAME"  value={form.last_name}  onChange={set("last_name")}  testid="portal-profile-last-name" />
        </div>
        <TextInput label="EMAIL"   type="email" value={form.email}   onChange={set("email")}   testid="portal-profile-email" />
        {/* Feb-2026 · Phase 3c-portal — current-email confirmation
            gate. Rendered ONLY when the user has edited the primary
            email away from the hydrated value. Edit back to the
            original → this block disappears. Testids pinned by the
            Phase-3c-portal brief. */}
        {emailChanged ? (
          <div className="mt-2 mb-2" data-testid="portal-profile-email-change-notice">
            <p className="text-xs mb-1" style={{ color: "#92400E" }}>
              You're changing your email. Confirm your current email to continue.
            </p>
            <input
              type="email"
              value={confirmCurrentEmail}
              onChange={(e) => {
                setConfirmCurrentEmail(e.target.value);
                setConfirmEmailError("");
              }}
              placeholder="Confirm current email"
              data-testid="portal-profile-confirm-current-email"
              className="portal-input w-full text-sm px-3 py-2 rounded-md"
            />
            {confirmEmailError ? (
              <p
                data-testid="portal-profile-confirm-current-email-error"
                className="text-xs mt-1"
                style={{ color: "#B91C1C" }}
              >
                {confirmEmailError}
              </p>
            ) : null}
          </div>
        ) : null}
        {/* Feb-2026 · portal-profile extension — Secondary email
            slot sits directly under the primary so the two email
            fields read as a coherent block.  Empty payload clears
            the slot server-side.  Inline validation mirrors the
            server contract: RFC-lite regex + must-differ-from-
            primary. */}
        <TextInput
          label="SECONDARY EMAIL (OPTIONAL)"
          type="email"
          value={form.secondary_email}
          onChange={set("secondary_email")}
          testid="portal-profile-secondary-email"
        />
        {secondaryEmailError ? (
          <div
            className="text-xs mt-1 mb-2"
            style={{ color: "#B91C1C" }}
            data-testid="portal-profile-secondary-email-error"
          >
            {secondaryEmailError}
          </div>
        ) : null}
        <TextInput label="PHONE"   type="tel"   value={form.phone}   onChange={set("phone")}   testid="portal-profile-phone" />
        <TextInput label="ADDRESS"              value={form.address} onChange={set("address")} testid="portal-profile-address" />
        <div className="mt-4 flex items-center gap-3">
          <Button type="submit" disabled={!canSave} testid="portal-profile-save">
            {saving ? "Saving…" : "Save changes"}
          </Button>
          <button type="button" onClick={cancel} disabled={!dirty || saving}
                  className="text-sm font-semibold" style={{ color: colors.muted }}
                  data-testid="portal-profile-cancel">Cancel</button>
        </div>
      </form>
      <div className="rounded-2xl p-5" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <h3 className="font-bold mb-2" style={{ color: colors.onSurface }}>Change password</h3>
        <div className="space-y-3">
          <TextInput label="CURRENT PASSWORD" type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} testid="pf-old-pw" />
          <TextInput label="NEW PASSWORD (≥8 chars, upper+lower+digit)" type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} testid="pf-new-pw" />
        </div>
        <div className="mt-3">
          <Button onClick={changePw} disabled={busy || !oldPw || !newPw} testid="pf-change">
            {busy ? "Saving…" : "Change password"}
          </Button>
        </div>
      </div>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
      </PortalPageShell>
  );
}

// ──────────────── /portal/request-service ────────────────
export function PortalRequestService() {
  const navigate = useNavigate();
  const { _user } = useAuth();
  // Phase 34 · Feb-2026 — Task I. The Service Type dropdown has been
  // removed. Customers now describe what they need in a free-text
  // paragraph; the backend defaults ``service_type`` to
  // ``"general_request"`` server-side so downstream dashboards keep
  // rendering. Preferred date + attachments (unchanged surface here)
  // remain intact.
  //
  // Phase F2c.1 · Feb-2026 — post-submit, we hold on to the returned
  // service-request id and render <PortalBookingPhotos> so the
  // customer can attach photos of the issue before leaving the page.
  // Falls back to the historical "immediate navigate" behaviour if
  // the endpoint doesn't return an id.
  const MIN_LEN = 10;
  const MAX_LEN = 2000;
  const [form, setForm] = useState({ request_details: "", preferred_date: "" });
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [createdId, setCreatedId] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const detailsLen = form.request_details.trim().length;
  const canSubmit = detailsLen >= MIN_LEN && detailsLen <= MAX_LEN && !busy;
  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    try {
      const res = await api.post("/customer-portal/service-requests", {
        request_details: form.request_details.trim(),
        preferred_date: form.preferred_date || undefined,
      });
      const rid = res?.id || res?.request_id || res?.message_id;
      setToast({ tone: "success", message: "Request sent — attach photos below if it helps." });
      if (rid) {
        setCreatedId(rid);   // stay on page for optional photo upload
      } else {
        setTimeout(() => navigate("/portal/home"), 800);
      }
    } catch (err) { setToast({ tone: "error", message: err.message }); }
    finally { setBusy(false); }
  };
  return (
    <PortalPageShell>
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-request" data-tour-id="request-service-form">
      <PageHeader title="Request Service" subtitle="Tell us what you need." />
      <form onSubmit={submit} className="rounded-2xl p-5 space-y-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div>
          <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>
            WHAT SERVICE DO YOU NEED?
          </label>
          <textarea
            value={form.request_details}
            onChange={set("request_details")}
            rows={6}
            required
            minLength={MIN_LEN}
            maxLength={MAX_LEN}
            placeholder="Describe what you need — e.g., green pool, broken sprinkler, tree trim, etc."
            className="portal-input w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
            data-testid="rs-details"
          />
          <div className="flex items-center justify-between mt-1 text-xs" style={{ color: colors.muted }}>
            <span data-testid="rs-details-hint">
              {detailsLen < MIN_LEN
                ? `A little more detail helps us prep the right crew (min ${MIN_LEN} characters).`
                : "Thanks — that's plenty to get us started."}
            </span>
            <span data-testid="rs-details-count">{detailsLen}/{MAX_LEN}</span>
          </div>
        </div>
        <TextInput label="PREFERRED DATE (OPTIONAL)" type="date" value={form.preferred_date} onChange={set("preferred_date")} testid="rs-date" />
        <div className="flex justify-end pt-2">
          <Button type="submit" disabled={!canSubmit || Boolean(createdId)} testid="rs-submit">
            <Plus size={14} /> {busy ? "Sending…" : createdId ? "Request sent ✓" : "Send request"}
          </Button>
        </div>
      </form>
      {createdId ? (
        <div className="mt-4" data-testid="rs-photos-panel">
          <PortalBookingPhotos appointmentId={createdId} />
          <div className="flex justify-end mt-3">
            <Button type="button" variant="ghost" onClick={() => navigate("/portal/home")} testid="rs-done">
              Done
            </Button>
          </div>
        </div>
      ) : null}
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
      </PortalPageShell>
  );
}

// ──────────────── /portal/payment-complete ────────────────
export function PortalPaymentComplete() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const sid = params.get("session_id");
  // Feb-2026 · Stripe reconcile-endpoint hardening. Previously this
  // screen ONLY polled ``GET /payments/status/{sid}`` and relied on
  // ``checkout.session.completed`` webhook delivery to flip the
  // invoice. If the webhook mis-fired (Thin-payload rejection,
  // Dashboard misconfig, transient blip), the customer sat in the
  // "still processing" state forever. We now fire a synchronous
  // ``POST /payments/stripe/session/{sid}/reconcile`` first — it
  // retrieves the Session from Stripe, verifies paid, and calls the
  // same ``_mark_invoice_paid_from_session`` the webhook uses.
  // Idempotent, so a subsequent webhook is a no-op.
  const [status, setStatus] = useState("checking");
  const [invoice, setInvoice] = useState(null);
  // Feb 2026 · Feb-2026 lint sweep — ``errMsg`` is threaded through
  // for future retry UX (issue tracked in memory/known_issues.md).
  // Underscore prefix satisfies the ``^_`` unused-vars allowlist.
  const [_errMsg, setErrMsg] = useState(null);
  const [retryKey, setRetryKey] = useState(0);   // bump to re-fire
  // Feb-2026 · Priority 3 — autobilling opt-in state. Only shown when
  // the reconcile response confirms a payment method was saved AND
  // the customer has NOT already opted in. Local UI state tracks
  // dismissal / success so the card doesn't linger after action.
  const [showAutobillingCta, setShowAutobillingCta] = useState(false);
  const [autobillingBusy, setAutobillingBusy] = useState(false);
  const [autobillingResult, setAutobillingResult] = useState(null);

  useEffect(() => {
    if (!sid) { setStatus("no_session"); return; }
    let cancelled = false;
    setStatus("checking");
    setErrMsg(null);
    // Reset CTA between retries so a stale success banner doesn't
    // carry over into a fresh reconcile attempt.
    setShowAutobillingCta(false);
    setAutobillingResult(null);

    const loadInvoice = async (invoice_id) => {
      if (!invoice_id) return;
      try {
        const inv = await api.get(`/quotes/${invoice_id}`);
        if (!cancelled) setInvoice(inv);
      } catch { /* non-fatal */ }
    };

    (async () => {
      // Phase 1 — synchronous reconcile. Guaranteed one round-trip;
      // no wait on webhook infrastructure.
      try {
        const r = await api.post(
          `/payments/stripe/session/${encodeURIComponent(sid)}/reconcile`,
          {},
        );
        if (cancelled) return;
        if (r?.reconciled) {
          setStatus("paid");
          // Priority 3 · Feb 2026 — surface the autobilling CTA
          // only when Stripe confirmed a saved PM AND the customer
          // has not already opted in on a prior payment.
          if (r.payment_method_saved && !r.autobilling_enabled) {
            setShowAutobillingCta(true);
          }
          if (r.invoice_id) loadInvoice(r.invoice_id);
          return;
        }
        // ``reconciled: false`` — Stripe still shows unpaid (bank
        // hold, ACH pending, 3DS still in flight, etc). Fall through
        // to the polling path so we surface the flip when it lands.
      } catch (exc) {
        if (cancelled) return;
        // Reconcile itself failed (502, network, auth). Show a
        // friendly retry — user's card may still have been charged
        // and the webhook will flip the invoice in the background.
        setErrMsg(exc?.detail || exc?.message || "Reconcile failed");
        setStatus("error");
        return;
      }

      // Phase 2 — polling fallback. Up to 60s @ 5s cadence per the
      // Stripe reconcile ship spec.
      let tries = 0;
      const MAX_TRIES = 12;
      while (!cancelled && tries < MAX_TRIES) {
        try {
          const r = await api.get(
            `/payments/status/${encodeURIComponent(sid)}`,
          );
          if (r?.status === "paid") {
            if (!cancelled) {
              setStatus("paid");
              if (r.invoice_id) loadInvoice(r.invoice_id);
            }
            return;
          }
        } catch { /* transient — keep polling */ }
        await new Promise((res) => setTimeout(res, 5000));
        tries++;
      }
      if (!cancelled) setStatus("pending");
    })();

    return () => { cancelled = true; };
  }, [sid, retryKey]);

  // Priority 3 · Feb 2026 — CTA handler. Idempotent server-side, so
  // a double-tap resolves cleanly. On success we swap the CTA for
  // a small confirmation so the customer sees positive feedback
  // without leaving the payment-complete screen.
  const handleEnableAutobilling = async () => {
    setAutobillingBusy(true);
    try {
      await api.post("/customer-portal/autobilling/enable", {});
      setAutobillingResult("enabled");
      setShowAutobillingCta(false);
    } catch (exc) {
      setAutobillingResult(
        exc?.detail === "no_default_payment_method"
          ? "no_pm"
          : "error",
      );
    } finally {
      setAutobillingBusy(false);
    }
  };

  const handleDismissAutobilling = () => {
    setShowAutobillingCta(false);
    setAutobillingResult("dismissed");
  };

  return (
    <PortalPageShell>
    <div className="max-w-md mx-auto px-4 sm:px-6 lg:px-8 py-10 text-center" data-testid="portal-pay-complete">
      {status === "checking" ? (
        <div data-testid="pc-checking">
          <Skeleton style={{ height: 120 }} />
        </div>
      ) : status === "paid" ? (
        <div data-testid="pc-paid">
          <div className="w-16 h-16 mx-auto rounded-full flex items-center justify-center"
            style={{ backgroundColor: colors.success + "20", color: colors.success }}>
            <Check size={28} />
          </div>
          <h1 className="text-2xl font-bold mt-4" style={{ color: colors.onSurface }}>Payment confirmed</h1>
          {invoice ? (
            <p className="text-sm mt-2" style={{ color: colors.muted }}>
              {invoice.title} · {money(invoice.total)}
            </p>
          ) : null}

          {/* Priority 3 · Feb 2026 — autobilling opt-in CTA. Shows
              only when the reconcile response confirmed a saved PM
              AND the customer isn't already opted in. Idempotent
              server-side; a successful click swaps the card for a
              small success confirmation so the user gets positive
              feedback without leaving the completion screen. */}
          {showAutobillingCta ? (
            <div
              className="mt-6 rounded-2xl p-5 text-left"
              style={{
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="autobilling-cta"
            >
              <h2
                className="text-base font-bold"
                style={{ color: colors.onSurface }}
                data-testid="autobilling-cta-title"
              >
                Never miss a payment
              </h2>
              <p
                className="text-sm mt-1"
                style={{ color: colors.muted }}
                data-testid="autobilling-cta-body"
              >
                Enable autobilling to charge future invoices to this saved payment method automatically.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  onClick={handleEnableAutobilling}
                  disabled={autobillingBusy}
                  testid="autobilling-cta-enable"
                >
                  {autobillingBusy ? "Enabling…" : "Enable autobilling"}
                </Button>
                <Button
                  variant="ghost"
                  onClick={handleDismissAutobilling}
                  disabled={autobillingBusy}
                  testid="autobilling-cta-dismiss"
                >
                  Not now
                </Button>
              </div>
            </div>
          ) : null}

          {autobillingResult === "enabled" ? (
            <div
              className="mt-6 rounded-xl px-4 py-3 text-sm text-left inline-flex items-center gap-2"
              style={{
                backgroundColor: colors.success + "15",
                color: colors.success,
                border: `1px solid ${colors.success}40`,
              }}
              data-testid="autobilling-enabled-banner"
            >
              <Check size={16} />
              <span>Autobilling is on. Future invoices will charge automatically.</span>
            </div>
          ) : null}
          {autobillingResult === "no_pm" ? (
            <div
              className="mt-6 rounded-xl px-4 py-3 text-sm text-left"
              style={{
                backgroundColor: "#FEF9C3",
                color: "#A16207",
                border: `1px solid #FDE68A`,
              }}
              data-testid="autobilling-nopm-banner"
            >
              We couldn't find a saved payment method. Add a card or bank first, then re-enable autobilling from Payment methods.
            </div>
          ) : null}
          {autobillingResult === "error" ? (
            <div
              className="mt-6 rounded-xl px-4 py-3 text-sm text-left"
              style={{
                backgroundColor: "#FEE2E2",
                color: "#B91C1C",
                border: `1px solid #FCA5A5`,
              }}
              data-testid="autobilling-error-banner"
            >
              We couldn't enable autobilling. Try again from your Payment methods page.
            </div>
          ) : null}

          <Button className="mt-6" onClick={() => navigate("/portal/invoices")} testid="pc-back">
            Back to invoices
          </Button>
        </div>
      ) : status === "error" ? (
        <div data-testid="pc-error">
          <div className="w-16 h-16 mx-auto rounded-full flex items-center justify-center"
            style={{ backgroundColor: "#FEE2E2", color: "#B91C1C" }}>
            <XIcon size={28} />
          </div>
          <h1 className="text-2xl font-bold mt-4" style={{ color: colors.onSurface }}>Something went wrong</h1>
          <p className="text-sm mt-2" style={{ color: colors.muted }}>
            Your card may still have been charged — we'll retry in the background.
          </p>
          <p className="text-xs mt-2" style={{ color: colors.muted }} data-testid="pc-error-id">
            Ref: {sid?.slice(-12) || "unknown"}
          </p>
          <Button className="mt-6" onClick={() => setRetryKey((k) => k + 1)}
                    testid="pc-retry">
            Try again
          </Button>
        </div>
      ) : (
        <div data-testid="pc-pending">
          <div className="w-16 h-16 mx-auto rounded-full flex items-center justify-center"
            style={{ backgroundColor: "#FEF9C3", color: "#A16207" }}>
            <XIcon size={28} />
          </div>
          <h1 className="text-2xl font-bold mt-4" style={{ color: colors.onSurface }}>Still processing</h1>
          <p className="text-sm mt-2" style={{ color: colors.muted }}>
            Your payment may still be finishing. Check invoices in a minute.
          </p>
          <Button className="mt-6" onClick={() => navigate("/portal/invoices")}>Back to invoices</Button>
        </div>
      )}
    </div>
      </PortalPageShell>
  );
}
