/**
 * F2f · Feb-2026 — Staff profile photo · Vitest.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(async () => ({ id: "u1", name: "Sam", email: "s@x.com", role: "manager", profile_photo_url: null })),
  patchSpy: vi.fn(async (url, body) => ({ ok: true, user: { id: "u1", name: "Sam", email: "s@x.com", role: "manager", ...body } })),
}));
vi.mock("@/api", () => ({
  api: { get: getSpy, patch: patchSpy, post: vi.fn(), put: vi.fn() },
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", name: "Sam", email: "s@x.com", role: "manager" }, loading: false }),
}));

const uploadSpies = [];
vi.mock("@/components/files/FileUpload", () => ({
  FileUpload: (props) => {
    uploadSpies.push(props);
    return (
      <button
        data-testid="mock-upload"
        data-purpose={props.purpose}
        data-linked-type={props.linkedEntityType}
        data-linked-id={props.linkedEntityId}
        data-accept={props.accept}
        onClick={() => props.onUploaded?.({ id: "f0-photo-1" })}
      >upload</button>
    );
  },
}));
vi.mock("@/components/files/AuthedImage", () => ({
  AuthedImage: (p) => <img data-testid="mock-authed-image" data-file-id={p.fileId} />,
}));

import MyProfilePage, { buildStaffPhotoUrl } from "@/pages/account/MyProfilePage";

beforeEach(() => {
  getSpy.mockClear();
  patchSpy.mockClear();
  uploadSpies.length = 0;
});
afterEach(() => cleanup());

describe("buildStaffPhotoUrl", () => {
  it("F0 id → /api/files/{id}/download", () => {
    expect(buildStaffPhotoUrl("abc")).toBe("/api/files/abc/download");
  });
  it("empty id → empty string", () => {
    expect(buildStaffPhotoUrl("")).toBe("");
    expect(buildStaffPhotoUrl(null)).toBe("");
  });
});

describe("MyProfilePage · initial render", () => {
  it("renders initial-badge fallback when profile_photo_url is null", async () => {
    render(<MyProfilePage />);
    await waitFor(() => expect(screen.queryByTestId("my-profile-page")).toBeTruthy());
    expect(screen.getByTestId("profile-initial-badge")).toBeTruthy();
    expect(screen.queryByTestId("mock-authed-image")).toBeNull();
  });

  it("renders AuthedImage when profile_photo_url matches /api/files/{id}/download", async () => {
    getSpy.mockResolvedValueOnce({
      id: "u1", name: "Sam", email: "s@x.com", role: "manager",
      profile_photo_url: "/api/files/f0-existing/download",
    });
    render(<MyProfilePage />);
    await waitFor(() => expect(screen.queryByTestId("mock-authed-image")).toBeTruthy());
    expect(screen.getByTestId("mock-authed-image").getAttribute("data-file-id")).toBe("f0-existing");
  });
});

describe("MyProfilePage · FileUpload wiring", () => {
  it("passes purpose='staff_profile_photo' + linked=user + id=me.id", async () => {
    render(<MyProfilePage />);
    await waitFor(() => expect(screen.queryByTestId("mock-upload")).toBeTruthy());
    const el = screen.getByTestId("mock-upload");
    expect(el.getAttribute("data-purpose")).toBe("staff_profile_photo");
    expect(el.getAttribute("data-linked-type")).toBe("user");
    expect(el.getAttribute("data-linked-id")).toBe("u1");
  });

  it("accept restricts to PNG/JPG/WebP (image-only, no PDF)", async () => {
    render(<MyProfilePage />);
    await waitFor(() => expect(screen.queryByTestId("mock-upload")).toBeTruthy());
    const accept = screen.getByTestId("mock-upload").getAttribute("data-accept");
    expect(accept).toContain("image/png");
    expect(accept).toContain("image/jpeg");
    expect(accept).toContain("image/webp");
    expect(accept).not.toContain("pdf");
    expect(accept).not.toContain("video");
  });
});

describe("MyProfilePage · PATCH round-trip", () => {
  it("upload success → PATCH /users/me with the F0 URL", async () => {
    render(<MyProfilePage />);
    await waitFor(() => expect(screen.queryByTestId("mock-upload")).toBeTruthy());
    fireEvent.click(screen.getByTestId("mock-upload"));
    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    expect(patchSpy).toHaveBeenCalledWith("/users/me", {
      profile_photo_url: "/api/files/f0-photo-1/download",
    });
  });

  it("remove button PATCHes with null (clear-on-null)", async () => {
    getSpy.mockResolvedValueOnce({
      id: "u1", name: "Sam", email: "s@x.com", role: "manager",
      profile_photo_url: "/api/files/f0-existing/download",
    });
    render(<MyProfilePage />);
    await waitFor(() => expect(screen.queryByTestId("profile-remove-photo")).toBeTruthy());
    fireEvent.click(screen.getByTestId("profile-remove-photo"));
    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    expect(patchSpy).toHaveBeenCalledWith("/users/me", { profile_photo_url: null });
  });
});
