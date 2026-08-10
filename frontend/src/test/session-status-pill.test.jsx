/**
 * Phase 54h-d · Aug-2026 — Session status pill + Clear action.
 *
 * Guards:
 *   • Green pill when ``minutes_remaining > 10``.
 *   • Amber pill + Retry link when ``0 < minutes_remaining <= 10``.
 *   • No pill when ``has_active_session: false``.
 *   • Clear action fires DELETE then refetches status.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";

const getMock = vi.fn();
const delMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    del: (...a) => delMock(...a),
    post: vi.fn(),
    patch: vi.fn(),
  },
  TOKEN_KEY: "token",
}));
vi.mock("@/theme", () => ({
  colors: { surface: "#fff", border: "#ddd", muted: "#666",
             onSurface: "#000", brand: "#0891B2" },
}));

import SessionStatusPill from "@/components/suppliers/SessionStatusPill";


describe("SessionStatusPill · Phase 54h-d", () => {
  beforeEach(() => { getMock.mockReset(); delMock.mockReset(); });
  afterEach(() => { getMock.mockReset(); delMock.mockReset(); });

  it("renders GREEN pill when minutes_remaining > 10 (locked at 25)", async () => {
    getMock.mockResolvedValueOnce({
      supplier_slug: "heritage",
      has_active_session: true,
      expires_at: "2026-08-10T08:25:00Z",
      minutes_remaining: 25,
    });
    await act(async () => {
      render(<SessionStatusPill slug="heritage"
                                   displayName="Heritage Pool Plus"
                                   canManage={true}
                                   onRetry={() => {}} />);
    });
    const pill = await screen.findByTestId("session-status-pill-heritage");
    expect(pill.getAttribute("data-tier")).toBe("green");
    expect(pill.textContent).toBe("Session cached · 25m left");
    // Retry link is amber-only.
    expect(screen.queryByTestId("session-status-retry-heritage"))
      .not.toBeInTheDocument();
  });

  it("renders AMBER pill + Retry link when minutes_remaining <= 10 (locked at 5)", async () => {
    getMock.mockResolvedValueOnce({
      supplier_slug: "heritage",
      has_active_session: true,
      expires_at: "2026-08-10T08:05:00Z",
      minutes_remaining: 5,
    });
    const onRetry = vi.fn();
    await act(async () => {
      render(<SessionStatusPill slug="heritage"
                                   displayName="Heritage Pool Plus"
                                   canManage={true}
                                   onRetry={onRetry} />);
    });
    const pill = await screen.findByTestId("session-status-pill-heritage");
    expect(pill.getAttribute("data-tier")).toBe("amber");
    expect(pill.textContent).toBe("Session expiring in 5m");
    // Retry link IS present + wires to onRetry callback.
    const retry = screen.getByTestId("session-status-retry-heritage");
    await act(async () => { fireEvent.click(retry); });
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders NO pill when has_active_session=false (silent)", async () => {
    getMock.mockResolvedValueOnce({
      supplier_slug: "heritage",
      has_active_session: false,
      expires_at: null,
      minutes_remaining: null,
    });
    await act(async () => {
      render(<SessionStatusPill slug="heritage"
                                   displayName="Heritage Pool Plus"
                                   canManage={true}
                                   onRetry={() => {}} />);
    });
    // Wait for the GET to resolve.
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(screen.queryByTestId("session-status-heritage"))
      .not.toBeInTheDocument();
    expect(screen.queryByTestId("session-status-pill-heritage"))
      .not.toBeInTheDocument();
  });

  it("Clear session action fires DELETE + refetches status", async () => {
    // First status call: green (active). After DELETE: no session.
    getMock.mockImplementation(async () => {
      if (delMock.mock.calls.length === 0) {
        return { has_active_session: true, minutes_remaining: 25,
                  expires_at: "2026-08-10T08:25:00Z" };
      }
      return { has_active_session: false, minutes_remaining: null,
                expires_at: null };
    });
    delMock.mockResolvedValueOnce({ ok: true, deleted: 1 });
    await act(async () => {
      render(<SessionStatusPill slug="heritage"
                                   displayName="Heritage Pool Plus"
                                   canManage={true}
                                   onRetry={() => {}} />);
    });
    await screen.findByTestId("session-status-pill-heritage");
    // Click trash → confirmation modal opens.
    await act(async () => {
      fireEvent.click(screen.getByTestId("session-status-clear-heritage"));
    });
    await screen.findByTestId("session-status-clear-confirm-heritage");
    // Confirm → DELETE fires + pill disappears after re-fetch.
    await act(async () => {
      fireEvent.click(
        screen.getByTestId("session-status-clear-confirm-btn-heritage"),
      );
    });
    await waitFor(() =>
      expect(delMock).toHaveBeenCalledWith("/suppliers/heritage/sessions"),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("session-status-pill-heritage"))
        .not.toBeInTheDocument(),
    );
  });
});
