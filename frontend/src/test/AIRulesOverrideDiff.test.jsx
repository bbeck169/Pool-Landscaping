/**
 * MTH-B · Feb-2026 — Override diff panel tests.
 *
 * Locks:
 *   1. No overrides → the panel renders nothing.
 *   2. Sub-field overrides render one row per override.
 *   3. Whole-category ``escalation_rules`` overrides render a
 *      single "(whole category)" row.
 *   4. "Reset entire category" opens a reason modal and POSTs the
 *      reset endpoint.
 *   5. Per-field revert fallback note is visible when expanded.
 *   6. ``collectOverrides`` returns [] for null overrideMap.
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

import OverrideDiff, {
  collectOverrides,
} from "@/components/ai-rules/OverrideDiff";

describe("MTH-B · OverrideDiff", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.post.mockResolvedValue({ ok: true });
  });

  it("collectOverrides returns [] for null overrideMap", () => {
    expect(collectOverrides("tone_voice", null, {}, {})).toEqual([]);
  });

  it("renders nothing when no tenant override exists", () => {
    const { container } = render(
      <OverrideDiff
        category="tone_voice"
        overrideMap={{
          "tone_voice.style": "platform",
          "tone_voice.custom_directive": "platform",
        }}
        tenantValue={{ style: "friendly", custom_directive: "" }}
        platformValue={{ style: "friendly", custom_directive: "" }}
      />,
    );
    expect(container.textContent).toBe("");
  });

  it("renders one row per tenant-overridden sub-field when expanded", () => {
    render(
      <OverrideDiff
        category="tone_voice"
        overrideMap={{
          "tone_voice.style": "tenant",
          "tone_voice.custom_directive": "platform",
        }}
        tenantValue={{ style: "technical", custom_directive: "" }}
        platformValue={{ style: "friendly", custom_directive: "" }}
      />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-override-diff-toggle"));
    expect(
      screen.getByTestId("ai-rules-override-diff-row-style"),
    ).toBeInTheDocument();
    // Only the tenant-overridden field renders — not the platform-side field.
    expect(
      screen.queryByTestId("ai-rules-override-diff-row-custom_directive"),
    ).not.toBeInTheDocument();
  });

  it("atomic whole-category override renders '(whole category)' row", () => {
    render(
      <OverrideDiff
        category="escalation_rules"
        overrideMap={{ escalation_rules: "tenant" }}
        tenantValue={[{ keyword: "refund" }]}
        platformValue={[]}
      />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-override-diff-toggle"));
    expect(
      screen.getByTestId("ai-rules-override-diff-row-_whole_category_"),
    ).toBeInTheDocument();
  });

  it("Reset entire category POSTs /tenant-ai-rules/reset/{category}", async () => {
    render(
      <OverrideDiff
        category="tone_voice"
        overrideMap={{ "tone_voice.style": "tenant" }}
        tenantValue={{ style: "technical", custom_directive: "" }}
        platformValue={{ style: "friendly", custom_directive: "" }}
      />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-override-diff-toggle"));
    fireEvent.click(
      screen.getByTestId("ai-rules-override-diff-reset-category"),
    );
    fireEvent.change(
      screen.getByTestId("ai-rules-override-diff-reset-reason-input"),
      { target: { value: "clearing overrides" } },
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-override-diff-reset-reason-confirm"),
    );
    await waitFor(() => {
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/tenant-ai-rules/reset/tone_voice",
        { reason: "clearing overrides" },
      );
    });
  });

  it("shows the per-field revert fallback note when expanded", () => {
    render(
      <OverrideDiff
        category="tone_voice"
        overrideMap={{ "tone_voice.style": "tenant" }}
        tenantValue={{ style: "technical" }}
        platformValue={{ style: "friendly" }}
      />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-override-diff-toggle"));
    expect(
      screen.getByTestId("ai-rules-override-diff-per-field-note").textContent,
    ).toMatch(/per-field/i);
  });
});
