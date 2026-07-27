/**
 * Phase 27 · Feb 2026 — Public service portal renders chemicals /
 * readings / checklist / videos returned by the public endpoint.
 * Verifies:
 *   • Video thumbnails render a play-icon overlay.
 *   • Clicking a video thumbnail opens a `<video controls>` inside
 *     the lightbox.
 *   • Chemistry readings, chemicals added, and checklist sections
 *     render when the endpoint returns non-empty arrays.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ServiceImagesPortalPage from "@/pages/public/ServiceImagesPortalPage";

function _mockFetch(payload, status = 200) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  });
}

function renderWithUuid(uuid = "test-uuid-1234") {
  return render(
    <MemoryRouter initialEntries={[`/portal/service/${uuid}`]}>
      <Routes>
        <Route path="/portal/service/:uuid" element={<ServiceImagesPortalPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ServiceImagesPortalPage (Phase 27)", () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it("renders chemistry readings, chemicals added, and checklist sections", async () => {
    _mockFetch({
      business_name: "TEST_ AquaTerra",
      logo_url: "",
      tech_first_name: "Mike",
      service_date: "2026-02-10",
      service_type: "Pool Service",
      images: [],
      videos: [],
      chemicals_added: [
        { name: "Liquid Chlorine", quantity: 1, unit: "gal" },
      ],
      chemical_readings: [
        { key: "ph", name: "pH", value: 7.5 },
        { key: "chlorine", name: "Free Chlorine", value: 2.1, unit: "ppm" },
      ],
      checklist: [{ label: "Skim surface" }, { label: "Empty pump basket" }],
    });
    renderWithUuid();
    await screen.findByTestId("service-portal-root");
    expect(screen.getByTestId("service-portal-readings-section")).toBeTruthy();
    expect(screen.getByTestId("service-portal-chemicals-section")).toBeTruthy();
    expect(screen.getByTestId("service-portal-checklist-section")).toBeTruthy();
    expect(screen.getByTestId("service-portal-reading-ph").textContent).toContain("7.5");
    expect(screen.getByTestId("service-portal-checklist-list").textContent).toContain("Skim surface");
    expect(screen.getByTestId("service-portal-checklist-list").textContent).toContain("Empty pump basket");
    expect(screen.getByTestId("service-portal-chemicals-list").textContent).toContain("Liquid Chlorine");
  });

  it("renders video thumbnail with play icon overlay + opens video lightbox", async () => {
    _mockFetch({
      business_name: "TEST_ AquaTerra",
      logo_url: "",
      tech_first_name: "Mike",
      service_date: "2026-02-10",
      service_type: "Pool Service",
      images: [],
      videos: [{
        url: "/api/public/service/test-uuid-1234/video/vid1",
        poster_url: "https://cdn.test/poster1.jpg",
        content_type: "video/mp4",
      }],
      chemicals_added: [],
      chemical_readings: [],
      checklist: [],
    });
    renderWithUuid();
    await screen.findByTestId("service-portal-root");
    // Play-icon overlay is present on the video tile.
    expect(screen.getByTestId("service-portal-video-play-0")).toBeTruthy();
    // Click opens a native <video> in the lightbox.
    fireEvent.click(screen.getByTestId("service-portal-video-0"));
    await waitFor(() => {
      expect(screen.getByTestId("service-portal-lightbox-video")).toBeTruthy();
    });
    const vid = screen.getByTestId("service-portal-lightbox-video");
    expect(vid.getAttribute("src")).toContain("/api/public/service/test-uuid-1234/video/vid1");
    expect(vid.getAttribute("controls")).not.toBeNull();
  });

  it("hides empty sections when the endpoint returns no data", async () => {
    _mockFetch({
      business_name: "TEST",
      logo_url: "",
      tech_first_name: "",
      service_date: "",
      service_type: "",
      images: [],
      videos: [],
      chemicals_added: [],
      chemical_readings: [],
      checklist: [],
    });
    renderWithUuid();
    await screen.findByTestId("service-portal-root");
    expect(screen.queryByTestId("service-portal-readings-section")).toBeNull();
    expect(screen.queryByTestId("service-portal-chemicals-section")).toBeNull();
    expect(screen.queryByTestId("service-portal-checklist-section")).toBeNull();
    expect(screen.getByTestId("service-portal-empty")).toBeTruthy();
  });
});
