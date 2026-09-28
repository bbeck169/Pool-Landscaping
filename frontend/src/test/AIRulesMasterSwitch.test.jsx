/**
 * MTH-B · Feb-2026 — Master Switch card tests.
 *
 * Locks:
 *   1. Admin sees state + disabled placeholder with "Requires super-admin"
 *      title; the flip button is NOT rendered.
 *   2. Super sees the Turn ON / Turn OFF button.
 *   3. Reason modal enforces the 8-char min gate.
 *   4. Confirm submits ``PUT /api/tenant-ai-rules/master-switch``
 *      with ``{ enabled, reason }`` payload.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: { put: vi.fn(), post: vi.fn(), get: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import MasterSwitchCard from "@/components/ai-rules/MasterSwitchCard";

describe("MTH-B · MasterSwitchCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.put.mockResolvedValue({
      ok: true,
      master_ai_send_live_comms: true,
      revision_number: 4,
    });
  });

  it("shows disabled placeholder + Requires super-admin for admin role", () => {
    render(
      <MasterSwitchCard
        masterEnabled={false}
        isSuper={false}
        lastUpdatedByName="ops@ex.com"
      />,
    );
    const btn = screen.getByTestId("ai-rules-master-switch-toggle-disabled");
    expect(btn).toBeDisabled();
    expect(btn.getAttribute("title")).toMatch(/super/i);
    // The super-only actionable toggle must be absent.
    expect(
      screen.queryByTestId("ai-rules-master-switch-toggle"),
    ).not.toBeInTheDocument();
  });

  it("super sees active toggle + can open the reason modal", () => {
    render(<MasterSwitchCard masterEnabled={false} isSuper />);
    fireEvent.click(screen.getByTestId("ai-rules-master-switch-toggle"));
    expect(
      screen.getByTestId("ai-rules-master-switch-reason-modal"),
    ).toBeInTheDocument();
  });

  it("reason modal enforces 8-char minimum before confirm", () => {
    render(<MasterSwitchCard masterEnabled={false} isSuper />);
    fireEvent.click(screen.getByTestId("ai-rules-master-switch-toggle"));
    const confirm = screen.getByTestId("ai-rules-master-switch-reason-confirm");
    expect(confirm).toBeDisabled();
    fireEvent.change(
      screen.getByTestId("ai-rules-master-switch-reason-input"),
      { target: { value: "short" } },
    );
    expect(confirm).toBeDisabled();
    fireEvent.change(
      screen.getByTestId("ai-rules-master-switch-reason-input"),
      { target: { value: "reviewed by owner" } },
    );
    expect(confirm).toBeEnabled();
  });

  it("confirm posts to /tenant-ai-rules/master-switch with flipped enabled + reason", async () => {
    render(<MasterSwitchCard masterEnabled={false} isSuper />);
    fireEvent.click(screen.getByTestId("ai-rules-master-switch-toggle"));
    fireEvent.change(
      screen.getByTestId("ai-rules-master-switch-reason-input"),
      { target: { value: "reviewed by owner" } },
    );
    fireEvent.click(screen.getByTestId("ai-rules-master-switch-reason-confirm"));
    await waitFor(() => {
      expect(_apiMock.put).toHaveBeenCalledWith(
        "/tenant-ai-rules/master-switch",
        { enabled: true, reason: "reviewed by owner" },
      );
    });
  });
});
