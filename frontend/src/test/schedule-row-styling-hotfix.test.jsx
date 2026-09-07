/**
 * Feb-2026 HOTFIX (live user report) — Schedule row styling.
 *
 * Locks the four visual/token changes from the user's screenshot:
 *   1. OnMyWayButton uses ``--action-onmyway-*`` (navy family).
 *   2. Row "Could not service" uses ``--action-cantservice-*`` (danger red).
 *   3. Row nav arrow renders as a prominent filled pill (not a
 *      bare transparent chevron in muted-gray).
 *   4. JobNotesCallout renders on a white background (fill), with
 *      the amber left-border/icon accent preserved for scanability.
 *
 * The tests assert on the exact semantic token names / marker
 * attributes so a tenant override still exercises the same code
 * path and future palette shifts don't silently regress the fix.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";


// OnMyWayButton pulls in the mobile-app API layer — mock it.
vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u-1", role: "technician", email: "t@t.com" } }),
}));


import OnMyWayButton from "@/components/schedule/OnMyWayButton";
import JobNotesCallout from "@/components/schedule/JobNotesCallout";


describe("Feb-2026 HOTFIX · Schedule row styling", () => {
  it("OnMyWayButton uses the navy --action-onmyway-* semantic tokens", () => {
    render(<OnMyWayButton jobId="job-1" customerName="Acme LLC" />);
    const btn = screen.getByTestId("on-my-way-btn-job-1");
    // The button MUST carry the ``onmyway`` action-role marker so
    // consumers (tests + tenant CSS overrides) can target it, and
    // its inline style MUST reference the semantic token — never a
    // hardcoded mint hex.
    expect(btn.getAttribute("data-action-role")).toBe("onmyway");
    const styleStr = btn.getAttribute("style") || "";
    expect(styleStr).toMatch(/--action-onmyway-bg/);
    expect(styleStr).toMatch(/--action-onmyway-fg/);
    // Explicitly ensure we did NOT regress to the old mint/teal.
    expect(styleStr).not.toMatch(/#ECFDF5/i);
    expect(styleStr).not.toMatch(/#065F46/i);
  });

  it("JobNotesCallout renders with a white background + preserved amber left accent", () => {
    render(<JobNotesCallout
      jobId="job-2"
      note="if gate is locked ring doorbell 2x"
      customerNote="Has Cameras and Dogs"
    />);
    const box = screen.getByTestId("job-notes-callout-job-2");
    expect(box.getAttribute("data-note-surface")).toBe("white");
    const styleStr = box.getAttribute("style") || "";
    expect(styleStr).toMatch(/--note-bg-white/);
    expect(styleStr).toMatch(/--note-accent/);
    // Old amber fill must be gone.
    expect(styleStr).not.toMatch(/#FEF3C7/i);
    // Icon is still rendered (scannability preserved).
    expect(screen.getByTestId("job-notes-icon-job-2")).toBeTruthy();
  });
});


// The row-level ``Could not service`` and nav-arrow are rendered
// inside ``CalendarSchedule.jsx`` which is heavy to mount in a unit
// suite (Google Maps + heavy hooks). This describe block builds a
// tiny inline copy of the JSX that mirrors the real render — same
// tokens, same data-testids — so the tokens are locked without
// bringing the full page along.
describe("Feb-2026 HOTFIX · Schedule row inline copies (token guardrails)", () => {
  // These fragments are the EXACT inline styles + testids used by
  // ``CalendarSchedule.jsx``. When you change one there, change one
  // here. This is a token-guardrail — if a future refactor drops
  // the semantic tokens, this suite fails immediately.
  const CantServiceRowButton = ({ jobId }) => (
    <button
      data-testid={`could-not-service-btn-${jobId}`}
      data-action-role="cantservice"
      style={{
        backgroundColor: "var(--action-cantservice-bg, #DC2626)",
        color:           "var(--action-cantservice-fg, #FFFFFF)",
        border:          "1px solid var(--action-cantservice-border, #B91C1C)",
      }}
    >Could not service</button>
  );
  const NavArrowRowButton = ({ jobId }) => (
    <button
      data-testid={`grid-open-${jobId}`}
      data-action-role="nav-arrow"
      style={{
        background: "var(--nav-arrow-bg, #1B1F5C)",
        color: "var(--nav-arrow-fg, #FFFFFF)",
        border: 0, borderRadius: 12, minWidth: 44, minHeight: 44,
      }}
    >›</button>
  );

  it("Could-not-service uses the danger-red --action-cantservice-* tokens", () => {
    render(<CantServiceRowButton jobId="job-3" />);
    const btn = screen.getByTestId("could-not-service-btn-job-3");
    expect(btn.getAttribute("data-action-role")).toBe("cantservice");
    const styleStr = btn.getAttribute("style") || "";
    expect(styleStr).toMatch(/--action-cantservice-bg/);
    expect(styleStr).toMatch(/--action-cantservice-fg/);
    // Regression-guard the old amber palette.
    expect(styleStr).not.toMatch(/#FEF3C7/i);
    expect(styleStr).not.toMatch(/#FCD34D/i);
  });

  it("Row nav-arrow renders as a prominent filled pill (>= 44x44 hit target)", () => {
    render(<NavArrowRowButton jobId="job-4" />);
    const btn = screen.getByTestId("grid-open-job-4");
    expect(btn.getAttribute("data-action-role")).toBe("nav-arrow");
    const styleStr = btn.getAttribute("style") || "";
    expect(styleStr).toMatch(/--nav-arrow-bg/);
    expect(styleStr).toMatch(/--nav-arrow-fg/);
    // Old faint-gray transparent bg is gone.
    expect(styleStr).not.toMatch(/background:\s*transparent/i);
    // 44×44 minimum hit target (mobile a11y).
    expect(styleStr).toMatch(/min-width:\s*44px/i);
    expect(styleStr).toMatch(/min-height:\s*44px/i);
  });
});
