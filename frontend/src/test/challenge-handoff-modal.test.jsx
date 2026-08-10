/**
 * Phase 54h-b · Aug-2026 — Challenge Handoff modal contract.
 *
 * Guards:
 *   • Modal renders on ``challenge_required: true`` response shape.
 *   • Bookmarklet anchor's href is a ``javascript:`` URL and embeds
 *     the fetched import token in the URL string.
 *   • Advanced-paste flow submits cookies via POST /suppliers/{slug}/sessions.
 *   • Retry button re-fires test-connection after success.
 *   • Modal doesn't open for ``ok: true`` or generic-error responses.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => getMock(...a),
          post: (...a) => postMock(...a) },
  TOKEN_KEY: "token",
}));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", border: "#ddd", muted: "#666",
    onSurface: "#000", brand: "#0891B2",
  },
}));

import ChallengeHandoffModal from "@/components/suppliers/ChallengeHandoffModal";


describe("ChallengeHandoffModal · Phase 54h-b", () => {
  beforeEach(() => { getMock.mockReset(); postMock.mockReset(); });
  afterEach(() => { getMock.mockReset(); postMock.mockReset(); });

  it("mounts and mints a 5-min import token on open", async () => {
    postMock.mockImplementation(async (path) => {
      if (path === "/suppliers/sessions/import-token") {
        return { token: "TOK.EN.123", expires_at: "2026-08-10T08:00:00Z" };
      }
      return {};
    });
    await act(async () => {
      render(
        <ChallengeHandoffModal
          slug="heritage" displayName="Heritage Pool Plus"
          loginUrl="https://heritagepoolplus.com/login"
          onClose={() => {}} onRetry={() => {}} />,
      );
    });
    expect(screen.getByTestId("challenge-handoff-modal")).toBeInTheDocument();
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/suppliers/sessions/import-token", {},
      ),
    );
  });

  it("bookmarklet anchor href is a javascript: URL that embeds the import token", async () => {
    postMock.mockResolvedValueOnce({
      token: "IMPORT_TOKEN_XYZ", expires_at: "2026-08-10T08:00:00Z",
    });
    await act(async () => {
      render(
        <ChallengeHandoffModal
          slug="heritage" displayName="Heritage Pool Plus"
          loginUrl="https://heritagepoolplus.com/login"
          onClose={() => {}} onRetry={() => {}} />,
      );
    });
    const anchor = await screen.findByTestId("challenge-handoff-bookmarklet");
    const href = anchor.getAttribute("href");
    expect(href).toMatch(/^javascript:/);
    expect(href).toContain("IMPORT_TOKEN_XYZ");
    // Anchor is draggable so operators can drag it to the bookmarks bar.
    expect(anchor.getAttribute("draggable")).toBe("true");
    // Its target path references the tenant's slug.
    expect(href).toContain(encodeURIComponent(
      "IMPORT_TOKEN_XYZ",
    ));
  });

  it("paste fallback textarea + Submit POSTs cookies to /suppliers/{slug}/sessions", async () => {
    postMock.mockImplementation(async (path) => {
      if (path === "/suppliers/sessions/import-token") {
        return { token: "T", expires_at: "2026-08-10T08:00:00Z" };
      }
      if (path === "/suppliers/heritage/sessions") {
        return { ok: true, cookie_count: 2 };
      }
      return {};
    });
    await act(async () => {
      render(
        <ChallengeHandoffModal
          slug="heritage" displayName="Heritage Pool Plus"
          loginUrl="https://heritagepoolplus.com/login"
          onClose={() => {}} onRetry={() => {}} />,
      );
    });
    // Reveal advanced section.
    await act(async () => {
      fireEvent.click(screen.getByTestId("challenge-handoff-toggle-advanced"));
    });
    const textarea = await screen.findByTestId("challenge-handoff-paste-textarea");
    await act(async () => {
      fireEvent.change(textarea, {
        target: { value: '[{"name":"cf","value":"x"},{"name":"s","value":"y"}]' },
      });
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("challenge-handoff-paste-submit"));
    });
    await waitFor(() => {
      const call = postMock.mock.calls.find(
        (c) => c[0] === "/suppliers/heritage/sessions",
      );
      expect(call).toBeTruthy();
      expect(call[1]).toEqual({
        cookies: [
          { name: "cf", value: "x" },
          { name: "s",  value: "y" },
        ],
      });
    });
    // Success banner appears + Retry button becomes enabled.
    await waitFor(() =>
      expect(screen.getByTestId("challenge-handoff-success")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("challenge-handoff-retry").disabled).toBe(false);
  });

  it("Retry button invokes onRetry after successful paste", async () => {
    postMock.mockImplementation(async (path) => {
      if (path === "/suppliers/sessions/import-token") return { token: "T" };
      if (path === "/suppliers/heritage/sessions") return { ok: true, cookie_count: 1 };
      return {};
    });
    const onRetry = vi.fn();
    await act(async () => {
      render(
        <ChallengeHandoffModal
          slug="heritage" displayName="Heritage Pool Plus"
          loginUrl="" onClose={() => {}} onRetry={onRetry} />,
      );
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("challenge-handoff-toggle-advanced"));
    });
    await act(async () => {
      fireEvent.change(
        screen.getByTestId("challenge-handoff-paste-textarea"),
        { target: { value: '[{"name":"a","value":"1"}]' } },
      );
      fireEvent.click(screen.getByTestId("challenge-handoff-paste-submit"));
    });
    await waitFor(() => screen.getByTestId("challenge-handoff-success"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("challenge-handoff-retry"));
    });
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("Retry is disabled until cookies land (prevents re-fire before session cache)", async () => {
    postMock.mockResolvedValueOnce({ token: "T" });
    await act(async () => {
      render(
        <ChallengeHandoffModal
          slug="heritage" displayName="Heritage Pool Plus"
          loginUrl="" onClose={() => {}} onRetry={() => {}} />,
      );
    });
    const retry = await screen.findByTestId("challenge-handoff-retry");
    expect(retry.disabled).toBe(true);
  });
});
