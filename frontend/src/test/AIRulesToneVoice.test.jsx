/**
 * MTH-B · Feb-2026 — Tone & Voice card tests.
 *
 * Locks:
 *   1. Radio + textarea render with the passed value.
 *   2. Save routes to ``PUT /api/tenant-ai-rules/tone_voice`` with
 *      ``{value: {style, custom_directive}, reason}``.
 *   3. Reset routes to ``POST /api/tenant-ai-rules/reset/tone_voice``.
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

import ToneVoiceCard from "@/components/ai-rules/ToneVoiceCard";

describe("MTH-B · ToneVoiceCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.put.mockResolvedValue({ ok: true });
    _apiMock.post.mockResolvedValue({ ok: true });
  });

  it("renders the selected style + directive from props", () => {
    render(
      <ToneVoiceCard
        value={{ style: "technical", custom_directive: "always cite ppm ranges" }}
        overrideMap={{}}
        platformValue={{ style: "friendly", custom_directive: "" }}
      />,
    );
    const radio = screen.getByTestId("ai-rules-tone-voice-style-technical");
    expect(radio.checked).toBe(true);
    const ta = screen.getByTestId("ai-rules-tone-voice-directive");
    expect(ta.value).toBe("always cite ppm ranges");
  });

  it("save flow: opens modal, requires 8-char reason, calls PUT", async () => {
    render(
      <ToneVoiceCard
        value={{ style: "friendly", custom_directive: "" }}
        overrideMap={{}}
        platformValue={{ style: "friendly", custom_directive: "" }}
      />,
    );
    // Switch style to formal.
    fireEvent.click(screen.getByTestId("ai-rules-tone-voice-style-formal"));
    fireEvent.click(screen.getByTestId("ai-rules-tone-voice-save"));
    fireEvent.change(
      screen.getByTestId("ai-rules-tone-voice-save-reason-input"),
      { target: { value: "onboarding review" } },
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-tone-voice-save-reason-confirm"),
    );
    await waitFor(() => {
      expect(_apiMock.put).toHaveBeenCalledWith(
        "/tenant-ai-rules/tone_voice",
        {
          value: { style: "formal", custom_directive: "" },
          reason: "onboarding review",
        },
      );
    });
  });

  it("reset flow: calls POST /reset with reason", async () => {
    render(
      <ToneVoiceCard
        value={{ style: "friendly", custom_directive: "" }}
        overrideMap={{ "tone_voice.style": "tenant" }}
        platformValue={{ style: "formal", custom_directive: "" }}
      />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-tone-voice-reset"));
    fireEvent.change(
      screen.getByTestId("ai-rules-tone-voice-reset-reason-input"),
      { target: { value: "restoring platform default" } },
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-tone-voice-reset-reason-confirm"),
    );
    await waitFor(() => {
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/tenant-ai-rules/reset/tone_voice",
        { reason: "restoring platform default" },
      );
    });
  });
});
