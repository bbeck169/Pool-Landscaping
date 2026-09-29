import React, { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Waves, Wrench, Receipt, FileText, MessageSquare, ChevronRight, AlertCircle, Plus, ClipboardCheck, DollarSign, CalendarClock, Wallet, X as XIcon, Send, Sparkles, UserRound, Star, Image as ImageIcon, Video as VideoIcon, Trees, Filter as FilterFunnelIcon } from "lucide-react";
import { api } from "@/api";
import { portalColors as colors, gradients, portalGradients } from '@/theme';
import { useAuth } from "@/auth";
import BusinessCard from "@/components/business-card/BusinessCard";
import { Skeleton, StatusPill } from '@/components/ui-kit';
import CallNowButton from "@/pages/portal/CallNowButton";
import ReferralSection from "@/pages/portal/ReferralSection";
import MyReferralsSection from "@/pages/portal/MyReferralsSection";
// Phase 30 · Feb-2026 — shared avatar components.
// Feb-2026 · AI Concierge avatar parity — reuse the SAME shared
// <AIAvatar> the AI Employee Hub (``pages/aiops/AiOpsPages.jsx``)
// and the internal AI Dock render for each persona. Guarantees
// pixel-consistent branding across every AI-employee surface;
// PersonaAvatar stays imported for legacy call sites elsewhere in
// this file but the customer-facing Concierge picker + chat use
// AIAvatar now.
import AIAvatar from "@/components/ai/AIAvatar";
import TechAvatar from "@/components/common/TechAvatar";
import PaymentMethodPromptModal from "@/components/portal/PaymentMethodPromptModal";

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
  const [_tosStatus, setTosStatus] = useState(null);
  const [summary, setSummary] = useState(null);
  // Task RR/SS Phase 2 · Feb 2026 — live credit balance via the new
  // customer-portal endpoint. Runs in parallel with /summary so the
  // tile flips from stale (from /summary payload) → live once the
  // dedicated read resolves. Falls back to whatever /summary
  // reported if the new endpoint 404s (deploy race).
  const [creditBalanceDollars, setCreditBalanceDollars] = useState(null);
  // Feb-2026 · Slice 3D — Quick service-request modal.
  const [requestOpen, setRequestOpen] = useState(false);
  // Feb-2026 · Slice 5 — customer AI carve-out (Skedra + Billy).
  const [aiEmployees, setAiEmployees] = useState([]);
  const [aiChat, setAiChat] = useState(null);   // { employee } or null
  // Feb-2026 — Portal Quick Action tiles: Photos/Videos/Messages.
  // ``unreadMessages`` powers the Messages tile badge.
  const [unreadMessages, setUnreadMessages] = useState(0);
  // Feb-2026 · Pool Service PS-D — Smart Portal Tiles state.
  //   ``next_visits`` schema (from GET /api/portal/dashboard/next-visits):
  //     { next_visits: [
  //         { service_type: "pool"|"landscape"|"filter_cleaning",
  //           next_visit_at: "2026-03-12T09:00:00-05:00" | "2026-03-12",
  //           tech_name: "Mike Rodriguez" | null,
  //           visit_id: "..." },
  //       ...
  //     ] }
  //   ``null`` = still loading (renders skeleton).
  //   ``{next_visits: []}`` = eligible → no tiles rendered.
  //   ``"error"`` = endpoint 500'd → row hidden, no crash.
  const [nextVisits, setNextVisits] = useState(null);

  const loadSummary = () => {
    api.get("/customer-portal/summary").then(setSummary).catch(() => setSummary(null));
    api.get("/customer-portal/credits/balance")
      .then((r) => {
        if (r && typeof r.balance_dollars === "number") {
          setCreditBalanceDollars(r.balance_dollars);
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    api.get("/portal/home").then(setData).catch(() => setData({ counts: {} }));
    api.get("/portal/terms/status").then(setTosStatus).catch(() => {});
    loadSummary();
    // Feb-2026 — unread portal-chat count for the Messages tile badge.
    api.get("/portal/messages/unread-count")
      .then((r) => setUnreadMessages(Number(r?.unread || 0)))
      .catch(() => setUnreadMessages(0));
    // Feb-2026 · Pool Service PS-D — Next Visit tiles.  Endpoint
    // returns [] when nothing qualifies; hitting a 500 flips
    // state to the ``"error"`` sentinel so the row hides fully
    // (fail-quietly per portal UX ruling #8).
    api.get("/portal/dashboard/next-visits")
      .then((r) => {
        const rows = Array.isArray(r?.next_visits)
          ? r.next_visits
          : [];
        setNextVisits(rows);
      })
      .catch((exc) => {
        // eslint-disable-next-line no-console
        console.warn("[ps-d] next-visits fetch failed", exc);
        setNextVisits("error");
      });
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
  // Feb-2026 P0 defense-in-depth — prefer the SERVER-scoped customer
  // name (returned by ``/portal/home`` and scoped strictly by JWT
  // ``customer_id`` + ``tenant_id``) over the JWT's ``user.name``
  // claim. If a mis-linked ``users.customer_id`` on the server ever
  // resolves the wrong customer, the greeting will still reflect
  // the ACTUAL customer the API is returning data for, so a mismatch
  // becomes visually obvious instead of masquerading. Falls back to
  // the JWT name only if the endpoint hasn't responded yet.
  const _serverName =
    data?.customer?.first_name ||
    (data?.customer?.name && String(data.customer.name).split(" ")[0]) ||
    "";
  const first = _serverName || user?.name?.split(" ")[0] || "there";

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-home">
      {/* Phase K11 · Feb-2026 — Payment-method prompt modal.  Renders
          once per browser session when the customer has no card or a
          card expiring within 30 days.  Hidden during impersonation. */}
      <PaymentMethodPromptModal />
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
          they're not duplicated.
          Phase P43 · Feb-2026 — the legacy ``mt-12 sm:mt-0`` top-offset
          hack (which used to push the CTA row below the floating
          UniversalMenu pill cluster) has been REMOVED.  The portal
          shell now mounts a proper sticky ``<header data-testid=
          "portal-sticky-header">`` (56px tall / ``h-14``) inside
          ``AppLayout``, so the outlet no longer needs padding
          compensation. */}
      <div
        className="mb-4 flex flex-col sm:flex-row gap-3 md:gap-4"
        data-testid="portal-cta-row"
        data-tour-id="portal-cta-row"
      >
        <div className="flex-1 min-w-0" data-testid="portal-cta-call">
          <CallNowButton />
        </div>
        <button
          onClick={() => setRequestOpen(true)}
          className="inline-flex items-center justify-center gap-2 flex-1 min-w-0 px-4 py-3 rounded-xl text-sm font-bold text-white shadow-sm hover:brightness-95"
          style={{ background: gradients.navyToGreen.css, minHeight: 48 }}
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
        style={{ background: portalGradients.navyToBlue.css, minHeight: 180 }}
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
                <div className="text-sm opacity-90 mt-1 flex items-center gap-1.5">
                  {data.next_visit.technician_name ? (
                    <TechAvatar user={{ name: data.next_visit.technician_name }} size="xs" testid="portal-tech-avatar-next" />
                  ) : null}
                  <span>
                    {data.next_visit.scheduled_date
                      ? new Date(data.next_visit.scheduled_date).toDateString()
                      : "TBD"}{" "}
                    · {data.next_visit.technician_name || "Unassigned"}
                  </span>
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

      {/* Feb-2026 · Pool Service PS-D — Smart Portal Tiles.
          Renders a horizontal row (mobile: stacked) of "Next
          Visit" tiles for Pool, Landscape, and Filter Cleaning.
          Eligibility (BOTH must hold per service type):
            1. Active recurring subscription for that service.
            2. At least one future scheduled job for that service.
          Backend filters to eligible entries only — see
          routers/portal_next_visits.py.  Loading state renders
          a skeleton row.  API error ("error" sentinel) or empty
          array → row not rendered (fail-quietly per ruling #8).
          Order: Pool → Landscape → Filter Cleaning (backend
          guarantees the sort). */}
      {nextVisits === null ? (
        <div
          className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-3"
          data-testid="next-visits-skeleton"
        >
          <Skeleton style={{ height: 88, borderRadius: 12 }} />
          <Skeleton style={{ height: 88, borderRadius: 12 }} />
          <Skeleton style={{ height: 88, borderRadius: 12 }} />
        </div>
      ) : (Array.isArray(nextVisits) && nextVisits.length > 0) ? (
        <div
          className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-3"
          data-testid="next-visits-tile-row"
        >
          {nextVisits.map((nv) => (
            <NextVisitTile
              key={nv.service_type}
              nv={nv}
              onOpen={() => navigate(
                `/portal/schedule?service_type=${encodeURIComponent(nv.service_type)}`,
              )}
            />
          ))}
        </div>
      ) : null}

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
            value={
              creditBalanceDollars !== null
                ? money(creditBalanceDollars)
                : (summary ? money(summary.credit) : "—")
            }
            tooltip={
              (() => {
                const live = creditBalanceDollars !== null
                  ? creditBalanceDollars
                  : summary?.credit;
                if (live == null) return "";
                return live > 0
                  ? `${money(live)} available credit — will apply to your next invoice.`
                  : "No prepayment credit on your account.";
              })()
            }
            onClick={() => navigate("/portal/payments")}
            testidLive="portal-stat-credit-balance"
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

      {/* Phase 34 · Feb 2026 · Task S′ — the yellow "Please review our
          updated Terms of Service" nudge banner has been physically
          removed from the customer portal home per product request.
          Customers can still open the ToS page from the sidebar
          link (/portal/terms); admin-side ToS management is
          unchanged. */}

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
          {/* Feb-2026 — Quick Action tiles: Photos, Videos, Messages. */}
          <ActionTile icon={ImageIcon} label="Photos" tone="#DB2777" onClick={() => navigate("/portal/photos")} testid="qa-photos" />
          <ActionTile icon={VideoIcon} label="Videos" tone="#7C3AED" onClick={() => navigate("/portal/videos")} testid="qa-videos" />
          <ActionTile icon={MessageSquare} label="Messages" tone="#0284C7" onClick={() => navigate("/portal/chats")} testid="qa-messages" badge={unreadMessages} />
        </div>
      </div>

      {/* Phase 34 · Feb 2026 · Task R (revised) — Last Visit card now
          sits immediately ABOVE the Ask a Concierge section (was
          previously above Refer a Friend). Testid preserved
          (`last-visit-card`). */}
      {data?.last_visit ? (
        <div
          className="rounded-2xl p-5 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid="last-visit-card"
          data-tour-id="last-visit-card"
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
              <div className="text-sm flex items-center gap-1.5" style={{ color: colors.muted }}>
                {data.last_visit.technician_name ? (
                  <TechAvatar user={{ name: data.last_visit.technician_name }} size="xs" testid="portal-tech-avatar-last" />
                ) : null}
                <span>{data.last_visit.scheduled_date} · {data.last_visit.technician_name || "—"}</span>
              </div>
              <div className="mt-2"><StatusPill status={data.last_visit.status} /></div>
            </div>
            <button onClick={() => navigate(`/portal/services/${data.last_visit.id}`)}>
              <ChevronRight size={18} color={colors.muted} />
            </button>
          </div>
        </div>
      ) : null}

      {/* Phase 34 · Feb 2026 · Ask-Concierge highlight — teal→blue
          gradient, distinct from the Refer-a-Friend purple→pink card
          so the two blocks read as separate hero-ish moments. White
          text on the gradient meets WCAG AA for 14px bold+. */}
      {aiEmployees.length > 0 ? (
        <div
          className="mt-5 mb-4 rounded-3xl p-5 shadow-lg"
          style={{
            background: "linear-gradient(135deg, #0891B2 0%, #0EA5E9 50%, #10B981 100%)",
            border: "1px solid rgba(255,255,255,0.10)",
          }}
          data-testid="portal-ai-section"
          data-tour-id="portal-ai-section"
        >
          <div className="flex items-center gap-2 mb-3">
            <Sparkles size={20} style={{ color: "#FFFFFF" }} />
            <h2
              className="text-lg font-black uppercase tracking-wide"
              style={{ color: "#FFFFFF" }}
            >
              Ask a Concierge
            </h2>
          </div>
          <p
            className="text-sm mb-4"
            style={{ color: "rgba(255,255,255,0.92)" }}
          >
            Chat with one of our AI concierges — no wait, answers in seconds.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {aiEmployees.map((emp) => (
              <button
                key={emp.id}
                onClick={() => setAiChat({ employee: emp })}
                className="text-left rounded-2xl p-4 transition hover:brightness-110 flex items-start gap-3"
                style={{
                  backgroundColor: "rgba(255,255,255,0.16)",
                  border: "1px solid rgba(255,255,255,0.28)",
                  backdropFilter: "blur(6px)",
                }}
                data-testid={`portal-ai-${emp.key}-card`}
              >
                <div
                  className="w-11 h-11 rounded-full flex items-center justify-center shrink-0 text-xl overflow-hidden"
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
                  <AIAvatar
                    size={44}
                    src={emp.avatar_url || undefined}
                    name={emp.name}
                    alt={emp.name}
                    testId={`portal-ai-${emp.key}-avatar`}
                  />
                </div>
                <div className="min-w-0">
                  <div
                    className="text-sm font-bold truncate"
                    style={{ color: "#FFFFFF" }}
                  >
                    {emp.name}
                  </div>
                  <div
                    className="text-xs mt-0.5 truncate"
                    style={{ color: "rgba(255,255,255,0.85)" }}
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

      {/* Feb-2026 · Item 3/10 — Customer-facing business card.
          Phase 34 · Feb 2026 · Task Z — width parity: the wrapper
          drops the ``max-w-md`` cap so the compact business card now
          spans the same width as ReferralSection / MyReferralsSection
          (both are un-capped within the ``max-w-4xl`` portal frame).
          Card testid preserved. */}
      <div className="mb-4" data-tour-id="business-card"
           data-testid="business-card-wrap">
        <BusinessCard variant="compact" />
      </div>

      {/* Phase 34 · Feb 2026 · Task R — the Last Visit block used to
          render here at the bottom. It has been moved up to sit
          directly under Ask Concierge and above Refer a Friend.
          Intentionally blank so nothing below shifts. */}

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


// Feb-2026 · Pool Service PS-D — Smart Portal Tile renderer.
//
//   Renders ONE "Next Visit" tile.  Service-type icon + label,
//   human-readable datetime, tech name (fallback "Tech to be
//   assigned"), and a chevron cue.  Whole tile is clickable and
//   deep-links to /portal/schedule?service_type=<key>.  Palette
//   matches the sibling account tiles (Navy #1B1F5C surface,
//   Blue #3B82F6 accent on the icon puck).
const _NEXT_VISIT_META = {
  pool: {
    label: "Pool",
    icon: Waves,
  },
  landscape: {
    label: "Landscape",
    icon: Trees,
  },
  filter_cleaning: {
    label: "Filter Cleaning",
    icon: FilterFunnelIcon,
  },
};

function _formatNextVisitDatetime(iso) {
  if (!iso) return "TBD";
  try {
    // Support both date-only ("2026-03-12") and full ISO with tz.
    const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(String(iso).trim());
    const d = new Date(isDateOnly ? `${iso}T09:00:00` : iso);
    if (Number.isNaN(d.getTime())) return "TBD";
    const dayLabel = d.toLocaleDateString(undefined, {
      weekday: "long", month: "short", day: "numeric",
    });
    if (isDateOnly) return dayLabel;
    const timeLabel = d.toLocaleTimeString(undefined, {
      hour: "numeric", minute: "2-digit",
    });
    return `${dayLabel} at ${timeLabel}`;
  } catch {
    return String(iso);
  }
}

function NextVisitTile({ nv, onOpen }) {
  const meta = _NEXT_VISIT_META[nv?.service_type];
  if (!meta) return null;
  const Icon = meta.icon;
  const dtLabel = _formatNextVisitDatetime(nv.next_visit_at);
  const techLabel = nv.tech_name || "Tech to be assigned";
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex items-start gap-3 text-left rounded-xl p-3 bg-white border border-zinc-200 hover:border-blue-300 hover:shadow-sm transition"
      data-testid={`next-visit-tile-${nv.service_type}`}
      data-visit-id={nv.visit_id || ""}
    >
      <div
        className="shrink-0 flex items-center justify-center w-10 h-10 rounded-lg text-white"
        style={{ background: "#1B1F5C" }}
        aria-hidden="true"
      >
        <Icon className="w-5 h-5" style={{ color: "#3B82F6" }} />
      </div>
      <div className="min-w-0 flex-1">
        <div
          className="text-[11px] uppercase tracking-wider font-bold"
          style={{ color: "#1B1F5C" }}
        >
          {meta.label}
        </div>
        <div
          className="text-sm font-semibold truncate mt-0.5"
          style={{ color: "#111827" }}
          data-testid={`next-visit-tile-datetime-${nv.service_type}`}
        >
          {dtLabel}
        </div>
        <div
          className="text-xs text-zinc-600 truncate mt-0.5"
          data-testid={`next-visit-tile-tech-${nv.service_type}`}
        >
          {techLabel}
        </div>
      </div>
      <ChevronRight
        className="w-4 h-4 shrink-0 mt-1"
        style={{ color: "#3B82F6" }}
        aria-hidden="true"
        data-testid={`next-visit-tile-link-${nv.service_type}`}
      />
    </button>
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

function ActionTile({ icon: Icon, label, tone, onClick, testid, badge }) {
  return (
    <button
      onClick={onClick}
      className="rounded-xl p-4 text-left transition hover:brightness-95 relative"
      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
      data-testid={testid}
    >
      <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-2" style={{ backgroundColor: tone + "20", color: tone }}>
        <Icon size={18} />
      </div>
      <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{label}</div>
      {badge && Number(badge) > 0 ? (
        <span
          className="absolute top-2 right-2 min-w-[20px] h-5 px-1.5 rounded-full flex items-center justify-center text-[10px] font-bold"
          style={{ background: colors.error, color: "#fff" }}
          data-testid={`${testid}-badge`}
        >{Number(badge) > 99 ? "99+" : badge}</span>
      ) : null}
    </button>
  );
}

// Feb-2026 · Slice 3B · Portal account tile.  Compact, single-row-of-4
// on md+, 2×2 on mobile.  ``alert=true`` swaps the border + label
// colour red (used by Past Due when > 0).
function Tile({ label, value, sub, icon: Icon, _tone, alert, tooltip, onClick, testid, testidLive }) {
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
        data-testid={testidLive || undefined}
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
            style={{ background: gradients.navyToGreen.css, opacity: busy ? 0.7 : 1 }}
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
              className="w-12 h-12 rounded-full flex items-center justify-center text-2xl shrink-0 overflow-hidden"
              style={{
                background:
                  employee.key === "billy"
                    ? "linear-gradient(135deg,#DCFCE7,#BBF7D0)"
                    : "linear-gradient(135deg,#DBEAFE,#BFDBFE)",
              }}
              aria-hidden="true"
            >
              <AIAvatar
                size={48}
                src={employee.avatar_url || undefined}
                name={employee.name}
                alt={employee.name}
                testId={`portal-ai-chat-avatar-${employee.key}`}
              />
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
            style={{ background: gradients.navyToGreen.css }}
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

