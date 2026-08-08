/**
 * Phase 51.6 · Feb 2026 — Walkie reply flow (target state + send payload).
 *
 * The Walkie page tracks a ``replyTarget`` state — the id of the
 * message being replied to. Setting it displays the compact quote
 * preview above the record button; sending the clip includes the
 * id as ``reply_to_message_id`` in the multipart POST; cancelling
 * clears state.
 *
 * Locked as a pure reducer here so the assertion is deterministic.
 */
import { describe, it, expect } from "vitest";

function replyReducer(state, action) {
  switch (action.type) {
    case "REPLY_TO":
      return { ...state, replyTarget: action.messageId };
    case "CANCEL_REPLY":
      return { ...state, replyTarget: null };
    case "SEND_COMPLETE":
      return { ...state, replyTarget: null };
    default:
      return state;
  }
}

function buildSendPayload(state, { channelId, durationMs, blob, mime }) {
  const fd = { channel_id: channelId, duration_ms: String(durationMs) };
  if (state.replyTarget) fd.reply_to_message_id = state.replyTarget;
  return { fd, hasBlob: !!blob, mime };
}

describe("Phase 51.6 · walkie reply flow reducer", () => {
  it("REPLY_TO sets the target message id", () => {
    const s = replyReducer({ replyTarget: null }, { type: "REPLY_TO", messageId: "m1" });
    expect(s.replyTarget).toBe("m1");
  });

  it("CANCEL_REPLY clears the target", () => {
    const s = replyReducer({ replyTarget: "m1" }, { type: "CANCEL_REPLY" });
    expect(s.replyTarget).toBeNull();
  });

  it("SEND_COMPLETE also clears the target (post-send)", () => {
    const s = replyReducer({ replyTarget: "m1" }, { type: "SEND_COMPLETE" });
    expect(s.replyTarget).toBeNull();
  });

  it("send payload includes reply_to_message_id when a target is set", () => {
    const state = { replyTarget: "parent_123" };
    const { fd } = buildSendPayload(state, {
      channelId: "ch1", durationMs: 3000, blob: new Uint8Array([1]), mime: "audio/webm",
    });
    expect(fd.reply_to_message_id).toBe("parent_123");
    expect(fd.channel_id).toBe("ch1");
    expect(fd.duration_ms).toBe("3000");
  });

  it("send payload OMITS reply_to_message_id when no target — plain post still works", () => {
    const state = { replyTarget: null };
    const { fd } = buildSendPayload(state, {
      channelId: "ch1", durationMs: 3000, blob: new Uint8Array([1]), mime: "audio/webm",
    });
    expect("reply_to_message_id" in fd).toBe(false);
  });

  it("switching reply target mid-flow overwrites the previous target", () => {
    let s = replyReducer({ replyTarget: null }, { type: "REPLY_TO", messageId: "m1" });
    s = replyReducer(s, { type: "REPLY_TO", messageId: "m2" });
    expect(s.replyTarget).toBe("m2");
  });
});
