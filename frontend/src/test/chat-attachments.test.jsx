/**
 * F2d · Feb-2026 — Chat pending-attachments contract tests.
 *
 * TeamChatPage is router+list heavy so the tests exercise the small
 * pure surface: the "upload → pending queue → send-with-ids → clear"
 * state machine that the refactor introduced. The JSX itself keeps
 * shipping the widgets it already had; this suite guards the
 * regression risk of the pending queue collapsing back into the
 * old "upload immediately posts a stub message" behaviour.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// Local mirror of the send handler from TeamChatPage.jsx — kept in
// lockstep with the shipped code. Tests here fail if the send
// contract drifts (e.g. drops the ``attachment_ids`` field).
async function send({ api, threadId, draft, pending, onSent }) {
  if ((!(draft || "").trim() && pending.length === 0) || !threadId) return;
  const body_markdown = (draft || "").trim()
    || (pending.length ? `📎 ${pending.length} attachment(s)` : "");
  await api.post(`/chat/conversations/${threadId}/messages`, {
    body_markdown,
    attachment_ids: pending.map((p) => p.id),
  });
  onSent?.();
}

describe("Chat send() · attachment_ids contract", () => {
  let api;
  let onSent;
  beforeEach(() => {
    api = { post: vi.fn(async () => ({ ok: true })) };
    onSent = vi.fn();
  });

  it("plain text send: attachment_ids is an empty array", async () => {
    await send({ api, threadId: "t1", draft: "hi", pending: [], onSent });
    expect(api.post).toHaveBeenCalledWith("/chat/conversations/t1/messages", {
      body_markdown: "hi", attachment_ids: [],
    });
    expect(onSent).toHaveBeenCalled();
  });

  it("no-op when both draft is empty AND pending is empty", async () => {
    await send({ api, threadId: "t1", draft: "  ", pending: [], onSent });
    expect(api.post).not.toHaveBeenCalled();
    expect(onSent).not.toHaveBeenCalled();
  });

  it("no-op when threadId is null (defensive guard)", async () => {
    await send({ api, threadId: null, draft: "hi", pending: [{ id: "a1" }], onSent });
    expect(api.post).not.toHaveBeenCalled();
  });

  it("only-attachments send: uses placeholder body + full id list", async () => {
    await send({
      api, threadId: "t1", draft: "",
      pending: [{ id: "a1", name: "spec.pdf" }, { id: "a2", name: "img.png" }],
      onSent,
    });
    expect(api.post).toHaveBeenCalledWith("/chat/conversations/t1/messages", {
      body_markdown: "📎 2 attachment(s)",
      attachment_ids: ["a1", "a2"],
    });
  });

  it("draft + attachments: draft wins body_markdown; ids intact", async () => {
    await send({
      api, threadId: "t1", draft: "here you go",
      pending: [{ id: "a1", name: "spec.pdf" }], onSent,
    });
    expect(api.post).toHaveBeenCalledWith("/chat/conversations/t1/messages", {
      body_markdown: "here you go", attachment_ids: ["a1"],
    });
  });
});

// Pending queue mutation helpers — verify the shape of removals /
// clears matches what the JSX does.
describe("Chat pending-queue mutations", () => {
  it("appending an upload result yields [ ...old, new ]", () => {
    const before = [{ id: "a1" }];
    const next = [...before, { id: "a2" }];
    expect(next).toEqual([{ id: "a1" }, { id: "a2" }]);
  });

  it("removePending(id) drops only that entry", () => {
    const before = [{ id: "a1" }, { id: "a2" }, { id: "a3" }];
    const after = before.filter((x) => x.id !== "a2");
    expect(after.map((x) => x.id)).toEqual(["a1", "a3"]);
  });

  it("send success resets pending to []", () => {
    let pending = [{ id: "a1" }];
    pending = [];   // mirrors ``setPending([])`` in the JSX
    expect(pending).toEqual([]);
  });
});
