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
} from "lucide-react";
import { api } from "@/api";
import { brandGradientCss, colors } from '@/theme';
import { useAuth } from "@/auth";
import { Skeleton, StatusPill } from '@/components/ui-kit';

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

  const loadSummary = () =>
    api.get("/customer-portal/summary").then(setSummary).catch(() => setSummary(null));

  useEffect(() => {
    api.get("/portal/home").then(setData).catch(() => setData({ counts: {} }));
    api.get("/portal/terms/status").then(setTosStatus).catch(() => {});
    loadSummary();
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

      {/* Feb-2026 · Slice 3B — Account tiles: Balance Due · Past Due ·
          Credit · Next Service. Rendered before the hero so the numbers
          the customer opened the portal to check are the first thing
          they see. */}
      <div
        className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4"
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

      {/* Feb-2026 · Slice 3D — Prominent Request Service CTA. Opens a
          modal so the customer never has to leave the landing page. */}
      <div className="mb-4 flex justify-end">
        <button
          onClick={() => setRequestOpen(true)}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold text-white shadow-sm hover:brightness-95"
          style={{ background: brandGradientCss }}
          data-testid="portal-request-service-btn"
        >
          <Plus size={16} /> Request Service
        </button>
      </div>

      {/* Original hero + rest of the page continues below */}
      <div
        className="rounded-2xl p-6 md:p-8 mb-4 text-white relative overflow-hidden"
        style={{ background: brandGradientCss, minHeight: 180 }}
        data-testid="portal-hero"
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

      {/* Alerts */}
      {data ? (
        <div className="grid grid-cols-3 gap-2 mb-4">
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

      {/* Quick actions */}
      <div
        className="rounded-2xl p-5 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="text-xs uppercase font-semibold mb-3" style={{ color: colors.muted }}>
          Quick actions
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <ActionTile icon={Plus} label="Request Service" tone={colors.brand} onClick={() => setRequestOpen(true)} testid="qa-request" />
          <ActionTile icon={ClipboardCheck} label="Service Reports" tone="#0891B2" onClick={() => navigate("/portal/service-reports")} testid="qa-service-reports" />
          <ActionTile icon={Receipt} label="Invoices" tone="#A16207" onClick={() => navigate("/portal/invoices")} testid="qa-invoices" />
          <ActionTile icon={FileText} label="Estimates" tone="#4338CA" onClick={() => navigate("/portal/estimates")} testid="qa-estimates" />
          <ActionTile icon={Wrench} label="Payment Method" tone={colors.success} onClick={() => navigate("/portal/payment-method")} testid="qa-pm" />
        </div>
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

      {/* Feb-2026 · Slice 3D — Quick Request Service modal.  Renders
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

