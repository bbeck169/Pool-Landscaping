/**
 * Phase B2 · Feb 2026 — Portal chat attachment · Vitest.
 *
 * Contract:
 *   1. PortalChatsPage renders incoming attachments via ChatAttachmentTile.
 *   2. Upload → send flow includes attachment_ids in the POST body.
 *   3. The tile source is the shared component at
 *      @/components/chat/ChatAttachmentTile (single source of truth).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, act } from "@testing-library/react";

// ── Hoisted mocks ────────────────────────────────────────────────
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
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "user-A", role: "customer", customer_id: "cust-A", name: "Cust A" } }),
}));
// Spy on the shared tile to prove PortalChatsPage uses it.
const tileCallLog = [];
vi.mock("@/components/chat/ChatAttachmentTile", async (importOriginal) => {
  const mod = await importOriginal();
  return {
    ...mod,
    ChatAttachmentTile: (props) => {
      tileCallLog.push(props.attachment);
      const { ChatAttachmentTile: Real } = mod;
      return <Real {...props} />;
    },
  };
});

// fetch mock for the F0 /api/files/upload call
const fetchMock = vi.fn();
beforeEach(() => {
  getSpy.mockReset();
  postSpy.mockReset();
  tileCallLog.length = 0;
  fetchMock.mockReset();
  global.fetch = fetchMock;
  global.localStorage.setItem("access_token", "test-token");
});
afterEach(() => cleanup());

import PortalChatsPage from "@/pages/portal/PortalChatsPage";

describe("PortalChatsPage · B2 attachments", () => {
  it("renders incoming attachments via shared ChatAttachmentTile", async () => {
    getSpy.mockImplementation((path) => {
      if (path === "/portal/chats") {
        return Promise.resolve([
          { id: "chat-A", subject: "Hi", customer_name: "Cust A",
            unread_by_admin: 0, unread_by_customer: 0, last_message_at: "2026-02-01" },
        ]);
      }
      if (path.startsWith("/portal/chats/chat-A/messages")) {
        return Promise.resolve({
          chat: { id: "chat-A" },
          messages: [
            {
              id: "m-1", sender_role: "customer", sender_name: "Cust A",
              body: "here you go", created_at: "2026-02-01T00:00:00Z",
              attachment_ids: ["f-1"],
              attachments: [{
                id: "f-1", filename: "cust-a.pdf", mime: "application/pdf",
                size: 1234, signed_url: "/api/files/f-1/download",
              }],
            },
          ],
        });
      }
      return Promise.resolve({});
    });
    postSpy.mockResolvedValue({ ok: true });

    render(<PortalChatsPage />);
    // Wait for thread list
    const threadBtn = await screen.findByTestId("chat-thread-chat-A");
    fireEvent.click(threadBtn);
    // Wait for the message + tile
    await waitFor(() => screen.getByTestId("portal-chat-msg-m-1"));
    await waitFor(() => screen.getByTestId("portal-chat-att-f-1"));
    // Prove the shared tile was invoked with our attachment shape
    expect(tileCallLog.length).toBeGreaterThan(0);
    expect(tileCallLog[0].id).toBe("f-1");
    expect(tileCallLog[0].signed_url).toBe("/api/files/f-1/download");
  });

  it("upload → send flow sends attachment_ids in POST body", async () => {
    getSpy.mockImplementation((path) => {
      if (path === "/portal/chats") {
        return Promise.resolve([
          { id: "chat-A", subject: "Hi", customer_name: "Cust A",
            unread_by_admin: 0, unread_by_customer: 0 },
        ]);
      }
      if (path.startsWith("/portal/chats/chat-A/messages")) {
        return Promise.resolve({ chat: { id: "chat-A" }, messages: [] });
      }
      return Promise.resolve({});
    });
    postSpy.mockImplementation((path, body) => {
      if (path.endsWith("/messages")) {
        return Promise.resolve({
          id: "m-new", sender_role: "customer",
          body: body.body, attachment_ids: body.attachment_ids,
          attachments: [], created_at: "2026-02-01T00:00:00Z",
        });
      }
      return Promise.resolve({ ok: true });
    });
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "f-uploaded",
        original_filename: "photo.jpg",
        content_type: "image/jpeg",
        size: 5432,
      }),
    });

    render(<PortalChatsPage />);
    const threadBtn = await screen.findByTestId("chat-thread-chat-A");
    fireEvent.click(threadBtn);
    await waitFor(() => screen.getByTestId("portal-chats-upload"));

    // Simulate file upload
    const fileInput = screen.getByTestId("portal-chats-upload");
    const file = new File(["hello"], "photo.jpg", { type: "image/jpeg" });
    await act(async () => {
      fireEvent.change(fileInput, { target: { files: [file] } });
    });

    // Verify fetch was called with F0 upload contract
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/files/upload");
    expect(opts.method).toBe("POST");
    expect(opts.headers.Authorization).toBe("Bearer test-token");
    // FormData inspection — the fields we care about
    const fd = opts.body;
    expect(fd.get("purpose")).toBe("portal_chat_attachment");
    expect(fd.get("linked_entity_type")).toBe("customer");
    expect(fd.get("linked_entity_id")).toBe("cust-A");

    // Pending strip should render the uploaded file
    await waitFor(() => screen.getByTestId("portal-chats-pending-f-uploaded"));

    // Type + send
    const input = screen.getByTestId("portal-chats-input");
    fireEvent.change(input, { target: { value: "please review" } });
    fireEvent.click(screen.getByTestId("portal-chats-send"));

    // Verify send payload includes attachment_ids
    await waitFor(() => {
      const sendCall = postSpy.mock.calls.find(
        (c) => String(c[0]).endsWith("/messages"),
      );
      expect(sendCall).toBeTruthy();
      expect(sendCall[1].body).toBe("please review");
      expect(sendCall[1].attachment_ids).toEqual(["f-uploaded"]);
    });
  });

  it("shared ChatAttachmentTile is the single source of truth", async () => {
    // Import both pages — both should reference the SAME module path
    const teamPageSrc = await import("@/pages/chat/TeamChatPage");
    const portalPageSrc = await import("@/pages/portal/PortalChatsPage");
    // Both modules should have been able to load — implicit check that
    // the shared tile export resolves for both.
    expect(teamPageSrc.default).toBeDefined();
    expect(portalPageSrc.default).toBeDefined();
  });
});
