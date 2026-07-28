/**
 * Phase F2e · Feb 2026 — Persona avatar upload · Vitest.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

// Mock the api used inside PersonaAvatarUploadModal + AuthedImage.
const { patchSpy } = vi.hoisted(() => ({ patchSpy: vi.fn(async () => ({ ok: true })) }));
vi.mock("@/api", () => ({
  api: { patch: patchSpy, get: vi.fn(), post: vi.fn(), put: vi.fn() },
  TOKEN_KEY: "token",
}));

// Mock the file upload / authed image so we exercise the modal + wiring,
// not the underlying widgets.
const uploadSpies = [];
vi.mock("@/components/files/FileUpload", () => ({
  FileUpload: (props) => {
    uploadSpies.push(props);
    return (
      <button
        data-testid="mock-file-upload"
        data-accept={props.accept}
        data-linked-type={props.linkedEntityType}
        data-linked-id={props.linkedEntityId}
        data-purpose={props.purpose}
        onClick={() => props.onUploaded?.({ id: "f0-abc-123" })}
      >
        upload
      </button>
    );
  },
}));
vi.mock("@/components/files/AuthedImage", () => ({
  AuthedImage: (p) => <div data-testid="mock-authed-image" data-file-id={p.fileId} />,
}));

import {
  PersonaAvatarUploadModal,
  buildPersonaAvatarUrl,
  defaultPersonaAvatarUrl,
  PERSONA_AVATAR_MAX_BYTES,
  PERSONA_AVATAR_ACCEPT,
} from "@/components/personas/PersonaAvatarUploadModal";
import { PersonaAvatar, extractF0FileId } from "@/components/personas/PersonaAvatar";

beforeEach(() => {
  patchSpy.mockClear();
  uploadSpies.length = 0;
});
afterEach(() => cleanup());

// ═══════════════════════════════════════════════════════════════════
// Pure helpers
// ═══════════════════════════════════════════════════════════════════
describe("buildPersonaAvatarUrl / defaultPersonaAvatarUrl", () => {
  it("F0 file id → /api/files/{id}/download", () => {
    expect(buildPersonaAvatarUrl("abc-123")).toBe("/api/files/abc-123/download");
  });
  it("empty id → empty string (defensive)", () => {
    expect(buildPersonaAvatarUrl("")).toBe("");
    expect(buildPersonaAvatarUrl(null)).toBe("");
  });
  it("defaultPersonaAvatarUrl(key) → /avatars/personas/{key}.jpg", () => {
    expect(defaultPersonaAvatarUrl("billy")).toBe("/avatars/personas/billy.jpg");
    expect(defaultPersonaAvatarUrl("")).toBe("");
  });
});

describe("extractF0FileId (routes F0 URLs through AuthedImage)", () => {
  it("returns the id when URL matches /api/files/{id}/download", () => {
    expect(extractF0FileId("/api/files/f0-xyz/download")).toBe("f0-xyz");
    expect(extractF0FileId("/api/files/f0-xyz/download?auth=abc")).toBe("f0-xyz");
  });
  it("returns null for legacy static paths + garbage", () => {
    expect(extractF0FileId("/avatars/personas/billy.jpg")).toBeNull();
    expect(extractF0FileId("")).toBeNull();
    expect(extractF0FileId(null)).toBeNull();
    expect(extractF0FileId("https://cdn.example.com/x.jpg")).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════════════
// FileUpload wiring
// ═══════════════════════════════════════════════════════════════════
describe("PersonaAvatarUploadModal · FileUpload wiring", () => {
  const persona = { key: "billy", name: "Billy", avatar_emoji: "🌱" };

  it("renders when a persona is provided", () => {
    render(<PersonaAvatarUploadModal persona={persona} />);
    expect(screen.getByTestId("persona-avatar-upload-modal")).toBeTruthy();
  });

  it("passes purpose='persona_avatar' + linked_entity_type='persona' + key as id", () => {
    render(<PersonaAvatarUploadModal persona={persona} />);
    const el = screen.getByTestId("mock-file-upload");
    expect(el.getAttribute("data-purpose")).toBe("persona_avatar");
    expect(el.getAttribute("data-linked-type")).toBe("persona");
    expect(el.getAttribute("data-linked-id")).toBe("billy");
  });

  it("accept restricts to PNG/JPEG/WebP (no video, no PDF)", () => {
    render(<PersonaAvatarUploadModal persona={persona} />);
    const el = screen.getByTestId("mock-file-upload");
    const accept = el.getAttribute("data-accept");
    expect(accept).toContain("image/png");
    expect(accept).toContain("image/jpeg");
    expect(accept).toContain("image/webp");
    expect(accept).not.toContain("video");
    expect(accept).not.toContain("pdf");
  });

  it("tightens max file size to 5MB (persona-specific)", () => {
    expect(PERSONA_AVATAR_MAX_BYTES).toBe(5 * 1024 * 1024);
    expect(PERSONA_AVATAR_ACCEPT).toMatch(/image/);
  });
});

// ═══════════════════════════════════════════════════════════════════
// PATCH round-trip
// ═══════════════════════════════════════════════════════════════════
describe("PersonaAvatarUploadModal · PATCH on upload success", () => {
  const persona = { key: "billy", id: "emp-1", name: "Billy" };

  it("uploads → PATCHes /ai-employees/{eid} with the F0 URL", async () => {
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(<PersonaAvatarUploadModal persona={persona} onSaved={onSaved} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("mock-file-upload"));
    await new Promise((r) => setTimeout(r, 0));
    expect(patchSpy).toHaveBeenCalledTimes(1);
    expect(patchSpy).toHaveBeenCalledWith("/ai-employees/emp-1", {
      avatar_url: "/api/files/f0-abc-123/download",
    });
    expect(onSaved).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("Reset button PATCHes back to the default static avatar path", async () => {
    const onSaved = vi.fn();
    render(<PersonaAvatarUploadModal persona={persona} onSaved={onSaved} />);
    fireEvent.click(screen.getByTestId("persona-avatar-reset"));
    await new Promise((r) => setTimeout(r, 0));
    expect(patchSpy).toHaveBeenCalledWith("/ai-employees/emp-1", {
      avatar_url: "/avatars/personas/billy.jpg",
    });
    expect(onSaved).toHaveBeenCalled();
  });
});

// ═══════════════════════════════════════════════════════════════════
// PersonaAvatar renders AuthedImage for F0 URLs
// ═══════════════════════════════════════════════════════════════════
describe("PersonaAvatar · F0 URL routing", () => {
  it("routes /api/files/{id}/download through AuthedImage", () => {
    render(<PersonaAvatar persona={{ key: "billy", name: "Billy",
                                        avatar_url: "/api/files/f0-xyz/download" }} />);
    const el = screen.getByTestId("mock-authed-image");
    expect(el.getAttribute("data-file-id")).toBe("f0-xyz");
  });

  it("uses a plain <img> for legacy static paths", () => {
    render(<PersonaAvatar persona={{ key: "billy", name: "Billy",
                                        avatar_url: "/avatars/personas/billy.jpg" }} />);
    expect(screen.queryByTestId("mock-authed-image")).toBeNull();
    const img = screen.getByRole("img");
    expect(img.getAttribute("src")).toBe("/avatars/personas/billy.jpg");
  });

  it("falls back to emoji when avatar_url is missing", () => {
    render(<PersonaAvatar persona={{ key: "billy", name: "Billy", avatar_emoji: "🌱" }} />);
    expect(screen.queryByTestId("mock-authed-image")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });
});
