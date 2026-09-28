/**
 * DTP-1 · Feb-2026 — PortalServiceDetail lightbox wire-up.
 *
 * Covers the wire-up spec'd in DTP-1:
 *   * A job with photos renders clickable photo buttons with
 *     testid ``portal-service-detail-photo-{i}``.
 *   * Clicking a photo opens the shared ``<Lightbox>`` with the
 *     testid prefix ``portal-service-detail-lightbox``.
 *   * ESC closes the lightbox.
 *   * ArrowRight advances to the next photo.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: {
    get:   (...a) => getSpy(...a),
    post:  vi.fn(),
    put:   vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

// PortalPages.jsx uses ``useAuth`` at module scope for other exports;
// PortalServiceDetail itself doesn't touch it, but the module-load
// path pulls the auth context. Stub it so we don't need a provider.
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "customer" } }),
}));

beforeEach(() => { getSpy.mockReset(); });
afterEach(() => cleanup());

import { PortalServiceDetail } from "@/pages/portal/PortalPages";

function _mount(job) {
  getSpy.mockResolvedValue(job);
  return render(
    <MemoryRouter initialEntries={["/portal/services/j1"]}>
      <Routes>
        <Route path="/portal/services/:id" element={<PortalServiceDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

const JOB = {
  id: "j1",
  title: "Weekly Service",
  status: "completed",
  scheduled_date: "2026-02-15",
  technician_name: "Alex",
  photos: [
    { url: "https://cdn.example/p1.jpg" },
    { url: "https://cdn.example/p2.jpg" },
  ],
};

describe("PortalServiceDetail · DTP-1 lightbox", () => {
  it("renders each photo as a clickable button with testid", async () => {
    _mount(JOB);
    await waitFor(() => expect(screen.getByText("Weekly Service")).toBeTruthy());
    expect(screen.getByTestId("portal-service-detail-photo-0")).toBeTruthy();
    expect(screen.getByTestId("portal-service-detail-photo-1")).toBeTruthy();
  });

  it("clicking a photo opens the shared Lightbox", async () => {
    _mount(JOB);
    await waitFor(() => screen.getByTestId("portal-service-detail-photo-0"));
    fireEvent.click(screen.getByTestId("portal-service-detail-photo-0"));
    expect(screen.getByTestId("portal-service-detail-lightbox")).toBeTruthy();
    const img = screen.getByTestId("portal-service-detail-lightbox-image");
    expect(img.getAttribute("src")).toContain("p1.jpg");
  });

  it("ESC key closes the lightbox", async () => {
    _mount(JOB);
    await waitFor(() => screen.getByTestId("portal-service-detail-photo-0"));
    fireEvent.click(screen.getByTestId("portal-service-detail-photo-0"));
    expect(screen.getByTestId("portal-service-detail-lightbox")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByTestId("portal-service-detail-lightbox")).toBeNull(),
    );
  });

  it("ArrowRight cycles to the next photo", async () => {
    _mount(JOB);
    await waitFor(() => screen.getByTestId("portal-service-detail-photo-0"));
    fireEvent.click(screen.getByTestId("portal-service-detail-photo-0"));
    expect(
      screen.getByTestId("portal-service-detail-lightbox-image").getAttribute("src"),
    ).toContain("p1.jpg");
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(
      screen.getByTestId("portal-service-detail-lightbox-image").getAttribute("src"),
    ).toContain("p2.jpg");
  });

  it("job without photos does not render the lightbox trigger buttons", async () => {
    _mount({ ...JOB, photos: [] });
    await waitFor(() => expect(screen.getByText("Weekly Service")).toBeTruthy());
    expect(screen.queryByTestId("portal-service-detail-photo-0")).toBeNull();
    expect(screen.queryByTestId("portal-service-detail-lightbox")).toBeNull();
  });
});
