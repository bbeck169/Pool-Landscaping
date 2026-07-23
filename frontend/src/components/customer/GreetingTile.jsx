// Feb-2026 · Item 9 — Portal home greeting tile.
//
// * Full-width gradient hero, tenant colors from business_card.
// * Left: avatar (logo_url) + "Good {tod}, {first_name}" + dynamic subline.
// * Right (≥sm): Contact us / Pay invoice / Book service quick actions.
// * Reads GET /api/customers/me/greeting-state.
//
// Rendered ONLY when the auth user has role=="customer". Callers
// are responsible for gating, but the component also self-gates as
// a belt-and-braces safety.
import React from "react";
import { useNavigate } from "react-router-dom";
import { IdCard, CreditCard, Calendar } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import BusinessCard from "@/components/business-card/BusinessCard";

const TOD_LABEL = {
  morning: "Good morning",
  afternoon: "Good afternoon",
  evening: "Good evening",
};

function makeSubline(state) {
  const t = state?.tenant_display_name || "our team";
  const d = state?.subline_data || {};
  switch (state?.subline_priority) {
    case "today_visit":
      return `Your ${d.service_title || "service"} is scheduled for today${
        d.visit_time ? ` at ${d.visit_time}` : ""
      }.`;
    case "upcoming_visit": {
      let when = "soon";
      try {
        const dt = new Date(String(d.visit_at) + (
          String(d.visit_at).length === 10 ? "T00:00:00" : ""
        ));
        when = dt.toLocaleDateString("en-US", {
          weekday: "long", month: "short", day: "numeric",
        });
      } catch (_e) { /* fall back */ }
      return `Your next ${d.service_title || "service"} is on ${when}.`;
    }
    case "unpaid_invoice": {
      const cents = Number(d.invoice_amount_cents || 0);
      const amount = (cents / 100).toLocaleString("en-US", {
        style: "currency", currency: "USD", minimumFractionDigits: 2,
      });
      return `You have an outstanding balance of ${amount}.`;
    }
    case "unread_message":
      return `You have a new message from ${t}.`;
    default:
      return `Thanks for being a valued customer of ${t}.`;
  }
}

export default function GreetingTile() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [state, setState] = React.useState(null);
  const [contactOpen, setContactOpen] = React.useState(false);

  React.useEffect(() => {
    if (!user || user.role !== "customer") return;
    let alive = true;
    api.get("/customers/me/greeting-state")
      .then((r) => { if (alive) setState(r); })
      .catch(() => { if (alive) setState(null); });
    return () => { alive = false; };
  }, [user]);

  if (!user || user.role !== "customer") return null;
  if (!state) {
    return (
      <div
        className="rounded-2xl h-[120px] mb-4 animate-pulse"
        style={{ backgroundColor: "#E5E7EB" }}
        data-testid="portal-greeting-tile-skeleton"
      />
    );
  }

  const greet = TOD_LABEL[state.time_of_day_bucket] || "Hello";
  const subline = makeSubline(state);
  const showPay = state.subline_priority === "unpaid_invoice" || state.unpaid_invoice_id;

  return (
    <>
      <div
        className="relative overflow-hidden rounded-2xl mb-4 p-5 sm:p-6 flex flex-col sm:flex-row sm:items-center gap-4"
        style={{
          minHeight: 120,
          background: `linear-gradient(135deg, ${state.gradient_from} 0%, ${state.gradient_to} 100%)`,
          color: "rgba(255,255,255,0.95)",
        }}
        data-testid="portal-greeting-tile"
        data-tour-id="greeting-tile"
      >
        {/* subtle diagonal sheen — pure CSS, no images. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-30"
          style={{
            background:
              "radial-gradient(circle at 85% 15%, rgba(255,255,255,0.35) 0%, transparent 55%)",
          }}
        />
        <div className="relative flex items-center gap-4 flex-1 min-w-0">
          {state.tenant_logo_url ? (
            <img
              src={state.tenant_logo_url}
              alt=""
              className="w-14 h-14 rounded-full object-cover bg-white/40 shrink-0"
              data-testid="portal-greeting-avatar"
            />
          ) : (
            <div
              className="w-14 h-14 rounded-full flex items-center justify-center shrink-0"
              style={{ backgroundColor: "rgba(255,255,255,0.25)",
                         color: "#fff", fontSize: 22, fontWeight: 700 }}
              data-testid="portal-greeting-avatar-fallback"
            >
              {(state.first_name || "?").slice(0, 1).toUpperCase()}
            </div>
          )}
          <div className="min-w-0">
            <div className="text-xl sm:text-2xl font-semibold leading-tight truncate"
                 data-testid="portal-greeting-headline">
              {greet}, {state.first_name}!
            </div>
            <div className="text-sm sm:text-[15px] opacity-90 mt-1"
                 data-testid="portal-greeting-subline">
              {subline}
            </div>
          </div>
        </div>

        <div className="relative hidden sm:flex flex-wrap items-center gap-2 shrink-0"
             data-testid="portal-greeting-actions">
          <button
            type="button"
            onClick={() => setContactOpen(true)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-md text-xs font-semibold hover:brightness-95"
            style={{ backgroundColor: "rgba(255,255,255,0.2)", color: "#fff",
                       border: "1px solid rgba(255,255,255,0.35)" }}
            data-testid="portal-greeting-contact-btn"
          >
            <IdCard size={13} /> Contact us
          </button>
          {showPay ? (
            <button
              type="button"
              onClick={() => navigate("/portal/invoices")}
              className="flex items-center gap-1.5 px-3 py-2 rounded-md text-xs font-semibold hover:brightness-95"
              style={{ backgroundColor: "#fff",
                         color: state.gradient_from || "#0EA5E9" }}
              data-testid="portal-greeting-pay-btn"
            >
              <CreditCard size={13} /> Pay invoice
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => navigate("/portal/book")}
            className="flex items-center gap-1.5 px-3 py-2 rounded-md text-xs font-semibold hover:brightness-95"
            style={{ backgroundColor: "rgba(255,255,255,0.2)", color: "#fff",
                       border: "1px solid rgba(255,255,255,0.35)" }}
            data-testid="portal-greeting-book-btn"
          >
            <Calendar size={13} /> Book service
          </button>
        </div>
      </div>

      {contactOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ backgroundColor: "rgba(0,0,0,0.55)" }}
          onClick={() => setContactOpen(false)}
          data-testid="portal-greeting-contact-modal"
        >
          <div
            className="relative max-w-md w-full"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => setContactOpen(false)}
              className="absolute -top-3 -right-3 w-8 h-8 rounded-full text-lg font-bold bg-white shadow-md"
              data-testid="portal-greeting-contact-close"
            >×</button>
            <BusinessCard variant="full" />
          </div>
        </div>
      ) : null}
    </>
  );
}
