/**
 * MTH-B · Feb-2026 — Escalation Rules card tests.
 *
 * Locks:
 *   1. Renders existing rules; empty state when zero.
 *   2. + Add Rule appends a new row.
 *   3. Regex toggle flips ``is_regex``.
 *   4. SLA input clamps to 1..1440.
 *   5. Save PUTs the cleaned rule set with reason.
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

import EscalationRulesCard from "@/components/ai-rules/EscalationRulesCard";

const RULES = [
  {
    keyword: "refund",
    is_regex: false,
    target_role: "admin",
    sla_minutes: 5,
    notify_channel: "email",
  },
];

describe("MTH-B · EscalationRulesCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.put.mockResolvedValue({ ok: true });
  });

  it("renders existing rules", () => {
    render(
      <EscalationRulesCard value={RULES} overrideMap={{}} platformValue={[]} />,
    );
    expect(screen.getByTestId("ai-rules-escalation-row-0")).toBeInTheDocument();
    expect(screen.getByTestId("ai-rules-escalation-row-0-keyword").value).toBe(
      "refund",
    );
  });

  it("empty-state renders when no rules", () => {
    render(
      <EscalationRulesCard value={[]} overrideMap={{}} platformValue={[]} />,
    );
    expect(screen.getByTestId("ai-rules-escalation-empty")).toBeInTheDocument();
  });

  it("+ Add Rule appends a row", () => {
    render(
      <EscalationRulesCard value={RULES} overrideMap={{}} platformValue={[]} />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-escalation-add"));
    expect(screen.getByTestId("ai-rules-escalation-row-1")).toBeInTheDocument();
  });

  it("regex checkbox flips is_regex on the row", () => {
    render(
      <EscalationRulesCard value={RULES} overrideMap={{}} platformValue={[]} />,
    );
    const cb = screen.getByTestId("ai-rules-escalation-row-0-regex");
    expect(cb.checked).toBe(false);
    fireEvent.click(cb);
    expect(cb.checked).toBe(true);
  });

  it("SLA input clamps at the 1440 upper bound", () => {
    render(
      <EscalationRulesCard value={RULES} overrideMap={{}} platformValue={[]} />,
    );
    const sla = screen.getByTestId("ai-rules-escalation-row-0-sla");
    fireEvent.change(sla, { target: { value: "5000" } });
    expect(Number(sla.value)).toBe(1440);
  });

  it("save PUTs the cleaned rules with reason", async () => {
    render(
      <EscalationRulesCard value={RULES} overrideMap={{}} platformValue={[]} />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-escalation-save"));
    fireEvent.change(
      screen.getByTestId("ai-rules-escalation-save-reason-input"),
      { target: { value: "adding refund rule" } },
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-escalation-save-reason-confirm"),
    );
    await waitFor(() => {
      expect(_apiMock.put).toHaveBeenCalledWith(
        "/tenant-ai-rules/escalation_rules",
        expect.objectContaining({
          value: expect.arrayContaining([
            expect.objectContaining({ keyword: "refund" }),
          ]),
          reason: "adding refund rule",
        }),
      );
    });
  });
});
