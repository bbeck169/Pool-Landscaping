/**
 * Phase 51.6 · Feb-2026 — Mobile walkie reply-preview render contract.
 *
 * Mirror of ``walkie-reply-render.test.jsx``. Same shape,
 * same placeholder string, same duration floor.
 */
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async () => null),
  setItem: jest.fn(async () => undefined),
  removeItem: jest.fn(async () => undefined),
  clear: jest.fn(async () => undefined),
}));

// eslint-disable-next-line import/first
import { normalizeReplyPreview, replyPreviewLabel } from "@/src/pages/walkie/walkie-helpers";

describe("Phase 51.6 · mobile normalizeReplyPreview", () => {
  it("returns null for missing / undefined preview", () => {
    expect(normalizeReplyPreview(null)).toBeNull();
    expect(normalizeReplyPreview(undefined)).toBeNull();
  });

  it("normalises a live parent to a fully-populated object", () => {
    expect(normalizeReplyPreview({
      id: "m1", sender_user_id: "u1", sender_display_name: "Alice",
      duration_ms: 3400, deleted: false,
    })).toEqual({ deleted: false, id: "m1", sender_display_name: "Alice", duration_ms: 3400 });
  });

  it("normalises a TTL-deleted parent to the deleted-only shape", () => {
    expect(normalizeReplyPreview({
      id: null, sender_user_id: null, sender_display_name: null, duration_ms: null,
      deleted: true,
    })).toEqual({ deleted: true, id: null, sender_display_name: null, duration_ms: null });
  });

  it("falls back to 'Teammate' when the backend omits sender_display_name", () => {
    expect(normalizeReplyPreview({ deleted: false }).sender_display_name).toBe("Teammate");
  });
});

describe("Phase 51.6 · mobile replyPreviewLabel", () => {
  it("renders the deleted-parent placeholder verbatim", () => {
    expect(replyPreviewLabel({ deleted: true })).toBe("(original message deleted)");
  });

  it("renders 'name · Xs' for a live parent", () => {
    expect(replyPreviewLabel({ deleted: false, sender_display_name: "Alice", duration_ms: 3400 }))
      .toBe("Alice · 3s");
  });

  it("clamps sub-second durations to '1s'", () => {
    expect(replyPreviewLabel({ deleted: false, sender_display_name: "Bob", duration_ms: 200 }))
      .toBe("Bob · 1s");
  });

  it("empty string when no preview", () => {
    expect(replyPreviewLabel(null)).toBe("");
  });
});
