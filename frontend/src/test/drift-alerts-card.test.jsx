/**
 * Phase D · Feb-2026 — DriftAlertsCard unit test.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

const _h = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
}));
vi.mock("@/api", () => ({
  api: { get: _h.get, put: _h.put, post: _h.post },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));

import DriftAlertsCard from "@/components/admin/DriftAlertsCard";

beforeEach(() => {
  _h.get.mockReset(); _h.put.mockReset(); _h.post.mockReset();
  _h.get.mockImplementation((p) => {
    if (p.endsWith("/drift-alerts")) {
      return Promise.resolve({
        tenant_id: "t1",
        enabled: true,
        email_recipients: ["ops@example.com"],
        slack_webhook_url_masked: "…abc123",
        timezone: "America/Phoenix",
      });
    }
    if (p.endsWith("/last-dispatch")) {
      return Promise.resolve({
        present: true, dispatched: true, date: "2026-02-05",
        channels_notified: ["email"], dangling_refs_total: 3,
        reason: "sent", timestamp: "2026-02-05T15:00:00Z",
      });
    }
    return Promise.resolve({});
  });
  _h.put.mockResolvedValue({
    tenant_id: "t1", enabled: true,
    email_recipients: ["ops@example.com", "dev@example.com"],
    slack_webhook_url_masked: "…xyz999", timezone: "America/Phoenix",
  });
  _h.post.mockResolvedValue({
    dispatched: false, reason: "clean", dangling_refs_total: 0,
  });
});


describe("DriftAlertsCard", () => {
  it("renders form pre-filled from GET", async () => {
    render(<DriftAlertsCard userRole="super_admin" />);
    await waitFor(() => screen.getByTestId("drift-alerts-emails-input"));
    expect(screen.getByTestId("drift-alerts-emails-input").value)
      .toBe("ops@example.com");
    expect(screen.getByTestId("drift-alerts-enabled-toggle").checked).toBe(true);
    expect(screen.getByTestId("drift-alerts-timezone-input").value)
      .toBe("America/Phoenix");
    // Masked webhook shown as reference; input is blank until user types.
    expect(screen.getByTestId("drift-alerts-webhook-input").value).toBe("");
  });

  it("Save calls PUT with normalized emails + new webhook", async () => {
    render(<DriftAlertsCard userRole="super_admin" />);
    await waitFor(() => screen.getByTestId("drift-alerts-emails-input"));
    act(() => {
      fireEvent.change(screen.getByTestId("drift-alerts-emails-input"),
        { target: { value: "ops@example.com, dev@example.com" } });
      fireEvent.change(screen.getByTestId("drift-alerts-webhook-input"),
        { target: { value: "https://hooks.slack.com/services/NEW" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("drift-alerts-save-btn"));
    });
    await waitFor(() => expect(_h.put).toHaveBeenCalledTimes(1));
    const [path, body] = _h.put.mock.calls[0];
    expect(path).toBe("/admin/settings/drift-alerts");
    expect(body.email_recipients).toEqual(
      ["ops@example.com", "dev@example.com"]);
    expect(body.slack_webhook_url).toBe(
      "https://hooks.slack.com/services/NEW");
  });

  it("Test-fire button calls the test-fire endpoint (super_admin only)", async () => {
    render(<DriftAlertsCard userRole="super_admin" />);
    await waitFor(() => screen.getByTestId("drift-alerts-test-fire-btn"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("drift-alerts-test-fire-btn"));
    });
    await waitFor(() => expect(_h.post).toHaveBeenCalledTimes(1));
    expect(_h.post.mock.calls[0][0])
      .toBe("/admin/settings/drift-alerts/test-fire");
  });

  it("Test-fire button hidden for non-super_admin", async () => {
    render(<DriftAlertsCard userRole="admin" />);
    await waitFor(() => screen.getByTestId("drift-alerts-save-btn"));
    expect(screen.queryByTestId("drift-alerts-test-fire-btn")).toBeNull();
  });
});
