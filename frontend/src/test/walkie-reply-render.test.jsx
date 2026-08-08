/**
 * Phase 51.6 · Feb 2026 — Walkie reply preview render contract.
 *
 * Locked shape from the backend's ``GET /messages`` enrichment:
 *   reply_preview = { id, sender_user_id, sender_display_name,
 *                     duration_ms, deleted }
 *
 * When ``deleted: true`` the sibling fields are null and the UI
 * renders the "(original message deleted)" placeholder verbatim.
 */
import { describe, it, expect } from "vitest";
import { normalizeReplyPreview, replyPreviewLabel } from "@/pages/walkie/walkie-helpers";

describe("Phase 51.6 · normalizeReplyPreview", () => {
  it("returns null for missing preview", () => {
    expect(normalizeReplyPreview(null)).toBeNull();
    expect(normalizeReplyPreview(undefined)).toBeNull();
  });

  it("normalises a live parent to a fully-populated object", () => {
    const p = normalizeReplyPreview({
      id: "m1",
      sender_user_id: "u1",
      sender_display_name: "Alice",
      duration_ms: 3400,
      deleted: false,
    });
    expect(p).toEqual({
      deleted: false,
      id: "m1",
      sender_display_name: "Alice",
      duration_ms: 3400,
    });
  });

  it("normalises a TTL-deleted parent to the deleted-only shape", () => {
    const p = normalizeReplyPreview({
      id: null, sender_user_id: null, sender_display_name: null, duration_ms: null,
      deleted: true,
    });
    expect(p).toEqual({
      deleted: true,
      id: null,
      sender_display_name: null,
      duration_ms: null,
    });
  });

  it("falls back to 'Teammate' when the backend omits sender_display_name", () => {
    const p = normalizeReplyPreview({ deleted: false });
    expect(p.sender_display_name).toBe("Teammate");
  });
});

describe("Phase 51.6 · replyPreviewLabel", () => {
  it("renders the '(original message deleted)' placeholder when parent TTL-expired", () => {
    expect(replyPreviewLabel({ deleted: true })).toBe("(original message deleted)");
  });

  it("renders 'name · Xs' for a live parent", () => {
    expect(replyPreviewLabel({
      deleted: false, sender_display_name: "Alice", duration_ms: 3400,
    })).toBe("Alice · 3s");
  });

  it("clamps sub-second durations to '1s' floor", () => {
    expect(replyPreviewLabel({
      deleted: false, sender_display_name: "Bob", duration_ms: 300,
    })).toBe("Bob · 1s");
  });

  it("returns empty string when no preview is attached", () => {
    expect(replyPreviewLabel(null)).toBe("");
  });
});
