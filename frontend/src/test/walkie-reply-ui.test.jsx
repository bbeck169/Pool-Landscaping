/**
 * Phase 51.6 · Feb-2026 — Walkie visible reply UI wiring (mount test).
 *
 * Locks the actual page-level render: Reply action button visible on
 * each row for permitted callers, "Replying to X" banner appears
 * after clicking Reply, banner cancel clears state, inline
 * ``walkie-reply-preview`` block renders on reply rows (with the
 * deleted-parent placeholder when applicable).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u_admin", role: "admin", name: "Alice" } }),
}));

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(async () => ({ ok: true })),
    del: vi.fn(async () => ({ ok: true })),
  },
  api_base: () => "https://example.test/api",
  TOKEN_KEY: "walkie_test_token",
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Silence the media APIs — the record button never fires in this test.
Object.defineProperty(global, "MediaRecorder", {
  value: class { start(){} stop(){} },
  writable: true,
});

const { api } = await import("@/api");
const { default: Walkie } = await import("@/pages/walkie/Walkie");

const CHANNEL = { id: "ch_ah", kind: "all_hands" };
const PARENT = {
  id: "m_parent", channel_id: "ch_ah", sender_user_id: "u_other", sender_name: "Bob",
  audio_url: "/files/a/download", duration_ms: 3400,
  created_at: "2026-02-07T10:00:00Z", is_pinned: false,
};
const REPLY_LIVE = {
  id: "m_reply1", channel_id: "ch_ah", sender_user_id: "u_admin", sender_name: "Alice",
  audio_url: "/files/b/download", duration_ms: 2000,
  created_at: "2026-02-07T10:05:00Z", is_pinned: false,
  reply_to_message_id: "m_parent",
  reply_preview: { id: "m_parent", sender_user_id: "u_other", sender_display_name: "Bob", duration_ms: 3400, deleted: false },
};
const REPLY_DEAD = {
  id: "m_reply2", channel_id: "ch_ah", sender_user_id: "u_admin", sender_name: "Alice",
  audio_url: "/files/c/download", duration_ms: 1500,
  created_at: "2026-02-07T10:10:00Z", is_pinned: false,
  reply_to_message_id: "m_ghost",
  reply_preview: { id: null, sender_user_id: null, sender_display_name: null, duration_ms: null, deleted: true },
};

beforeEach(() => {
  cleanup();
  api.get.mockReset();
  api.get.mockImplementation(async (path) => {
    if (path === "/walkie/channels") return { channels: [CHANNEL] };
    if (path.startsWith("/walkie/messages")) {
      return { messages: [REPLY_DEAD, REPLY_LIVE, PARENT] };  // desc order
    }
    return { messages: [] };
  });
});

describe("Phase 51.6 · Walkie visible reply UI", () => {
  it("renders a Reply action button on every message row for a permitted caller", async () => {
    render(<Walkie />);
    await waitFor(() => expect(screen.getByTestId(`walkie-reply-btn-${PARENT.id}`)).toBeTruthy());
    expect(screen.getByTestId(`walkie-reply-btn-${REPLY_LIVE.id}`)).toBeTruthy();
    expect(screen.getByTestId(`walkie-reply-btn-${REPLY_DEAD.id}`)).toBeTruthy();
  });

  it("clicking Reply shows the 'Replying to X' banner and cancel clears it", async () => {
    render(<Walkie />);
    const btn = await screen.findByTestId(`walkie-reply-btn-${PARENT.id}`);
    fireEvent.click(btn);
    const banner = await screen.findByTestId("walkie-reply-banner");
    expect(banner).toBeTruthy();
    const label = screen.getByTestId("walkie-reply-banner-label").textContent || "";
    // Bob is the parent sender_name, duration 3400ms → 3s.
    expect(label).toContain("Bob");
    expect(label).toContain("3s");
    // Cancel clears the banner.
    fireEvent.click(screen.getByTestId("walkie-reply-banner-cancel"));
    await waitFor(() => expect(screen.queryByTestId("walkie-reply-banner")).toBeNull());
  });

  it("reply rows render the inline walkie-reply-preview block with the correct label", async () => {
    render(<Walkie />);
    // Wait for the timeline to render.
    await screen.findByTestId(`walkie-reply-btn-${REPLY_LIVE.id}`);
    // Two reply-preview nodes must render (one live, one deleted).
    const previews = screen.getAllByTestId("walkie-reply-preview");
    expect(previews.length).toBe(2);
    // Live preview shows "Bob · 3s". Deleted preview shows placeholder.
    const texts = previews.map((el) => el.textContent || "");
    expect(texts.some((t) => t.includes("Bob") && t.includes("3s"))).toBe(true);
    expect(texts.some((t) => t.includes("(original message deleted)"))).toBe(true);
  });

  it("deleted-parent reply preview is marked with data-deleted=1", async () => {
    render(<Walkie />);
    await screen.findByTestId(`walkie-reply-btn-${REPLY_DEAD.id}`);
    const previews = screen.getAllByTestId("walkie-reply-preview");
    const deleted = previews.find((el) => el.getAttribute("data-deleted") === "1");
    expect(deleted).toBeTruthy();
    expect(deleted?.textContent || "").toContain("(original message deleted)");
  });
});
