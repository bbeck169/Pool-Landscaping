import React, { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import {
  Waves,
  Calendar,
  Wrench,
  Receipt,
  FileText,
  MessageSquare,
  ChevronRight,
  AlertCircle,
  Plus,
  Shield,
  ClipboardCheck,
  DollarSign,
  CalendarClock,
  Wallet,
  X as XIcon,
  Send,
  Sparkles,
  UserRound,
  Star,
} from "lucide-react";
import { api } from "@/api";
import { brandGradientCss, colors } from '@/theme';
import { useAuth } from "@/auth";
import GreetingTile from "@/components/customer/GreetingTile";
import BusinessCard from "@/components/business-card/BusinessCard";
import { Skeleton, StatusPill } from '@/components/ui-kit';
import PortalWalkthrough from "@/pages/portal/PortalWalkthrough";
import CallNowButton from "@/pages/portal/CallNowButton";
import ReferralSection from "@/pages/portal/ReferralSection";
import MyReferralsSection from "@/pages/portal/MyReferralsSection";

const money = (n) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" })
    .format(Number(n || 0));

const fmtServiceDate = (iso) => {
  if (!iso) return "";
  try {
    const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
    return d.toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  } catch {
    return String(iso).slice(0, 10);
  }
};

export default function PortalHome() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [tosStatus, setTosStatus] = useState(null);
  const [summary, setSummary] = useState(null);
  // Feb-2026 · Slice 3D — Quick service-request modal.
  const [requestOpen, setRequestOpen] = useState(false);
  // Feb-2026 · Slice 5 — customer AI carve-out (Skedra + Billy).
  const [aiEmployees, setAiEmployees] = useState([]);
  const [aiChat, setAiChat] = useState(null);   // { employee } or null

  const loadSummary = () =>
    api.get("/customer-portal/summary").then(setSummary).catch(() => setSummary(null));

  useEffect(() => {
    api.get("/portal/home").then(setData).catch(() => setData({ counts: {} }));
    api.get("/portal/terms/status").then(setTosStatus).catch(() => {});
    loadSummary();
    // Feb-2026 · Slice 5 — pull the two customer-audience AI
    // employees so the "Ask AI" section can render their cards.
    api
      .get("/customer-portal/ai-employees")
      .then((rows) => setAiEmployees(Array.isArray(rows) ? rows : []))
      .catch(() => setAiEmployees([]));
    // Feb-2026 · Slice 3B — refresh the tiles when the tab regains focus
    // so a customer who paid an invoice in another tab sees the new
    // Balance Due without a full reload.
    const onVis = () => {
      if (document.visibilityState === "visible") loadSummary();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  if (user && user.role !== "customer") return <Navigate to="/" replace />;
  const first = user?.name?.split(" ")[0] || "there";

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-home">
      {/* Feb-2026 · Item 9 — first thing the customer sees.
          Phase 34 · Feb 2026 · surgical removal — the "Good evening,
          {name}!" greeting tile (blue→green gradient + Contact us /
          Book service buttons) has been removed at the user's request.
          The GreetingTile component + import are left in place in the
          codebase so nothing else that references them breaks; only
          the JSX render call was deleted from PortalHome. */}
      {/* <GreetingTile /> */}

      {/* Phase 34 · Feb 2026 · Task K — top CTA row. Call Now + Request
          Service now sit as the FIRST row of the content area, above the
          hero card. Side-by-side on ≥sm, stacked full-width on narrow
          mobile. Same click handlers as before — the two buttons were
          previously scattered further down the page (Call Now above the
          quick actions, Request Service after the ToS banner). We render
          them here now and remove those old inline instances below so
          they're not duplicated. */}
      <div
        className="mb-4 flex flex-col sm:flex-row gap-3 md:gap-4"
        data-testid="portal-cta-row"
      >
        <div className="flex-1 min-w-0" data-testid="portal-cta-call">
          <CallNowButton />
        </div>
        <button
          onClick={() => setRequestOpen(true)}
          className="inline-flex items-center justify-center gap-2 flex-1 min-w-0 px-4 py-3 rounded-xl text-sm font-bold text-white shadow-sm hover:brightness-95"
          style={{ background: brandGradientCss, minHeight: 48 }}
          data-testid="portal-request-service-btn"
        >
          <Plus size={16} /> Request Service
        </button>
      </div>

      {/* Phase 34 · Feb 2026 — hero card relocated to the TOP of the
          Portal Home content area per user directive. It used to sit
          below the stat/alert cards + ToS banner + Call/Request
          buttons; now it renders first so customers land on their
          "Hi, {first} 👋 · next visit" greeting immediately. Content
          + styling unchanged — this is a pure DOM reorder. */}
      <div
        className="rounded-2xl p-6 md:p-8 mb-4 text-white relative overflow-hidden"
        style={{ background: brandGradientCss, minHeight: 180 }}
        data-testid="portal-hero"
        data-tour-id="next-service-visit"
      >
        <div
          className="absolute inset-0 opacity-25"
          style={{
            backgroundImage:
              "url(https://images.pexels.com/photos/261101/pexels-photo-261101.jpeg?auto=compress&cs=tinysrgb&w=1200)",
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        />
        <div className="relative">
          <p className="text-white/85 text-sm">Welcome back</p>
          <h1 className="text-3xl md:text-4xl font-bold mt-1">Hi, {first} 👋</h1>
          {data ? (
            data.next_visit ? (
              <div className="mt-4 bg-white/15 backdrop-blur rounded-xl p-4">
                <div className="text-xs uppercase tracking-widest opacity-80">Next visit</div>
                <div className="text-lg font-bold mt-0.5">{data.next_visit.title}</div>
                <div className="text-sm opacity-90 mt-1">
                  {data.next_visit.scheduled_date
                    ? new Date(data.next_visit.scheduled_date).toDateString()
                    : "TBD"}{" "}
                  · {data.next_visit.technician_name || "Unassigned"}
                </div>
              </div>
            ) : (
              <p className="text-white/85 mt-3 text-sm">No upcoming visits scheduled.</p>
            )
          ) : (
            <Skeleton style={{ height: 60, backgroundColor: "rgba(255,255,255,0.2)", marginTop: 12 }} />
          )}
        </div>
      </div>

      {/* Feb-2026 · Item 12 — status "circles" hoisted directly under
          the greeting tile. Two rows: primary account tiles
          (Balance/Past Due/Credit/Next Service) + optional alert
          tiles (Overdue/Estimates/Unread). No X-close buttons —
          these are status indicators, never dismissible.
          Also tags the block with ``data-tour-id="status-circles"``
          for the Item 10 tour highlight. */}
      <div data-tour-id="status-circles" data-testid="portal-status-circles">
        <div
          className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2"
          data-testid="portal-account-tiles"
        >
          <Tile
            testid="tile-balance-due"
            label="Balance Due"
            icon={DollarSign}
            value={summary ? money(summary.balance_due) : "—"}
            tooltip={
              summary
                ? `${summary.breakdown?.open_invoice_count || 0} open invoice(s) totaling ${money(summary.balance_due)}`
                : ""
            }
            onClick={() => navigate("/portal/invoices")}
          />
          <Tile
            testid="tile-past-due"
            label="Past Due"
            icon={AlertCircle}
            value={summary ? money(summary.past_due) : "—"}
            alert={(summary?.past_due || 0) > 0}
            tooltip={
              summary
                ? `${summary.breakdown?.past_due_invoice_count || 0} past-due invoice(s) totaling ${money(summary.past_due)}`
                : ""
            }
            onClick={() => navigate("/portal/invoices")}
          />
          <Tile
            testid="tile-credit"
            label="Credit"
            icon={Wallet}
            value={summary ? money(summary.credit) : "—"}
            tooltip={
              summary
                ? summary.credit > 0
                  ? `${money(summary.credit)} available credit — will apply to your next invoice.`
                  : "No prepayment credit on your account."
                : ""
            }
            onClick={() => navigate("/portal/payments")}
          />
          <Tile
            testid="tile-next-service"
            label="Next Service"
            icon={CalendarClock}
            value={
              summary?.next_service
                ? fmtServiceDate(summary.next_service.date)
                : "None scheduled"
            }
            sub={summary?.next_service?.service_type || ""}
            tooltip={
              summary?.next_service
                ? `${fmtServiceDate(summary.next_service.date)} · ${summary.next_service.service_type}`
                : "No upcoming service on the calendar."
            }
            onClick={() =>
              summary?.next_service?.job_id
                ? navigate(`/portal/services/${summary.next_service.job_id}`)
                : navigate("/portal/request-service")
            }
          />
        </div>
        {data ? (
          <div className="grid grid-cols-3 gap-2 mb-3">
            <AlertTile
              testid="alert-overdue"
              label="Overdue"
              value={data.counts.overdue_invoices || 0}
              tone={(data.counts.overdue_invoices || 0) > 0 ? colors.error : colors.muted}
              onClick={() => navigate("/portal/invoices")}
            />
            <AlertTile
              testid="alert-estimates"
              label="Pending estimates"
              value={data.counts.pending_estimates || 0}
              tone={(data.counts.pending_estimates || 0) > 0 ? "#A16207" : colors.muted}
              onClick={() => navigate("/portal/estimates")}
            />
            <AlertTile
              testid="alert-msgs"
              label="Unread messages"
              value={data.counts.unread_messages || 0}
              tone={(data.counts.unread_messages || 0) > 0 ? colors.brand : colors.muted}
              onClick={() => navigate("/portal/messages")}
            />
          </div>
        ) : null}
      </div>

      {tosStatus && !tosStatus.acknowledged && tosStatus.current_version ? (
        <div
          className="rounded-2xl p-4 mb-4 flex items-center gap-3 flex-wrap"
          style={{
            backgroundColor: "#FEF3C7",
            border: "1px solid #FCD34D",
          }}
          data-testid="tos-nudge-banner"
        >
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center shrink-0"
            style={{ backgroundColor: "#FDE68A", color: "#92400E" }}
          >
            <Shield size={18} />
          </div>
          <div className="flex-1 min-w-[200px]">
            <div className="text-sm font-semibold" style={{ color: "#92400E" }}>
              Please review our updated Terms of Service
            </div>
            <div className="text-xs mt-0.5" style={{ color: "#92400E", opacity: 0.85 }}>
              Version {tosStatus.current_version} · A quick read and acknowledgement keeps your service active.
            </div>
          </div>
          <button
            onClick={() => navigate("/portal/terms")}
            className="px-3 py-2 text-xs font-semibold rounded-lg hover:brightness-95"
            style={{ backgroundColor: "#B45309", color: "#fff" }}
            data-testid="tos-nudge-view"
          >
            View
          </button>
        </div>
      ) : null}

      {/* Phase 34 · Feb 2026 · Task K — the standalone Call Now button
          and Request Service CTA that used to live in this region have
          been moved to the top CTA row at the top of the page (see
          `data-testid="portal-cta-row"`). Physically deleted here to
          eliminate the duplicates the tester reported. */}

      {/* Alerts — Feb-2026 · Item 12 · moved into the status-circles
          block at the top of the page. The old copy here is retained
          intentionally empty to preserve the surrounding layout. */}
      {null}

      {/* Quick actions */}
      <div
        className="rounded-2xl p-5 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="text-xs uppercase font-semibold mb-3" style={{ color: colors.muted }}>
          Quick actions
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {/* Phase 34 · Task K de-dup — the "Request Service" tile that
              used to live here duplicated the top-row CTA. Removed. */}
          <ActionTile icon={ClipboardCheck} label="Service Reports" tone="#0891B2" onClick={() => navigate("/portal/service-reports")} testid="qa-service-reports" />
          <ActionTile icon={Receipt} label="Invoices" tone="#A16207" onClick={() => navigate("/portal/invoices")} testid="qa-invoices" />
          <ActionTile icon={FileText} label="Estimates" tone="#4338CA" onClick={() => navigate("/portal/estimates")} testid="qa-estimates" />
          <ActionTile icon={Wrench} label="Payment Method" tone={colors.success} onClick={() => navigate("/portal/payment-method")} testid="qa-pm" />
          <ActionTile icon={Star} label="Leave a Review" tone="#F59E0B" onClick={() => navigate("/portal/reviews")} testid="portal-reviews-tab" />
        </div>
      </div>

      {/* Phase 34 · Feb 2026 · reorder — "Ask a concierge" moved
          from bottom-of-page to sit directly ABOVE the "Refer a
          Friend" section per product request. Testids preserved
          (`portal-ai-section`, `portal-ai-<key>-card`) so existing
          e2e wiring keeps working. */}
      {aiEmployees.length > 0 ? (
        <div className="mt-5 mb-4" data-testid="portal-ai-section">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles size={16} style={{ color: colors.brand }} />
            <h2
              className="text-sm font-bold uppercase tracking-wider"
              style={{ color: colors.onSurface }}
            >
              Ask a concierge
            </h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {aiEmployees.map((emp) => (
              <button
                key={emp.id}
                onClick={() => setAiChat({ employee: emp })}
                className="text-left rounded-2xl p-4 transition hover:brightness-95 flex items-start gap-3"
                style={{
                  backgroundColor: colors.surface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid={`portal-ai-${emp.key}-card`}
              >
                <div
                  className="w-11 h-11 rounded-full flex items-center justify-center shrink-0 text-xl"
                  style={{
                    background:
                      emp.key === "billy"
                        ? "linear-gradient(135deg,#DCFCE7,#BBF7D0)"
                        : "linear-gradient(135deg,#DBEAFE,#BFDBFE)",
                    color:
                      emp.key === "billy" ? "#166534" : "#1E3A8A",
                  }}
                  aria-hidden="true"
                >
                  {emp.avatar_emoji || "🤖"}
                </div>
                <div className="min-w-0">
                  <div
                    className="text-sm font-bold truncate"
                    style={{ color: colors.onSurface }}
                  >
                    {emp.name}
                  </div>
                  <div
                    className="text-xs mt-0.5 truncate"
                    style={{ color: colors.muted }}
                  >
                    {emp.key === "billy"
                      ? "Ask about your balance, invoices, and payment history."
                      : "Ask about your visits, service history, and what's next."}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {/* Slice O2 · Refer a Friend section. */}
      <ReferralSection />
      {/* Slice O.2 · My Referrals — hides when list is empty. */}
      <MyReferralsSection />

      {/* Feb-2026 · Item 3/10 — Customer-facing business card. Tap
          to save the company contact / open NFC handoff. Tagged for
          the portal tour (step 4). */}
      <div className="mb-4 max-w-md" data-tour-id="business-card">
        <BusinessCard variant="compact" />
      </div>

      {/* Last visit */}
      {data?.last_visit ? (
        <div
          className="rounded-2xl p-5"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid="last-visit-card"
        >
          <div className="text-xs uppercase font-semibold mb-2" style={{ color: colors.muted }}>
            Last visit
          </div>
          <div className="flex items-start gap-3">
            <div
              className="w-11 h-11 rounded-xl flex items-center justify-center"
              style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}
            >
              <Waves size={18} />
            </div>
            <div className="flex-1">
              <div className="text-base font-semibold" style={{ color: colors.onSurface }}>{data.last_visit.title}</div>
              <div className="text-sm" style={{ color: colors.muted }}>
                {data.last_visit.scheduled_date} · {data.last_visit.technician_name || "—"}
              </div>
              <div className="mt-2"><StatusPill status={data.last_visit.status} /></div>
            </div>
            <button onClick={() => navigate(`/portal/services/${data.last_visit.id}`)}>
              <ChevronRight size={18} color={colors.muted} />
            </button>
          </div>
        </div>
      ) : null}

      {/* Feb-2026 · Slice J1 — the "Ask a concierge" AI Employees
          block used to render here at the bottom of the page.
          Phase 34 · Feb 2026 · reorder — it has been moved up to
          sit immediately above the "Refer a Friend" section. This
          slot is intentionally left empty so nothing below shifts. */}
      {null}

      {/* Feb-2026 · Slice 3D — Quick Request Service modal.
          only when the CTA is tapped.  Submits to the same endpoint
          as the full-page /portal/request-service route, so admins
          get the same message + bell + push regardless of entry. */}
      {requestOpen ? (
        <RequestServiceModal
          onClose={() => setRequestOpen(false)}
          onSent={() => {
            setRequestOpen(false);
            // Re-fetch the next-service tile so a new job that shows
            // up shortly after appears without a full reload.
            loadSummary();
          }}
        />
      ) : null}

      {/* Feb-2026 · Slice 5 — Customer AI chat pane (Skedra or Billy) */}
      {aiChat ? (
        <CustomerAiChatPane
          employee={aiChat.employee}
          onClose={() => setAiChat(null)}
        />
      ) : null}

      {/* Feb-2026 · Slice I — First-login walkthrough. Self-gates on
          the server-side ``portal_walkthrough_completed_at`` flag so
          returning customers never see it a second time. */}
      {/* Feb-2026 · Item 10 — Tour engine hoisted to AppLayout above
          so it survives navigation between portal pages. Remove the
          embedded copy here to avoid double-mount. */}
    </div>
  );
}

function AlertTile({ label, value, tone, onClick, testid }) {
  return (
    <button
      onClick={onClick}
      className="text-left rounded-2xl p-3 transition hover:brightness-95"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={testid}
    >
      <div className="flex items-center gap-1.5" style={{ color: tone }}>
        <AlertCircle size={13} />
        <span className="text-xs font-semibold">{label}</span>
      </div>
      <div className="text-2xl font-bold mt-1" style={{ color: colors.onSurface }}>{value}</div>
    </button>
  );
}

function ActionTile({ icon: Icon, label, tone, onClick, testid }) {
  return (
    <button
      onClick={onClick}
      className="rounded-xl p-4 text-left transition hover:brightness-95"
      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
      data-testid={testid}
    >
      <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-2" style={{ backgroundColor: tone + "20", color: tone }}>
        <Icon size={18} />
      </div>
      <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{label}</div>
    </button>
  );
}

// Feb-2026 · Slice 3B · Portal account tile.  Compact, single-row-of-4
// on md+, 2×2 on mobile.  ``alert=true`` swaps the border + label
// colour red (used by Past Due when > 0).
function Tile({ label, value, sub, icon: Icon, tone, alert, tooltip, onClick, testid }) {
  const borderColor = alert ? colors.error : colors.border;
  const labelColor = alert ? colors.error : colors.muted;
  return (
    <button
      onClick={onClick}
      title={tooltip || label}
      className="text-left rounded-2xl p-3 transition hover:brightness-95"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${borderColor}`,
      }}
      data-testid={testid}
    >
      <div className="flex items-center gap-1.5" style={{ color: labelColor }}>
        {Icon ? <Icon size={13} /> : null}
        <span className="text-xs font-semibold uppercase tracking-wide">{label}</span>
      </div>
      <div
        className="text-xl md:text-2xl font-bold mt-1 truncate"
        style={{ color: alert ? colors.error : colors.onSurface }}
      >
        {value}
      </div>
      {sub ? (
        <div
          className="text-xs mt-0.5 truncate"
          style={{ color: colors.muted }}
          data-testid={`${testid}-sub`}
        >
          {sub}
        </div>
      ) : null}
    </button>
  );
}

// Feb-2026 · Slice 3D — Modal / bottom-sheet for a quick service
// request. Submits directly to the new customer-portal endpoint which
// fires an internal message + admin bell + best-effort Expo push.
const SERVICE_TYPE_OPTIONS = [
  "Pool Cleaning",
  "Chemical Rebalance",
  "Equipment Repair",
  "Landscape",
  "Other",
];

function RequestServiceModal({ onClose, onSent }) {
  const [form, setForm] = useState({
    service_type: SERVICE_TYPE_OPTIONS[0],
    preferred_date: "",
    notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e?.preventDefault?.();
    setBusy(true);
    setError("");
    try {
      await api.post("/customer-portal/service-requests", {
        service_type: form.service_type,
        preferred_date: form.preferred_date || undefined,
        notes: form.notes || undefined,
      });
      setToast("Request sent — we'll be in touch shortly.");
      setTimeout(() => {
        onSent?.();
      }, 900);
    } catch (err) {
      setError(err?.message || "Failed to send request");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => {
        // Click on the backdrop closes the modal — but only if the
        // mousedown target IS the backdrop (avoids closing mid-drag
        // when selecting text inside the modal card).
        if (e.target === e.currentTarget) onClose?.();
      }}
      data-testid="portal-request-service-modal"
    >
      <form
        onSubmit={submit}
        className="w-full sm:max-w-md rounded-t-2xl sm:rounded-2xl p-5 shadow-2xl"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          maxHeight: "92vh",
          overflowY: "auto",
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-3">
          <div>
            <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
              Request Service
            </h2>
            <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
              Send a message to our team — we'll confirm the visit shortly.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg hover:brightness-95"
            style={{ color: colors.muted }}
            aria-label="Close"
            data-testid="portal-request-service-close"
          >
            <XIcon size={18} />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label
              className="text-xs font-semibold tracking-wide mb-1 block"
              style={{ color: colors.muted }}
            >
              SERVICE TYPE
            </label>
            <select
              value={form.service_type}
              onChange={set("service_type")}
              className="w-full px-3 py-2 rounded-lg text-sm outline-none"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="portal-request-service-type"
            >
              {SERVICE_TYPE_OPTIONS.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>

          <div>
            <label
              className="text-xs font-semibold tracking-wide mb-1 block"
              style={{ color: colors.muted }}
            >
              PREFERRED DATE (OPTIONAL)
            </label>
            <input
              type="date"
              value={form.preferred_date}
              onChange={set("preferred_date")}
              className="w-full px-3 py-2 rounded-lg text-sm outline-none"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="portal-request-service-date"
            />
          </div>

          <div>
            <label
              className="text-xs font-semibold tracking-wide mb-1 block"
              style={{ color: colors.muted }}
            >
              NOTES (OPTIONAL)
            </label>
            <textarea
              value={form.notes}
              onChange={set("notes")}
              rows={4}
              placeholder="Anything we should know?"
              className="w-full px-3 py-2 rounded-lg text-sm outline-none"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="portal-request-service-notes"
            />
          </div>
        </div>

        {error ? (
          <div
            className="mt-3 text-sm"
            style={{ color: colors.error }}
            data-testid="portal-request-service-error"
          >
            {error}
          </div>
        ) : null}

        <div className="mt-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-sm font-semibold"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurface,
            }}
            data-testid="portal-request-service-cancel"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white"
            style={{ background: brandGradientCss, opacity: busy ? 0.7 : 1 }}
            data-testid="portal-request-service-submit"
          >
            <Send size={14} /> {busy ? "Sending…" : "Send request"}
          </button>
        </div>
      </form>

      {toast ? (
        <div
          className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl text-sm text-white shadow-lg"
          style={{ backgroundColor: colors.onSurface }}
          data-testid="portal-request-service-toast"
        >
          {toast}
        </div>
      ) : null}
    </div>
  );
}


// Feb-2026 · Slice 5 — Customer AI chat pane.  Modal / bottom-sheet
// bound to one AI employee (Skedra or Billy).  Backend handles all
// escalation logic + credit debits; this shell just renders turns and
// exposes a manual "Handoff to human" button.
function CustomerAiChatPane({ employee, onClose }) {
  const [conv, setConv] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const c = await api.post(
          `/customer-portal/ai-employees/${employee.id}/conversations`,
          {},
        );
        if (!alive) return;
        setConv(c);
        const msgs = await api.get(
          `/customer-portal/ai-employees/${employee.id}/conversations/${c.id}/messages`,
        );
        if (alive) setMessages(Array.isArray(msgs) ? msgs : []);
      } catch {
        if (alive) setToast("Could not open chat — please try again.");
      }
    })();
    return () => { alive = false; };
  }, [employee.id]);

  const send = async (e) => {
    e?.preventDefault?.();
    const body = text.trim();
    if (!body || !conv || busy) return;
    setBusy(true);
    setText("");
    // Optimistic user echo — replaced by the server payload on success.
    const stamp = new Date().toISOString();
    setMessages((prev) => [
      ...prev,
      {
        id: `optimistic-${stamp}`,
        role: "user",
        text: body,
        created_at: stamp,
      },
    ]);
    try {
      const r = await api.post(
        `/customer-portal/ai-employees/${employee.id}/conversations/${conv.id}/messages`,
        { text: body },
      );
      setMessages((prev) => {
        const stripped = prev.filter((m) => !String(m.id).startsWith("optimistic-"));
        return [...stripped, r.user_message, r.assistant_message];
      });
      if (r.escalated) {
        setToast("A team member has been notified.");
      }
    } catch (err) {
      setToast(err?.message || "Send failed");
      // Remove the optimistic echo on failure.
      setMessages((prev) =>
        prev.filter((m) => !String(m.id).startsWith("optimistic-")),
      );
    } finally {
      setBusy(false);
    }
  };

  const handoff = async () => {
    if (!conv) return;
    setBusy(true);
    try {
      await api.post(
        `/customer-portal/ai-employees/${employee.id}/conversations/${conv.id}/handoff`,
        {},
      );
      setToast("Handoff sent — someone will follow up.");
    } catch (err) {
      setToast(err?.message || "Handoff failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}
    >
      <div
        className="w-full sm:max-w-md rounded-t-2xl sm:rounded-2xl shadow-2xl flex flex-col"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          height: "min(92vh, 640px)",
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 pt-4 pb-3"
          style={{ borderBottom: `1px solid ${colors.divider}` }}
        >
          <div className="flex items-center gap-2 min-w-0">
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center text-lg shrink-0"
              style={{
                background:
                  employee.key === "billy"
                    ? "linear-gradient(135deg,#DCFCE7,#BBF7D0)"
                    : "linear-gradient(135deg,#DBEAFE,#BFDBFE)",
              }}
              aria-hidden="true"
            >
              {employee.avatar_emoji || "🤖"}
            </div>
            <div className="min-w-0">
              <div
                className="text-sm font-bold truncate"
                style={{ color: colors.onSurface }}
              >
                {employee.name}
              </div>
              <div
                className="text-xs truncate"
                style={{ color: colors.muted }}
              >
                {employee.role}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg hover:brightness-95"
            style={{ color: colors.muted }}
            aria-label="Close"
            data-testid="portal-ai-close"
          >
            <XIcon size={18} />
          </button>
        </div>

        {/* Thread */}
        <div
          className="flex-1 overflow-y-auto px-4 py-3 space-y-2"
          data-testid="portal-ai-chat-thread"
        >
          {messages.length === 0 ? (
            <div
              className="text-xs px-1"
              style={{ color: colors.muted }}
              data-testid="portal-ai-chat-empty"
            >
              Ask a quick question — the concierge will reply straight away.
            </div>
          ) : null}
          {messages.map((m) => {
            const mine = m.role === "user";
            return (
              <div
                key={m.id}
                className={`flex ${mine ? "justify-end" : "justify-start"}`}
                data-testid={`portal-ai-msg-${m.role}`}
                data-escalated={m.escalated ? "1" : "0"}
              >
                <div
                  className="max-w-[85%] px-3 py-2 rounded-2xl text-sm whitespace-pre-wrap"
                  style={{
                    backgroundColor: mine
                      ? colors.brand
                      : colors.surfaceSecondary,
                    color: mine ? "#fff" : colors.onSurface,
                    borderTopLeftRadius: mine ? 16 : 4,
                    borderTopRightRadius: mine ? 4 : 16,
                  }}
                >
                  {m.text}
                </div>
              </div>
            );
          })}
        </div>

        {/* Composer */}
        <form
          onSubmit={send}
          className="px-3 py-3 flex items-end gap-2"
          style={{ borderTop: `1px solid ${colors.divider}` }}
          data-testid="portal-ai-composer"
        >
          <textarea
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(e);
              }
            }}
            placeholder={
              employee.key === "billy"
                ? "e.g. What's my current balance?"
                : "e.g. When's my next visit?"
            }
            className="flex-1 px-3 py-2 rounded-xl text-sm outline-none resize-none"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
              maxHeight: 120,
            }}
            data-testid="portal-ai-composer-input"
          />
          <button
            type="submit"
            disabled={busy || !text.trim()}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
            style={{ background: brandGradientCss }}
            data-testid="portal-ai-composer-send"
          >
            <Send size={14} /> Send
          </button>
        </form>
        <div className="px-4 pb-3 flex justify-between items-center">
          <button
            type="button"
            onClick={handoff}
            disabled={busy}
            className="inline-flex items-center gap-1 text-xs font-semibold"
            style={{ color: colors.brand }}
            data-testid="portal-ai-handoff-btn"
          >
            <UserRound size={12} /> Handoff to human
          </button>
          <div
            className="text-[10px]"
            style={{ color: colors.muted }}
          >
            {employee.name} may make mistakes — sensitive changes go to our team.
          </div>
        </div>
      </div>

      {toast ? (
        <div
          className="fixed bottom-6 right-6 z-[60] px-4 py-2 rounded-xl text-sm text-white shadow-lg"
          style={{ backgroundColor: colors.onSurface }}
          data-testid="portal-ai-toast"
        >
          {toast}
        </div>
      ) : null}
    </div>
  );
}

