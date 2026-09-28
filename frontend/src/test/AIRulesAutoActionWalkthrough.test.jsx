/**
 * MTH-D · Feb-2026 — AutoActionAllowlistCard walkthrough modal.
 *
 * Locks:
 *   1. Clicking a row's Zap "test" button opens the walkthrough
 *      modal for that action, preselects the namespace as employee
 *      (with the marco → marco_executive alias).
 *   2. Run walkthrough POSTs /tenant-ai-rules/preview with the
 *      current draft as pending_value and the picked
 *      employee_key + action_key.
 *   3. Success renders one reason-chain step per returned entry
 *      and the final verdict banner.
 *   4. Employee selector "— Select —" (empty) disables Run.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(), success: vi.fn(),
    info: vi.fn(), warning: vi.fn(),
  },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: { post: vi.fn(), put: vi.fn(), get: vi.fn() },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import AutoActionAllowlistCard from "@/components/ai-rules/AutoActionAllowlistCard";

const INVENTORY = [
  "marco.clock_in",
  "marco.save_note",
  "casey.draft_outreach_reply",
];

const PLATFORM = {
  "marco.clock_in": "admin_approval",
  "marco.save_note": "admin_approval",
  "casey.draft_outreach_reply": "admin_approval",
};

const DRAFT = {
  ...PLATFORM,
  "marco.clock_in": "auto",
};

const EMPLOYEE_KEYS = [
  "marco_executive",
  "casey",
  "emmie",
];

function renderCard(overrides = {}) {
  return render(
    <AutoActionAllowlistCard
      value={DRAFT}
      overrideMap={{ "auto_action_allowlist.marco.clock_in": "tenant" }}
      platformValue={PLATFORM}
      actionInventory={INVENTORY}
      employeeKeys={EMPLOYEE_KEYS}
      {...overrides}
    />,
  );
}

describe("MTH-D · AutoActionAllowlistCard walkthrough modal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.post.mockResolvedValue({
      preview_kind: "auto_action_walkthrough",
      output: {
        would_auto_execute: true,
        final_verdict: "AUTO_EXECUTE",
        reason_chain: [
          { check: "master_switch", ok: true, reason: "ai=enabled" },
          { check: "employee_enabled", ok: true, reason: "marco_executive=on" },
          { check: "allowlist", ok: true, reason: "marco.clock_in=auto" },
          { check: "working_hours", ok: true, reason: "inside window" },
        ],
      },
      warnings: [],
    });
  });

  it("clicking a row's test icon opens the walkthrough modal for that action", async () => {
    renderCard();
    expect(
      screen.queryByTestId("ai-rules-auto-actions-walkthrough-modal"),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByTestId("ai-rules-auto-action-row-marco.clock_in-test"),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("ai-rules-auto-actions-walkthrough-modal"),
      ).toBeInTheDocument(),
    );
    // marco → marco_executive alias must preselect.
    expect(
      screen.getByTestId("ai-rules-auto-actions-walkthrough-employee").value,
    ).toBe("marco_executive");
  });

  it("Run walkthrough POSTs preview with draft + employee_key + action_key", async () => {
    renderCard();
    fireEvent.click(
      screen.getByTestId("ai-rules-auto-action-row-marco.clock_in-test"),
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-auto-actions-walkthrough-run"),
    );
    await waitFor(() => {
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/tenant-ai-rules/preview",
        expect.objectContaining({
          category: "auto_action_allowlist",
          preview_kind: "auto_action_walkthrough",
          pending_value: expect.objectContaining({
            "marco.clock_in": "auto",
          }),
          preview_input: {
            employee_key: "marco_executive",
            action_key: "marco.clock_in",
          },
        }),
      );
    });
  });

  it("success renders one reason-chain step per entry + verdict banner", async () => {
    renderCard();
    fireEvent.click(
      screen.getByTestId("ai-rules-auto-action-row-marco.clock_in-test"),
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-auto-actions-walkthrough-run"),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("ai-rules-auto-actions-walkthrough-chain"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("ai-rules-auto-actions-walkthrough-step-0"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("ai-rules-auto-actions-walkthrough-step-3"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("ai-rules-auto-actions-walkthrough-step-4"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("ai-rules-auto-actions-walkthrough-verdict").textContent,
    ).toMatch(/AUTO_EXECUTE/);
  });

  it("empty employee selection disables Run walkthrough", async () => {
    renderCard();
    fireEvent.click(
      screen.getByTestId("ai-rules-auto-action-row-casey.draft_outreach_reply-test"),
    );
    // casey → casey passes through as-is (no alias needed).
    fireEvent.change(
      screen.getByTestId("ai-rules-auto-actions-walkthrough-employee"),
      { target: { value: "" } },
    );
    const runBtn = screen.getByTestId("ai-rules-auto-actions-walkthrough-run");
    expect(runBtn).toBeDisabled();
    fireEvent.click(runBtn);
    expect(_apiMock.post).not.toHaveBeenCalled();
  });
});
