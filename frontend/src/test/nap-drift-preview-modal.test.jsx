/**
 * Feb-2026 · Phase 22 — NAP drift preview modal (rendered from
 * BusinessCard settings when a NAP field mutates before save).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


const apiGet = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGet(...a) },
}));

import NapDriftPreviewModal from "@/components/citations/NapDriftPreviewModal";


beforeEach(() => { apiGet.mockReset(); });


describe("NapDriftPreviewModal", () => {
  it("renders nothing when open=false", () => {
    const { container } = render(
      <NapDriftPreviewModal open={false} proposed={{}} onConfirm={() => {}} onCancel={() => {}} />
    );
    expect(container.querySelector('[data-testid="nap-drift-preview-modal"]'))
      .toBeNull();
  });

  it("renders + fetches preview, listing every affected citation", async () => {
    apiGet.mockResolvedValueOnce({
      changed_fields: ["phone"],
      current: { phone: "555-OLD" },
      proposed: { phone: "555-NEW" },
      affected_count: 2,
      affected: [
        { directory_id: "d1", directory_slug: "google-business-profile",
          directory_name: "Google Business Profile",
          directory_url: "https://business.google.com",
          listing_url: "https://g.co/x",
          current_snapshot: { phone: "555-OLD" } },
        { directory_id: "d2", directory_slug: "yelp",
          directory_name: "Yelp for Business",
          directory_url: "https://biz.yelp.com",
          listing_url: null,
          current_snapshot: { phone: "555-OLD" } },
      ],
    });
    render(
      <NapDriftPreviewModal
        open={true}
        proposed={{ phone: "555-NEW" }}
        onConfirm={() => {}} onCancel={() => {}}
      />
    );
    expect(await screen.findByTestId("nap-drift-preview-title"))
      .toBeInTheDocument();
    expect(await screen.findByTestId("nap-drift-preview-summary"))
      .toHaveTextContent(/2 live listings/i);
    expect(screen.getByTestId("nap-drift-preview-item-google-business-profile"))
      .toBeInTheDocument();
    expect(screen.getByTestId("nap-drift-preview-item-yelp"))
      .toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith(
      expect.stringContaining("/citations/tenant/nap-drift-preview")
    );
  });

  it("shows no-changes banner when nothing actually differs", async () => {
    apiGet.mockResolvedValueOnce({
      changed_fields: [], current: {}, proposed: {},
      affected_count: 0, affected: [],
    });
    render(
      <NapDriftPreviewModal
        open={true} proposed={{}}
        onConfirm={() => {}} onCancel={() => {}}
      />
    );
    expect(await screen.findByTestId("nap-drift-preview-no-changes"))
      .toBeInTheDocument();
  });

  it("Confirm button fires onConfirm", async () => {
    apiGet.mockResolvedValueOnce({
      changed_fields: ["phone"], current: {}, proposed: {},
      affected_count: 0, affected: [],
    });
    const onConfirm = vi.fn();
    render(
      <NapDriftPreviewModal
        open={true} proposed={{ phone: "x" }}
        onConfirm={onConfirm} onCancel={() => {}}
      />
    );
    await screen.findByTestId("nap-drift-preview-confirm");
    fireEvent.click(screen.getByTestId("nap-drift-preview-confirm"));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("Cancel button fires onCancel", async () => {
    apiGet.mockResolvedValueOnce({
      changed_fields: [], current: {}, proposed: {},
      affected_count: 0, affected: [],
    });
    const onCancel = vi.fn();
    render(
      <NapDriftPreviewModal
        open={true} proposed={{}}
        onConfirm={() => {}} onCancel={onCancel}
      />
    );
    await screen.findByTestId("nap-drift-preview-cancel");
    fireEvent.click(screen.getByTestId("nap-drift-preview-cancel"));
    expect(onCancel).toHaveBeenCalled();
  });

  it("Surfaces backend error but still allows save", async () => {
    apiGet.mockRejectedValueOnce(new Error("boom"));
    render(
      <NapDriftPreviewModal
        open={true} proposed={{ phone: "x" }}
        onConfirm={() => {}} onCancel={() => {}}
      />
    );
    expect(await screen.findByTestId("nap-drift-preview-error"))
      .toHaveTextContent(/boom/);
    // Confirm still enabled.
    expect(screen.getByTestId("nap-drift-preview-confirm")).toBeInTheDocument();
  });
});
