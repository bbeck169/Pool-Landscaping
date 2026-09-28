/**
 * MTH-B · Feb-2026 — Auto-Action Allowlist card tests.
 *
 * Locks:
 *   1. Renders every action key grouped by namespace with the
 *      "N/M auto-approved" header count.
 *   2. Search filter narrows both group + row visibility.
 *   3. Toggling a row from admin_approval → auto flips the mode.
 *   4. Override pill appears when a row's mode differs from the
 *      platform-default map.
 *   5. Save PUTs the draft with reason.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: { put: vi.fn(), post: vi.fn(), get: vi.fn() },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import AutoActionAllowlistCard from "@/components/ai-rules/AutoActionAllowlistCard";

const INVENTORY = [
  "marco.clock_in",
  "marco.save_note",
  "casey.draft_outreach_reply",
  "emmie.draft_campaign",
];

const PLATFORM = {
  "marco.clock_in": "admin_approval",
  "marco.save_note": "admin_approval",
  "casey.draft_outreach_reply": "admin_approval",
  "emmie.draft_campaign": "admin_approval",
};

describe("MTH-B · AutoActionAllowlistCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.put.mockResolvedValue({ ok: true });
  });

  it("renders every action grouped by namespace", () => {
    render(
      <AutoActionAllowlistCard
        value={{ ...PLATFORM }}
        overrideMap={{}}
        platformValue={PLATFORM}
        actionInventory={INVENTORY}
      />,
    );
    expect(
      screen.getByTestId("ai-rules-auto-actions-group-marco"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("ai-rules-auto-actions-group-casey"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("ai-rules-auto-actions-group-emmie"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("ai-rules-auto-action-row-marco.clock_in"),
    ).toBeInTheDocument();
  });

  it("shows group-level 'N/M auto-approved' count", () => {
    render(
      <AutoActionAllowlistCard
        value={{
          ...PLATFORM,
          "marco.clock_in": "auto",
        }}
        overrideMap={{ "auto_action_allowlist.marco.clock_in": "tenant" }}
        platformValue={PLATFORM}
        actionInventory={INVENTORY}
      />,
    );
    // marco has 2 total, 1 auto → "1/2 auto-approved".
    expect(
      screen.getByTestId("ai-rules-auto-actions-group-count-marco").textContent,
    ).toMatch(/1\/2/);
  });

  it("search narrows visible groups + rows", () => {
    render(
      <AutoActionAllowlistCard
        value={{ ...PLATFORM }}
        overrideMap={{}}
        platformValue={PLATFORM}
        actionInventory={INVENTORY}
      />,
    );
    fireEvent.change(screen.getByTestId("ai-rules-auto-actions-search"), {
      target: { value: "casey" },
    });
    expect(
      screen.getByTestId("ai-rules-auto-actions-group-casey"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("ai-rules-auto-actions-group-marco"),
    ).not.toBeInTheDocument();
  });

  it("toggles a row from Admin → Auto and shows override pill", () => {
    render(
      <AutoActionAllowlistCard
        value={{ ...PLATFORM }}
        overrideMap={{}}
        platformValue={PLATFORM}
        actionInventory={INVENTORY}
      />,
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-auto-action-row-marco.clock_in-mode-auto"),
    );
    // The Auto button becomes active AND override pill appears
    // because the value now diverges from the platform default.
    expect(
      screen.getByTestId("ai-rules-auto-action-row-marco.clock_in-override"),
    ).toBeInTheDocument();
  });

  it("save posts the current draft with reason", async () => {
    render(
      <AutoActionAllowlistCard
        value={{ ...PLATFORM }}
        overrideMap={{}}
        platformValue={PLATFORM}
        actionInventory={INVENTORY}
      />,
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-auto-action-row-marco.clock_in-mode-auto"),
    );
    fireEvent.click(screen.getByTestId("ai-rules-auto-actions-save"));
    fireEvent.change(
      screen.getByTestId("ai-rules-auto-actions-save-reason-input"),
      { target: { value: "trusted marco action" } },
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-auto-actions-save-reason-confirm"),
    );
    await waitFor(() => {
      expect(_apiMock.put).toHaveBeenCalledTimes(1);
    });
    const [path, body] = _apiMock.put.mock.calls[0];
    expect(path).toBe("/tenant-ai-rules/auto_action_allowlist");
    expect(body.reason).toBe("trusted marco action");
    expect(body.value["marco.clock_in"]).toBe("auto");
  });
});
