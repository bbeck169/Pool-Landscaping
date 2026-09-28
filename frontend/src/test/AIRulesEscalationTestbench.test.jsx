/**
 * MTH-D · Feb-2026 — EscalationRulesCard server-driven testbench.
 *
 * Locks:
 *   1. "Test rules" button POSTs to /tenant-ai-rules/preview with
 *      ``category=escalation_rules``, ``preview_kind=escalation_match``,
 *      the cleaned pending rule set + line-split test messages
 *      (capped at 5, empty lines dropped).
 *   2. Empty message textarea shows a toast error and does NOT
 *      hit the API.
 *   3. Success renders one result row per returned message and
 *      shows the ESCALATES / no-match chip.
 *   4. Malformed-regex warnings surface an inline banner.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";

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

import EscalationRulesCard from "@/components/ai-rules/EscalationRulesCard";

const RULES = [
  {
    keyword: "refund",
    is_regex: false,
    target_role: "admin",
    sla_minutes: 5,
    notify_channel: "email",
  },
  {
    keyword: "\\bcancel\\b",
    is_regex: true,
    target_role: "super",
    sla_minutes: 15,
    notify_channel: "both",
  },
];

describe("MTH-D · EscalationRulesCard server testbench", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.post.mockResolvedValue({
      preview_kind: "escalation_match",
      output: {
        results: [
          {
            message: "refund my last visit",
            matched_rule: {
              keyword: "refund",
              is_regex: false,
              target_role: "admin",
              sla_minutes: 5,
              notify_channel: "email",
            },
            reasoning: "matched literal keyword 'refund'",
          },
          {
            message: "see you next week",
            matched_rule: null,
            reasoning: "no rule matched",
          },
        ],
      },
      warnings: [],
    });
  });

  it("Test rules POSTs preview with cleaned rules + line-split messages", async () => {
    render(
      <EscalationRulesCard
        value={RULES}
        overrideMap={{}}
        platformValue={[]}
      />,
    );
    fireEvent.change(
      screen.getByTestId("ai-rules-escalation-testbench-input"),
      {
        target: {
          value:
            "refund my last visit\n\nsee you next week\ncancel appointment\n",
        },
      },
    );
    fireEvent.click(screen.getByTestId("ai-rules-escalation-testbench-run"));
    await waitFor(() => {
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/tenant-ai-rules/preview",
        expect.objectContaining({
          category: "escalation_rules",
          preview_kind: "escalation_match",
          pending_value: expect.arrayContaining([
            expect.objectContaining({ keyword: "refund" }),
            expect.objectContaining({ keyword: "\\bcancel\\b", is_regex: true }),
          ]),
          preview_input: expect.objectContaining({
            test_messages: [
              "refund my last visit",
              "see you next week",
              "cancel appointment",
            ],
          }),
        }),
      );
    });
  });

  it("caps test_messages at 5 lines (extras dropped)", async () => {
    render(
      <EscalationRulesCard
        value={RULES}
        overrideMap={{}}
        platformValue={[]}
      />,
    );
    const lines = ["one", "two", "three", "four", "five", "six", "seven"];
    fireEvent.change(
      screen.getByTestId("ai-rules-escalation-testbench-input"),
      { target: { value: lines.join("\n") } },
    );
    fireEvent.click(screen.getByTestId("ai-rules-escalation-testbench-run"));
    await waitFor(() => {
      const body = _apiMock.post.mock.calls[0][1];
      expect(body.preview_input.test_messages).toHaveLength(5);
      expect(body.preview_input.test_messages).toEqual([
        "one", "two", "three", "four", "five",
      ]);
    });
  });

  it("empty textarea shows toast error and does NOT hit the API", () => {
    render(
      <EscalationRulesCard
        value={RULES}
        overrideMap={{}}
        platformValue={[]}
      />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-escalation-testbench-run"));
    expect(_apiMock.post).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringMatching(/at least one test message/i),
    );
  });

  it("success renders one row per result with match/no-match chips", async () => {
    render(
      <EscalationRulesCard
        value={RULES}
        overrideMap={{}}
        platformValue={[]}
      />,
    );
    fireEvent.change(
      screen.getByTestId("ai-rules-escalation-testbench-input"),
      { target: { value: "refund my last visit\nsee you next week" } },
    );
    fireEvent.click(screen.getByTestId("ai-rules-escalation-testbench-run"));
    await waitFor(() =>
      expect(
        screen.getByTestId("ai-rules-escalation-testbench-results"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("ai-rules-escalation-testbench-result-0"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("ai-rules-escalation-testbench-result-0-match"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("ai-rules-escalation-testbench-result-1-nomatch"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("ai-rules-escalation-testbench-result-0").textContent,
    ).toMatch(/admin/);
  });

  it("malformed-regex warning surfaces as an inline banner", async () => {
    _apiMock.post.mockResolvedValueOnce({
      preview_kind: "escalation_match",
      output: { results: [] },
      warnings: [
        "malformed regex in rule 1: '\\b('",
        "info-only note that should NOT render as a warning",
      ],
    });
    render(
      <EscalationRulesCard
        value={RULES}
        overrideMap={{}}
        platformValue={[]}
      />,
    );
    fireEvent.change(
      screen.getByTestId("ai-rules-escalation-testbench-input"),
      { target: { value: "refund" } },
    );
    fireEvent.click(screen.getByTestId("ai-rules-escalation-testbench-run"));
    await waitFor(() =>
      expect(
        screen.getByTestId("ai-rules-escalation-testbench-warning-0"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("ai-rules-escalation-testbench-warning-1"),
    ).not.toBeInTheDocument();
  });
});
