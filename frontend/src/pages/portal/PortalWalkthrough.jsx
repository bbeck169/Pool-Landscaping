// Feb-2026 · Slice I — Customer portal first-login walkthrough.
//
// Lightweight custom tour (no external deps). Overlays a dimmed
// backdrop with a positioned tooltip pointing at each target testid
// in sequence.
//
// Justification for custom vs Shepherd.js/Reactour: adding a 40kb+
// package for a nine-step self-contained tour that never re-runs on
// the same customer is overkill. Custom control keeps the bundle
// small and the tour styleable with our own tokens.
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "@/api";

const colors = {
  brand: "#0EA5E9",
  onSurface: "#0F172A",
  muted: "#64748B",
  border: "#E2E8F0",
  surface: "#FFFFFF",
};

// Nine ordered steps referenced by data-testid targets that already
// exist on the portal (per Slice-I brief).
export const WALKTHROUGH_STEPS = [
  {
    id: "welcome", target: null,
    title: "Welcome to your portal",
    body: "Here's a 60-second tour of everything you can do here. You can skip anytime.",
  },
  {
    id: "balance", target: "portal-billing-tile",
    title: "Your balance",
    body: "Your current balance, past-due amount, and any credit on file live right here.",
  },
  {
    id: "service", target: "portal-service-records-tile",
    title: "Service records",
    body: "Every past visit with what was done, water readings, and photos.",
  },
  {
    id: "invoices", target: "portal-invoices-tile",
    title: "Invoices & payments",
    body: "Open invoices, pay online, and view receipts.",
  },
  {
    id: "messages", target: "portal-quick-request-btn",
    title: "Messages & requests",
    body: "Send us a message or request a service in a couple of clicks.",
  },
  {
    id: "reviews", target: "portal-reviews-tile",
    title: "Leave a review",
    body: "Tell us how we're doing after a visit.",
  },
  {
    id: "preferences", target: "portal-preferences-link",
    title: "Your preferences",
    body: "Update contact info, notification prefs, and how you want to be reached.",
  },
  {
    id: "ai", target: "portal-ai-section",
    title: "Ask a concierge",
    body: "Skedra and Billy are here 24/7 for questions about your account.",
  },
  {
    id: "done", target: null,
    title: "You're all set",
    body: "You can replay this tour any time from Preferences.",
  },
];


export default function PortalWalkthrough({ forceOpen = false, onClose }) {
  const [status, setStatus] = useState(null);      // null | "should_show" | "done"
  const [step, setStep] = useState(0);
  const [rect, setRect] = useState(null);

  // Load status once. Skipped when the caller forceOpens (replay).
  useEffect(() => {
    let alive = true;
    if (forceOpen) {
      if (alive) { setStatus("should_show"); setStep(0); }
      return () => { alive = false; };
    }
    api.get("/customer-portal/walkthrough/status")
      .then((r) => { if (alive) setStatus(r.should_show ? "should_show" : "done"); })
      .catch(() => { if (alive) setStatus("done"); });
    return () => { alive = false; };
  }, [forceOpen]);

  const cur = WALKTHROUGH_STEPS[step];

  useLayoutEffect(() => {
    if (status !== "should_show" || !cur) { setRect(null); return; }
    if (!cur.target) { setRect(null); return; }
    const q = () => {
      const node = document.querySelector(`[data-testid="${cur.target}"]`);
      if (!node) { setRect(null); return; }
      const r = node.getBoundingClientRect();
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
      node.scrollIntoView({ behavior: "smooth", block: "center" });
    };
    q();
    window.addEventListener("resize", q);
    window.addEventListener("scroll", q, true);
    return () => {
      window.removeEventListener("resize", q);
      window.removeEventListener("scroll", q, true);
    };
  }, [step, status, cur]);

  const complete = async () => {
    // Only mark complete on the SERVER when the tour is running for
    // the first time (not on the replay from preferences — the flag
    // never clears).
    if (!forceOpen) {
      try { await api.post("/customer-portal/walkthrough/complete", {}); }
      catch (e) { /* graceful — user still sees close */ }
    }
    setStatus("done");
    if (onClose) onClose();
  };

  if (status !== "should_show") return null;

  const isFirst = step === 0;
  const isLast = step === WALKTHROUGH_STEPS.length - 1;

  const tooltipPos = rect
    ? {
        top: Math.min(rect.top + rect.height + 12, window.innerHeight - 240),
        left: Math.min(Math.max(rect.left, 20), window.innerWidth - 340),
      }
    : {
        top: "50%", left: "50%",
        transform: "translate(-50%, -50%)",
      };

  const spotlightPad = 6;

  return (
    <div data-testid="portal-walkthrough-container"
         style={{ position: "fixed", inset: 0, zIndex: 9998,
                  pointerEvents: "auto" }}>
      {/* Dim backdrop with a spotlight cutout for the current target. */}
      <div style={{
        position: "absolute", inset: 0,
        background: "rgba(15,23,42,.55)",
        WebkitClipPath: rect ? _spotlight(rect, spotlightPad) : "none",
        clipPath: rect ? _spotlight(rect, spotlightPad) : "none",
      }} />

      {/* Tooltip card. */}
      <div style={{
        position: "absolute",
        ...tooltipPos,
        width: 320,
        background: colors.surface,
        borderRadius: 14,
        border: `1px solid ${colors.border}`,
        boxShadow: "0 24px 60px rgba(0,0,0,.24)",
        padding: 18,
        zIndex: 9999,
      }}
      data-testid={`portal-walkthrough-step-${step}`}>
        <div style={{
          fontSize: 11, fontWeight: 700, textTransform: "uppercase",
          color: colors.muted, letterSpacing: ".05em", marginBottom: 6,
        }}>
          Step {step + 1} of {WALKTHROUGH_STEPS.length}
        </div>
        <div style={{
          fontSize: 16, fontWeight: 700, color: colors.onSurface,
          marginBottom: 6,
        }}>{cur.title}</div>
        <div style={{ fontSize: 14, color: colors.onSurface, marginBottom: 14 }}>
          {cur.body}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between",
                       alignItems: "center", gap: 8 }}>
          <button onClick={complete}
                  data-testid="portal-walkthrough-skip-btn"
                  style={{
                    background: "transparent", border: "none",
                    color: colors.muted, fontSize: 12,
                    fontWeight: 600, cursor: "pointer",
                  }}>
            Skip
          </button>
          <div style={{ display: "flex", gap: 6 }}>
            <button disabled={isFirst}
                    data-testid="portal-walkthrough-prev-btn"
                    onClick={() => setStep((s) => Math.max(0, s - 1))}
                    style={{
                      padding: "8px 14px", borderRadius: 10,
                      border: `1px solid ${colors.border}`,
                      background: "#fff", color: colors.onSurface,
                      fontSize: 13, fontWeight: 600, cursor: "pointer",
                      opacity: isFirst ? 0.4 : 1,
                    }}>
              Back
            </button>
            <button onClick={() =>
              isLast ? complete() : setStep((s) => s + 1)
            }
                    data-testid="portal-walkthrough-next-btn"
                    style={{
                      padding: "8px 14px", borderRadius: 10,
                      background: colors.brand, color: "#fff",
                      fontSize: 13, fontWeight: 700, cursor: "pointer",
                      border: "none",
                    }}>
              {isLast ? "Done" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


function _spotlight(rect, pad) {
  // CSS clip-path polygon that shows everything OUTSIDE the target
  // rectangle. Combined with the semi-opaque backdrop it creates the
  // "spotlight" effect: the target is bright, the rest is dimmed.
  const x1 = rect.left - pad, y1 = rect.top - pad;
  const x2 = rect.left + rect.width + pad, y2 = rect.top + rect.height + pad;
  return `polygon(
    0 0, 100% 0, 100% 100%, 0 100%, 0 0,
    ${x1}px ${y1}px, ${x1}px ${y2}px,
    ${x2}px ${y2}px, ${x2}px ${y1}px,
    ${x1}px ${y1}px
  )`;
}
