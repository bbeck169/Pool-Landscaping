/**
 * Phase S2 · Feb-2026 — Brand Brain empty state CTA.
 *
 * When the tenant has never ingested a website AND has no manual
 * brand_brain content authored, the tab MUST render the "Ingest
 * your website" empty-state CTA.  Clicking it opens the ingest
 * modal.  This test locks in the empty-state contract.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { api } from "@/api";
import BrandBrainTab from "@/pages/soshie/BrandBrainTab";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("S2 · brand brain empty state", () => {
  it("renders the CTA when brand_brain is empty and no ingest exists",
      async () => {
    api.get.mockResolvedValueOnce({
      brand_brain: {}, latest_ingest: null,
    });
    render(<BrandBrainTab />);
    // Empty state card + CTA.
    expect(await screen.findByTestId("brand-brain-empty"))
      .toBeInTheDocument();
    expect(screen.getByTestId("ingest-empty-cta"))
      .toBeInTheDocument();
  });

  it("renders content + Re-ingest button when brand memory exists",
      async () => {
    api.get.mockResolvedValueOnce({
      brand_brain: {
        tone: "Warm and casual",
        audience: "Homeowners",
        talking_points: ["Reliable service", "Local pros"],
        do_say: [], dont_say: [],
      },
      latest_ingest: {
        url: "https://example.test", ingested_at: "2026-02-01T12:00:00Z",
        headings: ["Services"], service_summary: "We install pools.",
      },
    });
    render(<BrandBrainTab />);
    expect(await screen.findByTestId("brand-brain-content"))
      .toBeInTheDocument();
    expect(screen.getByTestId("brand-brain-reingest-btn"))
      .toBeInTheDocument();
    expect(screen.getByTestId("brand-brain-tone").textContent)
      .toMatch(/warm and casual/i);
    expect(screen.getByTestId("brand-brain-last-ingest").textContent)
      .toMatch(/example\.test/);
  });

  it("clicking the empty-state CTA opens the ingest modal", async () => {
    api.get.mockResolvedValueOnce({
      brand_brain: {}, latest_ingest: null,
    });
    render(<BrandBrainTab />);
    const cta = await screen.findByTestId("ingest-empty-cta");
    fireEvent.click(cta);
    await waitFor(() =>
      expect(screen.getByTestId("brand-brain-ingest-modal"))
        .toBeInTheDocument());
    expect(screen.getByTestId("ingest-url-input"))
      .toBeInTheDocument();
  });
});
