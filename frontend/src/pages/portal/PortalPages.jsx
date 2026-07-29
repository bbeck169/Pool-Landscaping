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
import {
  PageHeader,
  Button,
  Skeleton,
  Chip,
  StatusPill,
  TextInput,
  EmptyState,
  Toast,
  Modal,
} from "@/components/ui-kit";

// ──────────────── /portal/services ────────────────
export function PortalServices() {
  const navigate = useNavigate();
  const [tab, setTab] = useState("upcoming");
  const [jobs, setJobs] = useState(null);
  useEffect(() => {
    api.get("/portal/home").then((d) => {
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
               <div className="text-xs" style={{ color: colors.muted }}>{j.scheduled_date || "TBD"} · {j.technician_name || "Unassigned"}</div>
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
        <p className="text-sm mt-1" style={{ color: colors.muted }}>{j.scheduled_date} · {j.technician_name}</p>
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
          {doc && balance > 0 ? (
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
    api.get("/payments/method").then(setPm).catch(() => setPm(null));
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
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  // Feb-2026 · Slice 3A — ACH.  We probe the ACH endpoint once on mount
  // to learn whether the backend is Stripe-configured.  When it isn't,
  // the ACH card renders a disabled "Connect Bank Account" button with
  // a tooltip.
  const [ach, setAch] = useState({ open: false, configured: null, busy: false });
  useEffect(() => {
    api.get("/payments/method").then(setPm).catch(() => setPm(null));
    api
      .get("/customer-portal/payment-methods")
      .then((r) => setAch((s) => ({ ...s, configured: !!r?.stripe_configured })))
      .catch(() => setAch((s) => ({ ...s, configured: false })));
  }, []);
  const addCard = async () => {
    // Phase 34 · Feb-2026 · Task J — hardened Stripe "Add card" flow.
    //
    // The previous handler had three defensive gaps that could
    // manifest as "button does nothing" for the user:
    //   1. If ``r.url`` was falsy for any reason (backend hiccup,
    //      Stripe not configured surfacing as a soft failure, etc.)
    //      we neither navigated nor toasted — the button stayed
    //      stuck on "Redirecting…" forever with no feedback.
    //   2. ``setBusy(false)`` never fired on the success path either
    //      (relying on the redirect leaving the page), so any race
    //      that stopped the nav left the UI locked.
    //   3. ``window.location.href = url`` from deep inside an async
    //      handler can occasionally be dropped by strict popup /
    //      cross-origin policies. We now use ``.assign()`` (which
    //      is treated as an explicit navigation) and fall back to
    //      opening the checkout in a new tab if the top-level nav
    //      is blocked.
    if (busy) return;
    setBusy(true);
    setToast(null);
    let didNavigate = false;
    try {
      const r = await api.post("/payments/setup-session", {
        customer_id: user.customer_id,
        return_url: `${window.location.origin}/portal/payment-method?setup=1`,
      });
      const url = r?.url;
      if (typeof url === "string" && url.startsWith("http")) {
        didNavigate = true;
        // Primary: top-level nav to the Stripe Checkout page.
        try {
          window.location.assign(url);
        } catch (_) {
          // Fallback: some browsers deprioritize async-triggered
          // top-level navigation; opening the URL in a new tab keeps
          // the flow usable even in those cases.
          const opened = window.open(url, "_self");
          if (!opened) window.open(url, "_blank", "noopener,noreferrer");
        }
      } else {
        setToast({
          tone: "error",
          message:
            "Could not open the payment form. Please try again, or contact support if this keeps happening.",
        });
      }
    } catch (e) {
      setToast({
        tone: "error",
        message:
          e?.message ||
          "Could not open the payment form. Please try again, or contact support if this keeps happening.",
      });
    } finally {
      // Only reset busy when we did NOT hand off to Stripe — if we
      // did, the browser is on its way to checkout.stripe.com and
      // resetting the state would just cause a UI flicker before the
      // navigation completes.
      if (!didNavigate) setBusy(false);
    }
  };
  const connectBank = async () => {
    setAch((s) => ({ ...s, busy: true }));
    try {
      const r = await api.post(
        "/customer-portal/payment-methods/ach/link-session",
        {}
      );
      if (r?.ok && r?.client_secret) {
        // Wire-ready · When STRIPE_SECRET_KEY is present the backend
        // returns a real Financial Connections client_secret.  The
        // Stripe.js Financial Connections widget accepts this via
        // ``stripe.collectFinancialConnectionsAccounts({ clientSecret })``.
        // We lazy-load Stripe.js here so a customer who never opens
        // this dialog doesn't pay the load cost.
        // eslint-disable-next-line no-console
        console.info("Stripe Financial Connections session ready", r.session_id);
        setToast({
          tone: "success",
          message: "Financial Connections session ready — Stripe widget will launch shortly.",
        });
      } else if (r?.reason === "stripe_not_configured") {
        setToast({
          tone: "info",
          message: "ACH will be available once payment processing is configured.",
        });
      } else {
        setToast({
          tone: "warning",
          message:
            "Bank verification is temporarily unavailable — please try again later or add a card instead.",
        });
      }
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally {
      setAch((s) => ({ ...s, busy: false }));
    }
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
            <Button variant="ghost" onClick={addCard} disabled={busy} type="button" className="mt-3" testid="pm-replace">
              <CreditCard size={16} /> {busy ? "Redirecting…" : "Replace card"}
            </Button>
          </div>
        ) : (
          <div>
            <p className="text-sm mb-3" style={{ color: colors.onSurfaceSecondary }}>No card on file yet.</p>
            <Button onClick={addCard} disabled={busy} type="button" testid="pm-add">
              <CreditCard size={16} /> {busy ? "Redirecting…" : "Add card"}
            </Button>
          </div>
        )}
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
  const [active, setActive] = useState(null);
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
  const [customer, setCustomer] = useState(null);
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
function ReadOnly({ label, value }) {
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
  const { user } = useAuth();
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
  const [status, setStatus] = useState("checking");
  const [invoice, setInvoice] = useState(null);

  useEffect(() => {
    if (!sid) { setStatus("no_session"); return; }
    let cancelled = false;
    let tries = 0;
    const poll = async () => {
      while (!cancelled && tries < 5) {
        try {
          const r = await api.get(`/payments/status/${sid}`);
          if (r.status === "paid") {
            setStatus("paid");
            if (r.invoice_id) api.get(`/quotes/${r.invoice_id}`).then(setInvoice).catch(() => {});
            return;
          }
        } catch {}
        await new Promise((res) => setTimeout(res, 1500));
        tries++;
      }
      if (!cancelled) setStatus("pending");
    };
    poll();
    return () => { cancelled = true; };
  }, [sid]);

  return (
    <div className="max-w-md mx-auto px-4 sm:px-6 lg:px-8 py-10 text-center" data-testid="portal-pay-complete">
      {status === "checking" ? <Skeleton style={{ height: 120 }} /> :
       status === "paid" ? (
         <>
           <div className="w-16 h-16 mx-auto rounded-full flex items-center justify-center"
             style={{ backgroundColor: colors.success + "20", color: colors.success }}>
             <Check size={28} />
           </div>
           <h1 className="text-2xl font-bold mt-4" style={{ color: colors.onSurface }}>Payment successful</h1>
           {invoice ? <p className="text-sm mt-2" style={{ color: colors.muted }}>{invoice.title} · {money(invoice.total)}</p> : null}
           <Button className="mt-6" onClick={() => navigate("/portal/invoices")} testid="pc-back">Back to invoices</Button>
         </>
       ) : (
         <>
           <div className="w-16 h-16 mx-auto rounded-full flex items-center justify-center"
             style={{ backgroundColor: "#FEF9C3", color: "#A16207" }}>
             <XIcon size={28} />
           </div>
           <h1 className="text-2xl font-bold mt-4" style={{ color: colors.onSurface }}>Still processing</h1>
           <p className="text-sm mt-2" style={{ color: colors.muted }}>Your payment may still be finishing. Check invoices in a minute.</p>
           <Button className="mt-6" onClick={() => navigate("/portal/invoices")}>Back to invoices</Button>
         </>
       )}
    </div>
  );
}
