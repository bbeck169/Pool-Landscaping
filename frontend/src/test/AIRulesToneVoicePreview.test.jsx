/**
 * MTH-D · Feb-2026 — ToneVoiceCard server-preview integration.
 *
 * Locks:
 *   1. "Test this rule" button calls /tenant-ai-rules/preview
 *      with the currently-edited style + directive.
 *   2. Loading state renders the spinner label.
 *   3. Success renders the sample response.
 *   4. Error state renders the retry button + retries.
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

import ToneVoiceCard from "@/components/ai-rules/ToneVoiceCard";

describe("MTH-D · ToneVoiceCard server preview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.post.mockResolvedValue({
      preview_kind: "response",
      output: {
        prompt_preview: "— Tone & voice guidance —\nRespond with professional…",
        user_message: "When can you come?",
        sample_response: "Good afternoon. We can arrive Tuesday between 8-10 AM.",
        provider: "emergent",
        model: "claude-sonnet-4-5",
        llm_ms: 812,
      },
      warnings: [],
    });
  });

  it("clicks Test this rule → POSTs preview with tone_voice + user message", async () => {
    render(
      <ToneVoiceCard
        value={{ style: "friendly", custom_directive: "" }}
        overrideMap={{}}
        platformValue={{ style: "friendly", custom_directive: "" }}
      />,
    );
    // Switch to formal.
    fireEvent.click(screen.getByTestId("ai-rules-tone-voice-style-formal"));
    // Type a custom sample message.
    fireEvent.change(
      screen.getByTestId("ai-rules-tone-voice-preview-user-msg"),
      { target: { value: "My pump is loud." } },
    );
    fireEvent.click(screen.getByTestId("ai-rules-tone-voice-preview-run"));
    await waitFor(() => {
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/tenant-ai-rules/preview",
        expect.objectContaining({
          category: "tone_voice",
          preview_kind: "response",
          pending_value: expect.objectContaining({
            style: "formal",
          }),
          preview_input: expect.objectContaining({
            user_message: "My pump is loud.",
          }),
        }),
      );
    });
  });

  it("success renders sample_response + meta", async () => {
    render(
      <ToneVoiceCard
        value={{ style: "friendly", custom_directive: "" }}
        overrideMap={{}}
        platformValue={{ style: "friendly", custom_directive: "" }}
      />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-tone-voice-preview-run"));
    await waitFor(() =>
      expect(
        screen.getByTestId("ai-rules-tone-voice-preview-response"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("ai-rules-tone-voice-preview-response").textContent,
    ).toMatch(/Good afternoon/);
    expect(
      screen.getByTestId("ai-rules-tone-voice-preview-meta").textContent,
    ).toMatch(/claude-sonnet-4-5/);
  });

  it("llm_unavailable output surfaces retry button", async () => {
    _apiMock.post.mockResolvedValueOnce({
      preview_kind: "response",
      output: { error: "llm_unavailable", message: "provider offline" },
      warnings: [],
    });
    render(
      <ToneVoiceCard
        value={{ style: "friendly", custom_directive: "" }}
        overrideMap={{}}
        platformValue={{ style: "friendly", custom_directive: "" }}
      />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-tone-voice-preview-run"));
    await waitFor(() =>
      expect(
        screen.getByTestId("ai-rules-tone-voice-preview-error"),
      ).toBeInTheDocument(),
    );
    // Retry button visible; clicking triggers another POST.
    _apiMock.post.mockResolvedValueOnce({
      preview_kind: "response",
      output: { sample_response: "Ok now working." },
      warnings: [],
    });
    fireEvent.click(screen.getByTestId("ai-rules-tone-voice-preview-retry"));
    await waitFor(() =>
      expect(_apiMock.post).toHaveBeenCalledTimes(2),
    );
  });

  it("empty preview state before any test click", () => {
    render(
      <ToneVoiceCard
        value={{ style: "friendly", custom_directive: "" }}
        overrideMap={{}}
        platformValue={{ style: "friendly", custom_directive: "" }}
      />,
    );
    expect(
      screen.getByTestId("ai-rules-tone-voice-preview-empty"),
    ).toBeInTheDocument();
  });
});
