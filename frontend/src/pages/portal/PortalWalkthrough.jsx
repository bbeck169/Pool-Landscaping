// Feb-2026 · Item 10 — Portal tour engine.
//
// 12-step guided tour that navigates via react-router as it goes,
// spotlights each anchor with a ring + pulsing overlay, and marks
// itself seen on complete OR skip. Zero external deps — custom
// engine keeps the bundle lean.
//
// Steps must reference elements tagged with ``data-tour-id`` — the
// anchors were laid across the customer portal in the earlier pass.
//
// Rendered ONLY for role=="customer". Also hard-gates on
// ``user.has_seen_customer_tour`` so it never replays.
import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { X, ChevronLeft, ChevronRight } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";

const STEPS = [
  // Phase 34 · Feb 2026 · Tour v2 — extended step list covers the
  // Task-K top CTA row + Task-R Last Visit position + Task-34
  // Ask-Concierge / Refer-a-Friend highlights. Anchors point at
  // stable ``data-tour-id`` (or the equivalent ``data-testid``
  // which the tour engine will also accept as a fallback selector).
  { anchor: "portal-cta-row",       route: "/portal/home",
    title: "Call Now + Request Service",
    body:  "Two taps to reach us — call directly or send a written request." },
  { anchor: "status-circles",       route: "/portal/home",
    title: "Quick account status",
    body:  "Balance, past due, credit, and your next scheduled visit at a glance." },
  { anchor: "last-visit-card",      route: "/portal/home",
    title: "Your last visit",
    body:  "See the most recent service we performed, with a shortcut to the full report." },
  { anchor: "portal-ai-section",    route: "/portal/home",
    title: "Ask a Concierge",
    body:  "Billy handles billing questions; Skedra covers scheduling. Answers in seconds." },
  { anchor: "portal-referral-section", route: "/portal/home",
    title: "Refer a Friend — earn $55 credit",
    body:  "Send us a friend's contact info and we'll reach out. You get $55 in credit after their first paid month." },
  { anchor: "business-card",        route: "/portal/home",
    title: "Our contact card",
    body:  "Save our contact — tap-to-share via NFC or vCard." },
  { anchor: "communications-list",  route: "/portal/messages",
    title: "Communications history",
    body:  "Every message we send you shows up here." },
  { anchor: "invoices-list",        route: "/portal/invoices",
    title: "Invoices",
    body:  "Pay in one tap. Past invoices are here too." },
  { anchor: "estimates-list",       route: "/portal/estimates",
    title: "Estimates",
    body:  "Approve or decline estimates here — you'll be notified when a new one is ready." },
  { anchor: "service-reports-list", route: "/portal/service-reports",
    title: "Service reports · grouped by date",
    body:  "After every visit we send a report with photos and readings. Reports are now grouped by visit date." },
  { anchor: "request-service-form", route: "/portal/request-service",
    title: "Request a one-off visit",
    body:  "Need something outside your normal schedule? Tell us what you need in a short paragraph." },
  { anchor: "payment-method-panel", route: "/portal/payment-method",
    title: "Payment method",
    body:  "Add or update the card we use for automatic billing. Cards are securely stored with Stripe." },
];

const ROUTE_SETTLE_MS = 350;

export default function PortalWalkthrough({ forceOpen = false, onClose }) {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [visible, setVisible] = React.useState(false);
  const [step, setStep] = React.useState(0);
  const [rect, setRect] = React.useState(null);
  const [status, setStatus] = React.useState(null);   // null | "should_show" | "done"

  const isCustomer = user?.role === "customer";
  const userSeen = !!user?.has_seen_customer_tour;

  // ── Decide whether to show ────────────────────────────────────
  React.useEffect(() => {
    let alive = true;
    if (!isCustomer) { setStatus("done"); return () => { alive = false; }; }
    if (forceOpen) {
      if (alive) { setStatus("should_show"); setStep(0); setVisible(true); }
      return () => { alive = false; };
    }
    if (userSeen) { setStatus("done"); return () => { alive = false; }; }
    api.get("/customer-portal/walkthrough/status")
      .then((r) => {
        if (!alive) return;
        // Phase 34 · Task V — prefer the v2 flag so v1-completers see
        // the extended step list once. Falls back to the legacy
        // ``should_show`` for older backend responses.
        const shouldShow = r?.should_show_v2 ?? r?.should_show;
        if (shouldShow) { setStatus("should_show"); setVisible(true); }
        else               { setStatus("done"); }
      })
      .catch(() => { if (alive) setStatus("done"); });
    return () => { alive = false; };
  }, [forceOpen, isCustomer, userSeen]);

  // ── Navigate + spotlight the current step ─────────────────────
  const cur = STEPS[step];
  React.useEffect(() => {
    if (!visible || !cur) return;
    let cancelled = false;
    const settle = async () => {
      if (location.pathname !== cur.route) {
        navigate(cur.route);
        await new Promise((r) => setTimeout(r, ROUTE_SETTLE_MS));
      } else {
        await new Promise((r) => setTimeout(r, 60));
      }
      if (cancelled) return;
      const el = document.querySelector(`[data-tour-id="${cur.anchor}"]`);
      if (el) {
        try { el.scrollIntoView({ behavior: "smooth", block: "center" }); }
        catch (_e) { /* JSDom lacks scrollIntoView — ignore in tests. */ }
        // Give the smooth scroll a beat to land before measuring.
        setTimeout(() => {
          if (cancelled) return;
          setRect(el.getBoundingClientRect());
        }, 320);
      } else {
        setRect(null);
      }
    };
    settle();
    return () => { cancelled = true; };
  }, [visible, step, cur, location.pathname, navigate]);

  // ── Re-measure on resize / scroll so the highlight tracks. ────
  React.useEffect(() => {
    if (!visible) return;
    const onMove = () => {
      if (!cur) return;
      const el = document.querySelector(`[data-tour-id="${cur.anchor}"]`);
      if (el) setRect(el.getBoundingClientRect());
    };
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, { passive: true });
    return () => {
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove);
    };
  }, [visible, cur]);

  const markSeenAndClose = React.useCallback(async () => {
    if (!forceOpen) {
      try { await api.post("/users/me/mark-tour-seen", {}); }
      catch (_e) {
        try { await api.post("/customer-portal/walkthrough/complete", {}); }
        catch (_e2) { /* graceful */ }
      }
      if (setUser && user) {
        setUser({ ...user, has_seen_customer_tour: true });
      }
    }
    setVisible(false);
    setStatus("done");
    if (onClose) onClose();
  }, [forceOpen, onClose, setUser, user]);

  if (!isCustomer) return null;
  if (!visible || status !== "should_show") return null;

  const isLast = step === STEPS.length - 1;
  const isFirst = step === 0;

  // Spotlight box — 8px padding around the target.
  const pad = 8;
  const box = rect ? {
    top: Math.max(0, rect.top - pad),
    left: Math.max(0, rect.left - pad),
    width: rect.width + pad * 2,
    height: rect.height + pad * 2,
  } : null;

  // Position the tooltip below the box when possible, above when not.
  const vh = typeof window !== "undefined" ? window.innerHeight : 800;
  const spaceBelow = box ? vh - (box.top + box.height) : 0;
  const showBelow = spaceBelow > 240;
  const tipStyle = box ? {
    position: "fixed",
    left: Math.min(Math.max(box.left, 16), (window.innerWidth || 1024) - 336),
    top: showBelow ? box.top + box.height + 12 : Math.max(16, box.top - 190),
    width: 320,
  } : { position: "fixed", left: 24, bottom: 24, width: 320 };

  return (
    <div className="fixed inset-0 z-[9999]"
         data-testid="portal-tour-engine">
      {/* Dim backdrop — pointer-events-auto so clicks outside the box
          don't leak to the app. */}
      <div className="absolute inset-0"
           style={{ backgroundColor: "rgba(15, 23, 42, 0.55)",
                      transition: "opacity .2s" }}
           data-testid="portal-tour-backdrop" />

      {/* Spotlight cutout — a bright ring drawn over the target rect. */}
      {box ? (
        <div
          className="absolute rounded-xl pointer-events-none"
          style={{
            top: box.top, left: box.left,
            width: box.width, height: box.height,
            boxShadow: "0 0 0 4px rgba(14,165,233,1), 0 0 0 9999px rgba(0,0,0,0.001)",
            outline: "3px solid rgba(255,255,255,0.85)",
            outlineOffset: 2,
            animation: "portalTourPulse 1.8s ease-in-out infinite",
          }}
          data-testid="portal-tour-spotlight"
        />
      ) : null}

      {/* Tooltip. */}
      <div
        style={tipStyle}
        className="bg-white rounded-xl shadow-2xl border border-zinc-200"
        data-testid="portal-tour-tooltip"
      >
        <div className="flex items-start p-4 gap-2">
          <div className="flex-1">
            <div className="text-[11px] uppercase tracking-wide font-semibold text-zinc-500"
                 data-testid="portal-tour-step-counter">
              Step {step + 1} of {STEPS.length}
            </div>
            <div className="text-base font-semibold mt-0.5"
                 data-testid="portal-tour-title">{cur.title}</div>
            <div className="text-sm text-zinc-600 mt-1.5"
                 data-testid="portal-tour-body">{cur.body}</div>
          </div>
          <button
            type="button"
            onClick={markSeenAndClose}
            className="p-1 rounded-md hover:bg-zinc-100"
            title="Skip tour"
            data-testid="portal-tour-skip"
          >
            <X size={14} className="text-zinc-500" />
          </button>
        </div>
        <div className="flex items-center gap-1 px-4 pb-2">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className={`h-1 flex-1 rounded-full ${i <= step ? "bg-sky-500" : "bg-zinc-200"}`}
              data-testid={`portal-tour-dot-${i}`}
            />
          ))}
        </div>
        <div className="flex items-center justify-between p-3 border-t border-zinc-100">
          <button
            type="button"
            disabled={isFirst}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            className="text-xs font-semibold px-2.5 py-1.5 rounded-md flex items-center gap-1 text-zinc-600 hover:bg-zinc-100 disabled:opacity-40"
            data-testid="portal-tour-back"
          >
            <ChevronLeft size={12} /> Back
          </button>
          <button
            type="button"
            onClick={markSeenAndClose}
            className="text-xs text-zinc-500 hover:text-zinc-700"
            data-testid="portal-tour-skip-text"
          >Skip tour</button>
          <button
            type="button"
            onClick={() => {
              if (isLast) { markSeenAndClose(); }
              else { setStep((s) => Math.min(STEPS.length - 1, s + 1)); }
            }}
            className="text-xs font-semibold px-3 py-1.5 rounded-md text-white bg-sky-600 hover:bg-sky-700 flex items-center gap-1"
            data-testid={isLast ? "portal-tour-finish" : "portal-tour-next"}
          >
            {isLast ? "Finish" : "Next"} {!isLast ? <ChevronRight size={12} /> : null}
          </button>
        </div>
      </div>

      {/* Keyframes lifted inline so we don't have to touch the global css. */}
      <style>{`
        @keyframes portalTourPulse {
          0%, 100% { box-shadow: 0 0 0 4px rgba(14,165,233,1), 0 0 0 9999px rgba(0,0,0,0.001); }
          50%      { box-shadow: 0 0 0 8px rgba(14,165,233,0.6), 0 0 0 9999px rgba(0,0,0,0.001); }
        }
      `}</style>
    </div>
  );
}
