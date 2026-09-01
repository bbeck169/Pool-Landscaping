/**
 * Phase K8 · Feb-2026 — Portal chat bubble sender-name contract.
 *
 * Bug reproduced verbatim: portal user Brian Beckman was logged in
 * with a drifted auth-context ``user.name = "Jennifer Carson"``, and
 * the server (after the fix) stamps ``message.sender_name`` from the
 * CUSTOMER record ("Brian Beckman") — NOT from the user auth
 * context.  This test locks the CLIENT render contract in place so
 * a future refactor can't regress by falling back to
 * ``thread.customer_name`` or ``user.name`` from useAuth.
 *
 * Assertions
 *   1. Bubble renders ``message.sender_name`` verbatim.
 *   2. Bubble does NOT render the auth-context ``user.name``
 *      (which is the buggy value from the reported screenshot).
 *   3. Bubble does NOT fall back to ``thread.customer_name``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, postSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
  },
  TOKEN_KEY: "access_token",
}));

// Auth context deliberately carries the WRONG name — the drifted
// value from the bug report.  If the bubble reads user.name for
// mine === true rows, this test fails and we've regressed.
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: {
      id: "portal-user-brian",
      role: "customer",
      customer_id: "cust-brian",
      name: "Jennifer Carson", // ← drifted, per bug report
    },
  }),
}));

// Neutralize the shared attachment tile — irrelevant to this test.
vi.mock("@/components/chat/ChatAttachmentTile", () => ({
  ChatAttachmentTile: () => null,
}));

beforeEach(() => {
  getSpy.mockReset();
  postSpy.mockReset();
  global.localStorage.setItem("access_token", "t");
});
afterEach(() => cleanup());

import PortalChatsPage from "@/pages/portal/PortalChatsPage";

describe("PortalChatsPage · K8 sender-name contract", () => {
  it("bubble renders message.sender_name (Brian Beckman), NOT user.name (Jennifer Carson) or thread.customer_name", async () => {
    getSpy.mockImplementation((path) => {
      if (path === "/portal/chats") {
        return Promise.resolve([
          {
            id: "chat-K8",
            subject: "test",
            // Even the thread customer_name is intentionally misleading
            // to prove the bubble doesn't fall back to it.
            customer_name: "Not The Sender",
            unread_by_admin: 0,
            unread_by_customer: 0,
            last_message_at: "2026-09-01",
          },
        ]);
      }
      if (path.startsWith("/portal/chats/chat-K8/messages")) {
        return Promise.resolve({
          chat: { id: "chat-K8" },
          messages: [
            {
              id: "m-K8-1",
              sender_role: "customer",
              // Server-derived canonical name (post-K8 fix).
              sender_name: "Brian Beckman",
              body: "test",
              created_at: "2026-09-01T00:00:00Z",
              attachments: [],
            },
          ],
        });
      }
      return Promise.resolve([]);
    });
    postSpy.mockResolvedValue({ ok: true });

    render(<PortalChatsPage />);

    // Open the thread.
    await waitFor(() =>
      expect(screen.getByTestId("chat-thread-chat-K8")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("chat-thread-chat-K8"));

    // Wait for the message bubble to mount.
    await waitFor(() =>
      expect(screen.getByTestId("portal-chat-msg-m-K8-1")).toBeInTheDocument(),
    );
    const bubble = screen.getByTestId("portal-chat-msg-m-K8-1");
    expect(bubble.textContent).toContain("Brian Beckman");
    expect(bubble.textContent).not.toContain("Jennifer Carson");
    expect(bubble.textContent).not.toContain("Not The Sender");
  });
});
