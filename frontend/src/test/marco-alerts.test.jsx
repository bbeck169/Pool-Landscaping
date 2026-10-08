/**
 * Feb-2026 · MARCO Proactive Alerts — frontend vitest suite.
 *
 * Covers:
 *   (a) ``useMarcoAlerts`` — polls /count, exposes
 *       ``{supported, count, bySeverity, byKind}``.
 *   (b) ``useMarcoAlerts`` — non-admin role returns supported=false
 *       and never polls.
 *   (c) ``AlertsBadge`` — renders only when count>0, displays
 *       99+ cap, max-severity-wins color, click fires
 *       ``ai-dock:open-alerts`` event.
 *   (d) ``AlertsPanel`` — fetches /alerts on mount, renders rows,
 *       ack button POSTs, dismiss removes from list.
 *   (e) ``AlertsPanel`` — empty state copy.
 */
import React from "react";
import {
  render, screen, waitFor, act, fireEvent, cleanup,
} from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

const _api = {
  get: vi.fn(),
  post: vi.fn(),
};
vi.mock("@/api", () => ({
  api: {
    get: (p) => _api.get(p),
    post: (p, b) => _api.post(p, b),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#123", onBrand: "#fff",
    surface: "#fff", surfaceMuted: "#eee",
    onSurface: "#111", onSurfaceSecondary: "#333",
    muted: "#999", border: "#ccc", danger: "#c00",
    warning: "#f90",
  },
}));

vi.mock("lucide-react", () => ({
  AlertTriangle: (p) => <span data-testid="icon-warn" {...p}/>,
  AlertCircle:   (p) => <span data-testid="icon-error" {...p}/>,
  Info:          (p) => <span data-testid="icon-info" {...p}/>,
  Check:         (p) => <span data-testid="icon-check" {...p}/>,
  X:             (p) => <span data-testid="icon-x" {...p}/>,
  ChevronDown:   (p) => <span data-testid="icon-down" {...p}/>,
  ChevronRight:  (p) => <span data-testid="icon-right" {...p}/>,
  ExternalLink:  (p) => <span data-testid="icon-link" {...p}/>,
}));

beforeEach(() => {
  _api.get.mockReset();
  _api.post.mockReset();
});

afterEach(() => {
  cleanup();
});


// ══════════════════════════════════════════════════════════════════
// (a)(b) useMarcoAlerts
// ══════════════════════════════════════════════════════════════════
describe("useMarcoAlerts", () => {
  it("(a) polls /count and exposes aggregate state for admin", async () => {
    _api.get.mockResolvedValue({
      total: 5,
      unacknowledged: 3,
      by_severity: { info: 0, warn: 3, error: 2 },
      by_kind: { overdue_invoice: 2, sms_failed: 3 },
    });
    const { default: useMarcoAlerts } = await import(
      "../hooks/useMarcoAlerts.js");

    let captured = null;
    function _Harness() {
      captured = useMarcoAlerts({ user: { role: "admin" } });
      return <div data-testid="state">{captured.count}</div>;
    }
    render(<_Harness/>);
    await waitFor(() => expect(_api.get).toHaveBeenCalledWith(
      "/ai/marco/alerts/count"));
    await waitFor(() => expect(captured.count).toBe(5));
    expect(captured.supported).toBe(true);
    expect(captured.bySeverity.error).toBe(2);
    expect(captured.unacknowledged).toBe(3);
  });

  it("(b) returns supported:false for technician + never polls",
      async () => {
    _api.get.mockResolvedValue({ total: 0 });
    const { default: useMarcoAlerts } = await import(
      "../hooks/useMarcoAlerts.js");
    let captured = null;
    function _Harness() {
      captured = useMarcoAlerts({
        user: { role: "technician" },
        intervalMs: 50,   // tiny — would fire fast if polling were enabled.
      });
      return <div data-testid="harness"/>;
    }
    render(<_Harness/>);
    await waitFor(() => expect(screen.getByTestId("harness")).toBeTruthy());
    expect(captured.supported).toBe(false);
    // Wait longer than the (would-be) poll interval; nothing fires.
    await new Promise((r) => setTimeout(r, 200));
    expect(_api.get).not.toHaveBeenCalled();
  });
});


// ══════════════════════════════════════════════════════════════════
// (c) AlertsBadge
// ══════════════════════════════════════════════════════════════════
describe("AlertsBadge", () => {
  it("(c1) returns null when count<=0", async () => {
    const { default: AlertsBadge } = await import(
      "../components/AIDock/AlertsBadge.jsx");
    const { container } = render(<AlertsBadge count={0}/>);
    expect(container.innerHTML).toBe("");
  });

  it("(c2) renders number + fires ai-dock:open-alerts on click",
      async () => {
    const { default: AlertsBadge } = await import(
      "../components/AIDock/AlertsBadge.jsx");
    const seen = [];
    const handler = (ev) => seen.push(ev.detail);
    window.addEventListener("ai-dock:open-alerts", handler);
    render(<AlertsBadge count={120}
                        bySeverity={{ error: 2, warn: 0, info: 0 }}/>);
    const btn = screen.getByTestId("ai-dock-alerts-badge");
    expect(btn.textContent).toBe("99+");
    expect(btn.dataset.severity).toBe("error");
    await act(async () => { fireEvent.click(btn); });
    expect(seen.length).toBe(1);
    expect(seen[0].count).toBe(120);
    window.removeEventListener("ai-dock:open-alerts", handler);
  });
});


// ══════════════════════════════════════════════════════════════════
// (d)(e) AlertsPanel
// ══════════════════════════════════════════════════════════════════
describe("AlertsPanel", () => {
  it("(d) fetches /alerts on mount, Ack POSTs, Dismiss removes",
      async () => {
    const row = {
      id: "ACT_1",
      kind: "overdue_invoice", severity: "warn",
      title: "Invoice INV-1 is overdue",
      body: "$450",
      entity_ref: { type: "invoice", id: "INV-1" },
      acknowledged_at: null, acknowledged_by: null,
      dismissed_at: null, dismissed_by: null,
    };
    const acked = { ...row,
      acknowledged_at: "2026-02-01T00:00:00Z",
      acknowledged_by: "u1" };
    // Three GETs: initial mount + ack-triggered refresh +
    // dismiss-triggered refresh (post optimistic drop).
    _api.get
      .mockResolvedValueOnce([row])
      .mockResolvedValueOnce([acked])
      .mockResolvedValueOnce([]);
    _api.post.mockResolvedValueOnce(acked);
    _api.post.mockResolvedValueOnce({ ok: true });

    const { default: AlertsPanel } = await import(
      "../components/AIDock/AlertsPanel.jsx");
    render(<AlertsPanel/>);

    await waitFor(() => expect(_api.get).toHaveBeenCalledWith(
      "/ai/marco/alerts?limit=100"));
    await waitFor(() => expect(
      screen.getByTestId("marco-alert-row-ACT_1")).toBeTruthy());

    // Ack — POST fires, row remains visible but shows acked state.
    await act(async () => {
      fireEvent.click(screen.getByTestId("marco-alert-ack-ACT_1"));
    });
    await waitFor(() => expect(_api.post).toHaveBeenCalledWith(
      "/ai/marco/alerts/ACT_1/acknowledge", {}));
    // Row still mounted after ack (dismiss button still there).
    await waitFor(() => expect(
      screen.getByTestId("marco-alert-dismiss-ACT_1")).toBeTruthy());

    // Dismiss.
    await act(async () => {
      fireEvent.click(screen.getByTestId("marco-alert-dismiss-ACT_1"));
    });
    await waitFor(() => expect(_api.post).toHaveBeenCalledWith(
      "/ai/marco/alerts/ACT_1/dismiss", {}));
    // Optimistic drop + refetch returns [] → row gone.
    await waitFor(() => {
      expect(screen.queryByTestId(
        "marco-alert-row-ACT_1")).toBeFalsy();
    });
  });

  it("(e) renders empty-state copy when there are no alerts",
      async () => {
    _api.get.mockResolvedValue([]);
    const { default: AlertsPanel } = await import(
      "../components/AIDock/AlertsPanel.jsx");
    render(<AlertsPanel/>);
    await waitFor(() => expect(screen.getByTestId(
      "marco-alerts-empty")).toBeTruthy());
  });
});
