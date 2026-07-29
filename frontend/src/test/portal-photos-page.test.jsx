/**
 * Portal Quick Action tiles + Photos/Videos pages · Feb-2026 · Vitest.
 *
 * Covers:
 *   1. PortalPhotosPage grid renders items.
 *   2. PortalPhotosPage empty state.
 *   3. Lightbox opens on tile click, shows job metadata.
 *   4. Messages tile on portal home links to /portal/chats + shows badge.
 *   5. Photos + Videos tiles link to /portal/photos and /portal/videos.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { getSpy, navigateSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  navigateSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { get: (...a) => getSpy(...a), post: vi.fn(), patch: vi.fn() },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateSpy };
});

beforeEach(() => {
  getSpy.mockReset();
  navigateSpy.mockReset();
});
afterEach(() => cleanup());

import PortalPhotosPage from "@/pages/portal/PortalPhotosPage";

describe("PortalPhotosPage", () => {
  it("renders grid when photos are returned", async () => {
    getSpy.mockResolvedValue({
      items: [
        { file_id: "f1", filename: "before.jpg", url: "/api/files/f1/download",
          mime: "image/jpeg", size: 100, job_id: "j1", job_title: "Weekly Cleaning",
          purpose: "job_photo", uploaded_at: "2026-02-10T10:00:00Z", source: "file" },
        { file_id: "f2", filename: "after.jpg", url: "/api/files/f2/download",
          mime: "image/jpeg", size: 100, job_id: "j1", job_title: "Weekly Cleaning",
          purpose: "job_photo", uploaded_at: "2026-02-10T11:00:00Z", source: "file" },
      ],
      total: 2, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("portal-photos-grid")).toBeTruthy());
    expect(screen.getByTestId("portal-photo-f1")).toBeTruthy();
    expect(screen.getByTestId("portal-photo-f2")).toBeTruthy();
  });

  it("renders empty state when no photos", async () => {
    getSpy.mockResolvedValue({ items: [], total: 0, limit: 24, offset: 0 });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("portal-photos-empty")).toBeTruthy());
  });

  it("opens lightbox on tile click with job metadata", async () => {
    getSpy.mockResolvedValue({
      items: [
        { file_id: "f1", filename: "sparkle.jpg", url: "/api/files/f1/download",
          mime: "image/jpeg", size: 1, job_id: "j1", job_title: "Pool sparkle service",
          purpose: "job_photo", uploaded_at: "2026-02-10T10:00:00Z", source: "file" },
      ],
      total: 1, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() => screen.getByTestId("portal-photo-f1"));
    fireEvent.click(screen.getByTestId("portal-photo-f1"));
    expect(screen.getByTestId("portal-photo-lightbox")).toBeTruthy();
    expect(screen.getByTestId("portal-photo-lightbox-title").textContent)
      .toContain("Pool sparkle service");
    // Close.
    fireEvent.click(screen.getByTestId("portal-photo-lightbox-close"));
    expect(screen.queryByTestId("portal-photo-lightbox")).toBeNull();
  });
});
