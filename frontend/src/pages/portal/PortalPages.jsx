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
  Landmark,
  Lock,
} from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { useAuth } from "@/auth";
import InvoiceView from "@/components/InvoiceView";
import EstimateView from "@/components/EstimateView";
import PortalBookingPhotos from "@/components/portal/PortalBookingPhotos";
// Phase 5A hot-fix · Feb 2026 — replace the legacy hosted-checkout
// redirect with the Phase 4B <PaymentForm> modal (Card + ACH + wallets).
import PaymentForm from "@/components/PaymentForm";
// Feb-2026 P0 fix (Bug 2 · Item A) — the previous portal Add-card
// flow POSTed to ``/payments/setup-session`` (a hosted-checkout
// endpoint that doesn't exist on this deployment) and GET
// ``/payments/method`` (also 404). We now use the shared inline
// SetupIntent + Elements form the sibling ``PortalPaymentMethods``
// page uses. Same identity invariant: customer_id derives from
// the JWT server-side, never from a URL param.
import StripeAddCardForm from "@/components/payments/StripeAddCardForm";
// Feb 2026 · P0 fix — Stripe Elements ACH bank-account capture form.
// Replaces the previous log-only "Connect Bank Account" branch that
// never mounted <Elements>, leaving every customer stuck at the
// "widget will launch shortly" toast.
import StripeAddBankForm from "@/components/payments/StripeAddBankForm";
import { getStripeConfig } from "@/lib/stripeConfig";
// Phase 30 · Feb-2026 — shared TechAvatar for tech identity chips.
import TechAvatar from "@/components/common/TechAvatar";
import { PageHeader, Button, Skeleton, Chip, StatusPill, TextInput, EmptyState, Toast } from "@/components/ui-kit";

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
  );
}

export function PortalServiceDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [j, setJ] = useState(null);
  useEffect(() => { api.get(`/jobs/${id}`).then(setJ).catch(() => {}); }, [id]);
  if (!j) return <div className="max-w-3xl mx-auto p-6"><Skeleton style={{ height: 200 }} /></div>;
  return (
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
              <img key={i} src={p.url || p.data_url || p} alt="" className="w-full aspect-square object-cover rounded-lg"
                style={{ border: `1px solid ${colors.border}` }} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
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
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-invoices" data-tour-id="invoices-list">
      <PageHeader title="My Invoices" subtitle="Pay online, download receipts." />
      <div className="rounded-2xl p-5 mb-4" style={{ background: "linear-gradient(90deg, #0284C7, #16A34A)", color: "#fff" }}>
        <div className="text-sm opacity-85">Total outstanding</div>
        <div className="text-3xl font-bold mt-1" data-testid="port-outstanding">{money(total)}</div>
      </div>
      {rows === null ? <Skeleton style={{ height: 220 }} /> :
       rows.length === 0 ? <EmptyState icon={FileText} title="No invoices yet" /> :
       <ul className="space-y-2">
         {rows.map((r) => {
           const balance = Math.max(0, Number(r.total || 0) - Number(r.amount_paid || 0));
           return (
             <li key={r.id} onClick={() => navigate(`/portal/invoices/${r.id}`)}
               className="cursor-pointer flex items-center gap-3 p-4 rounded-xl"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid={`port-inv-${r.id}`}>
               <div className="flex-1 min-w-0">
                 <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{r.title}</div>
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
  );
}

export function PortalInvoiceDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const printable = params.get("format") === "printable";
  const [doc, setDoc] = useState(null);
  const [toast, setToast] = useState(null);
  // Phase 5A hot-fix · Feb 2026 — Portal Pay Now now uses the Phase 4B
  // <PaymentForm> (Card + ACH + wallets). The legacy
  // /api/payments/checkout/{id} endpoint returned "Stripe not
  // configured" whenever the older Phase-53 SDK path hit an exception.
  const [payNowOpen, setPayNowOpen] = useState(false);
  useEffect(() => { api.get(`/quotes/${id}`).then(setDoc).catch(() => {}); }, [id]);

  const balance = doc
    ? Math.max(0, Number(doc.total || 0) - Number(doc.amount_paid || 0))
    : 0;

  return (
    <div
      className={printable ? "" : "max-w-4xl mx-auto px-2 sm:px-4 lg:px-6 py-4"}
      data-testid="portal-inv-detail"
    >
      {!printable ? (
        <div className="max-w-4xl mx-auto flex items-center justify-between mb-3 px-2">
          <button
            onClick={() => navigate("/portal/invoices")}
            className="flex items-center gap-1 text-sm font-semibold"
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
              the ``InvoiceView.canPay`` gate one level deeper. */}
          {doc && balance > 0
              && (doc?.payment_status || "").toLowerCase() !== "paid" ? (
            <Button onClick={() => setPayNowOpen(true)} testid="port-pay">
              <CreditCard size={16} /> {`Pay ${money(balance)}`}
            </Button>
          ) : null}
        </div>
      ) : null}
      <InvoiceView invoiceId={id} printable={printable} />
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
  );
}

// ──────────────── /portal/estimates ────────────────
export function PortalEstimates() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/quotes?doc_type=quote").then(setRows).catch(() => setRows([])); }, []);
  return (
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
  );
}

export function PortalEstimateDetail() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const printable = params.get("format") === "printable";
  const [toast, setToast] = useState(null);
  return (
    <div
      className={printable ? "" : "max-w-4xl mx-auto px-2 sm:px-4 lg:px-6 py-4"}
      data-testid="portal-est-detail"
    >
      <EstimateView estimateId={id} isAdmin={false} printable={printable} />
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
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
  );
}

export function PortalPaymentMethod() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [pm, setPm] = useState(null);
  // Feb-2026 P0 fix (Bug 2 · Item A) — the previous "Add card" flow
  // used ``busy`` state to gate a Stripe Checkout redirect. The
  // inline SetupIntent + Elements form now owns its own busy
  // state internally, so we no longer need a top-level one.
  const [toast, setToast] = useState(null);
  // Feb-2026 P0 fix (Bug 2 · Item A) — inline Stripe Elements Add-card
  // form replaces the previous hosted-checkout redirect. The
  // ``showAddCard`` toggle controls the form panel; on success we
  // refresh the card-on-file summary and hide the form. Publishable
  // key + auth token are read the same way the sibling
  // ``PortalPaymentMethods`` page reads them.
  const [showAddCard, setShowAddCard] = useState(false);
  // Feb 2026 · P0 fix — ACH counterpart of ``showAddCard``. Flips
  // true when the customer clicks "Connect Bank Account" and Stripe
  // is configured; mounts the ``StripeAddBankForm`` inline instead
  // of the previous log-only branch.
  const [showAddBank, setShowAddBank] = useState(false);
  const [pubKey, setPubKey] = useState("");
  const _authToken = typeof window !== "undefined"
    ? window.localStorage.getItem("token") : "";
  const _apiBase = `${process.env.REACT_APP_BACKEND_URL}/api`;
  // Feb-2026 · Slice 3A — ACH.  We probe the ACH endpoint once on mount
  // to learn whether the backend is Stripe-configured.  When it isn't,
  // the ACH card renders a disabled "Connect Bank Account" button with
  // a tooltip.
  const [ach, setAch] = useState({ open: false, configured: null, busy: false });

  // Feb-2026 P0 fix (Bug 2 · Item A) — shared loader so the "card on
  // file" chip refreshes after a successful Add-card, without a full
  // page reload.
  const loadPm = React.useCallback(() => {
    api
      .get("/customer-portal/payment-methods")
      .then((r) => {
        const list = Array.isArray(r?.methods) ? r.methods : [];
        const chosen = list.find((m) => m?.is_default) || list[0] || null;
        setPm(chosen);
        setAch((s) => ({ ...s, configured: !!r?.stripe_configured }));
      })
      .catch(() => {
        setPm(null);
        setAch((s) => ({ ...s, configured: false }));
      });
  }, []);

  useEffect(() => {
    loadPm();
    getStripeConfig()
      .then((c) => setPubKey(c?.publishable_key || ""))
      .catch(() => setPubKey(""));
  }, [loadPm]);

  const addCard = () => {
    // Feb-2026 P0 fix (Bug 2 · Item A) — opens the inline SetupIntent
    // + Elements form. Never redirects, never POSTs to the missing
    // ``/payments/setup-session`` endpoint, never constructs a URL
    // with ``/undefined``. The SetupIntent endpoint (``POST
    // /api/payments/stripe/setup-intent``) derives ``customer_id``
    // from the JWT server-side.
    setToast(null);
    setShowAddCard(true);
  };
  const onAddCardSuccess = () => {
    setShowAddCard(false);
    setToast({ tone: "success", message: "Card saved." });
    loadPm();
  };
  const connectBank = () => {
    // Feb 2026 · P0 fix — mount the inline ACH form instead of the
    // previous log-only stub. The form fetches the SetupIntent from
    // ``/customer-portal/payment-methods/ach/link-session`` and
    // drives Stripe's ``<PaymentElement>`` for the us_bank_account
    // flow. Success handler refreshes the payment-methods summary
    // and closes the panel.
    setToast(null);
    setShowAddBank(true);
  };
  const onAddBankSuccess = () => {
    setShowAddBank(false);
    setToast({ tone: "success", message: "Bank account saved." });
    loadPm();
  };
  const stripeReady = ach.configured === true;
  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-pm" data-tour-id="payment-method-panel">
      <button onClick={() => navigate("/portal/payments")} className="flex items-center gap-1 text-sm font-semibold mb-4" style={{ color: colors.muted }}>
        <ArrowLeft size={14} /> Payments
      </button>
      <PageHeader title="Payment Methods" subtitle="Save a card or connect a bank account so admin can charge you for approved services without another checkout." />
      {/* Credit card block — unchanged flow */}
      <div className="rounded-2xl p-6 mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }} data-testid="pm-card-block">
        <div className="flex items-center gap-2 mb-3" style={{ color: colors.brand }}>
          <CreditCard size={18} />
          <div className="text-sm font-bold uppercase tracking-wider" style={{ color: colors.onSurface }}>
            Credit / Debit Card
          </div>
        </div>
        {pm?.brand ? (
          <div>
            <div className="text-lg font-semibold" style={{ color: colors.onSurface }}>
              {pm.brand} · •••• {pm.last4}
            </div>
            <div className="text-sm mt-1" style={{ color: colors.muted }}>Saved · expires {pm.exp_month}/{pm.exp_year}</div>
            <Button variant="ghost" onClick={addCard} disabled={showAddCard} type="button" className="mt-3" testid="pm-replace">
              <CreditCard size={16} /> {showAddCard ? "Adding…" : "Replace card"}
            </Button>
          </div>
        ) : (
          <div>
            <p className="text-sm mb-3" style={{ color: colors.onSurfaceSecondary }}>No card on file yet.</p>
            <Button onClick={addCard} disabled={showAddCard} type="button" testid="pm-add">
              <CreditCard size={16} /> {showAddCard ? "Adding…" : "Add card"}
            </Button>
          </div>
        )}
        {/* Feb-2026 P0 fix (Bug 2 · Item A) — inline Stripe Elements
            form. Renders only when the user has clicked Add/Replace.
            Reads ``customer_id`` from the JWT server-side (the
            component posts no explicit id for portal customers). */}
        {showAddCard ? (
          <div className="mt-4" data-testid="pm-add-card-form">
            <StripeAddCardForm
              apiBase={_apiBase}
              authToken={_authToken}
              customerId={user?.customer_id}
              publishableKey={pubKey}
              onSuccess={onAddCardSuccess}
              onCancel={() => setShowAddCard(false)}
              title="Add a card"
            />
          </div>
        ) : null}
        {toast?.tone === "success" ? (
          <div
            className="mt-3 text-sm rounded-md px-3 py-2"
            style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
            data-testid="pm-toast"
          >
            {toast.message}
          </div>
        ) : null}
      </div>

      {/* Feb-2026 · Slice 3A — ACH bank account (Stripe Financial
          Connections). Wire-ready: when the backend reports Stripe
          is not configured (missing key or placeholder-shaped key),
          both the outer "Add ACH" button and the inner "Connect Bank
          Account" button render disabled with a "Coming soon" tooltip. */}
      <div
        className="rounded-2xl p-6"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="pm-ach-block"
      >
        <div className="flex items-center gap-2 mb-3" style={{ color: colors.success }}>
          <Landmark size={18} />
          <div
            className="text-sm font-bold uppercase tracking-wider"
            style={{ color: colors.onSurface }}
          >
            Bank Account (ACH)
          </div>
        </div>
        {!ach.open ? (
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <p
              className="text-sm max-w-md"
              style={{ color: colors.onSurfaceSecondary }}
            >
              {stripeReady
                ? "Link a bank account for lower-fee ACH payments. Instant bank verification via Stripe Financial Connections — no routing/account numbers to type."
                : "Instant bank verification via Stripe · Coming soon. This will let you link a bank account for lower-fee ACH payments once payment processing is configured."}
            </p>
            <button
              onClick={() => setAch((s) => ({ ...s, open: true }))}
              disabled={!stripeReady}
              title={
                stripeReady
                  ? "Add a bank account via Stripe Financial Connections"
                  : "Coming soon — ACH will be available once payment processing is configured."
              }
              className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                backgroundColor: stripeReady ? colors.surfaceSecondary : "#F1F5F9",
                color: stripeReady ? colors.onSurface : colors.muted,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="add-ach-btn"
              data-stripe-ready={stripeReady ? "1" : "0"}
            >
              <Plus size={16} /> {stripeReady ? "Add ACH" : "Add ACH · Coming soon"}
            </button>
          </div>
        ) : showAddBank ? (
          /* Feb 2026 · P0 fix — inline Stripe Elements ACH form.
             Replaces the previous log-only branch that never
             mounted <Elements>. */
          <div data-testid="pm-ach-add-panel">
            <StripeAddBankForm
              apiBase={_apiBase}
              authToken={_authToken}
              publishableKey={pubKey}
              onSuccess={onAddBankSuccess}
              onCancel={() => setShowAddBank(false)}
            />
          </div>
        ) : (
          <div>
            <div
              className="rounded-xl p-4 mb-3"
              style={{
                backgroundColor: colors.surfaceSecondary,
                border: `1px solid ${colors.divider}`,
              }}
            >
              <div className="flex items-start gap-3">
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                  style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
                >
                  <Lock size={16} />
                </div>
                <div className="min-w-0">
                  <div
                    className="text-sm font-semibold"
                    style={{ color: colors.onSurface }}
                  >
                    Instant bank verification via Stripe Financial Connections
                  </div>
                  <div
                    className="text-xs mt-1"
                    style={{ color: colors.onSurfaceSecondary }}
                  >
                    You'll be prompted to log into your bank securely.
                    We never see or store your credentials. Financial
                    Connections is verification only — no money moves
                    until you approve a specific charge.
                  </div>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={connectBank}
                disabled={!stripeReady || ach.busy}
                title={
                  !stripeReady
                    ? "ACH will be available once payment processing is configured."
                    : "Launch Stripe Financial Connections"
                }
                className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50 disabled:cursor-not-allowed"
                style={{
                  background: stripeReady ? colors.success : colors.muted,
                }}
                data-testid="ach-connect-btn"
                data-stripe-ready={stripeReady ? "1" : "0"}
              >
                {ach.busy ? "Opening…" : "Connect Bank Account"}
              </button>
              <Button
                variant="ghost"
                onClick={() => setAch((s) => ({ ...s, open: false }))}
              >
                Cancel
              </Button>
              {ach.configured === false ? (
                <span
                  className="text-xs"
                  style={{ color: colors.warning }}
                  data-testid="ach-not-configured-hint"
                >
                  ACH will be available once payment processing is configured.
                </span>
              ) : null}
            </div>
          </div>
        )}
      </div>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

// ──────────────── /portal/documents ────────────────
export function PortalDocuments() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/me/documents").then(setRows).catch(() => setRows([])); }, []);
  return (
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
  );
}

// ──────────────── /portal/messages ────────────────
export function PortalMessages() {
  // Feb-2026 — the per-conversation AI sparkles toggle used to live
  // here (data-testid="msg-ai-toggle"). It has been removed from the
  // customer portal per product guardrail: no AI-adjacent UI on
  // customer-facing surfaces. Message text is now sent verbatim.
  const [threads, setThreads] = useState(null);
  const [_active, _setActive] = useState(null);
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
          className="flex-1 px-3 py-2 text-sm rounded-lg outline-none resize-none focus:ring-2"
          style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
          data-testid="msg-input" />
        <Button onClick={send} disabled={busy || !text.trim()} testid="msg-send"><Send size={14} /></Button>
      </div>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

// ──────────────── /portal/profile ────────────────
export function PortalProfile() {
  const { user, refreshMe } = useAuth();
  const [_customer, setCustomer] = useState(null);
  const [form, setForm] = useState({ first_name: "", last_name: "", email: "", phone: "", address: "" });
  const [initial, setInitial] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    // Phase 34 · Task N — load the customer's current profile from
    // /me so we start with the freshest linked values.
    api.get(`/me`)
      .then((c) => {
        setCustomer(c);
        const nx = {
          first_name: c?.first_name || (user?.name || "").split(" ")[0] || "",
          last_name: c?.last_name || (user?.name || "").split(" ").slice(1).join(" ") || "",
          email: c?.email || user?.email || "",
          phone: c?.phone || "",
          address: c?.address || "",
        };
        setForm(nx);
        setInitial(JSON.stringify(nx));
      })
      .catch(() => {});
  }, [user]);

  const dirty = initial && JSON.stringify(form) !== initial;
  const valid = (
    form.first_name.trim() &&
    form.email.trim() && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email) &&
    ("" + form.phone).replace(/\D/g, "").length >= 10 &&
    form.address.trim().length >= 5
  );
  const canSave = dirty && valid && !saving;

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async (e) => {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true); setError("");
    try {
      const resp = await api.patch("/customer-portal/profile", form);
      setToast({ tone: "success", message: "Profile updated" });
      // Snapshot the saved values so the form becomes clean again.
      setInitial(JSON.stringify(form));
      // Refresh cached user context so the header / other surfaces
      // pick up the new name/email.
      try { await refreshMe?.(); } catch (_) { /* best-effort */ }
      setCustomer((c) => ({ ...(c || {}), ...(resp?.profile || {}) }));
    } catch (err) {
      setError(err?.message || "Could not save. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const cancel = () => {
    if (!initial) return;
    setForm(JSON.parse(initial));
    setError("");
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
  );
}
function _ReadOnly({ label, value }) {
  return (
    <div className="mb-2">
      <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>{label}</div>
      <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{value || "—"}</div>
    </div>
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
            className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
            style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
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
  );
}
