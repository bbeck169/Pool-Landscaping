/**
 * Feb-2026 · Phase 22 — Edit sheet · Analytics + Duplicates tabs.
 *
 * Covers tab switching, analytics form flow (POST + history refresh),
 * duplicate URL add/remove/status flow (PATCH), and the trend arrow
 * rendered from history endpoint response.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPatch = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: (...a) => apiPost(...a),
    patch: (...a) => apiPatch(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
}));

import CitationBuilderPage from "@/pages/settings/CitationBuilderPage";


const SUMMARY = {
  total_directories: 1, by_status: { live: 1 }, live_count: 1,
  needs_update_count: 0, nap_drift_count: 0, duplicates_open_count: 0,
  total_impressions_last_30d: 500, weighted_completeness_score: 100,
  oldest_last_verified_at: "2026-02-10T00:00:00Z",
};

const VOICE = { score: 0, max_score: 100, breakdown: [] };


function mkRow() {
  return {
    total: 1,
    citations: [{
      directory_id: "dir-gbp", id: "row-gbp",
      directory: { id: "dir-gbp", slug: "google-business-profile",
        name: "Google Business Profile", category: "search", weight: 10,
        url: "https://business.google.com" },
      status: "live",
      listing_url: "https://g.co/plofv", notes: "hi",
      last_verified_at: "2026-02-10T00:00:00Z",
      nap_drift_detected: false,
      duplicate_urls: [
        { url: "https://dup.example.com/a", status: "reported", note: "" },
      ],
      impressions_last_30d: 500,
      clicks_last_30d: 40,
      actions_last_30d: 5,
    }],
  };
}


function mockDefault() {
  apiGet.mockImplementation((p) => {
    if (p === "/citations/tenant") return Promise.resolve(mkRow());
    if (p === "/citations/tenant/summary") return Promise.resolve(SUMMARY);
    if (p === "/citations/tenant/voice-score") return Promise.resolve(VOICE);
    if (p === "/citations/tenant/dir-gbp/analytics-history") {
      return Promise.resolve({
        total: 2, trend: "up",
        snapshots: [
          { impressions: 500, clicks: 40, actions: 5, recorded_at: "2026-02-10" },
          { impressions: 350, clicks: 20, actions: 2, recorded_at: "2026-01-10" },
        ],
      });
    }
    return Promise.reject(new Error(`unmocked ${p}`));
  });
}


function renderPage() {
  return render(<MemoryRouter><CitationBuilderPage /></MemoryRouter>);
}


async function openEditSheet() {
  const editBtn = await screen.findByTestId("citation-row-edit-google-business-profile");
  fireEvent.click(editBtn);
  await screen.findByTestId("citation-edit-sheet");
}


beforeEach(() => {
  apiGet.mockReset(); apiPost.mockReset(); apiPatch.mockReset();
});


describe("EditSheet · Analytics tab", () => {
  it("switches to the Analytics tab and loads history", async () => {
    mockDefault();
    renderPage();
    await openEditSheet();
    fireEvent.click(screen.getByTestId("citation-edit-tab-analytics"));
    // Trend arrow reflects the "up" trend from history mock.
    expect(await screen.findByTestId("citation-edit-analytics-trend"))
      .toHaveTextContent("up");
    // Chart rendered because history has snapshots.
    expect(await screen.findByTestId("citation-edit-analytics-chart"))
      .toBeInTheDocument();
    // Input fields prefilled from row.
    expect(screen.getByTestId("citation-edit-analytics-impressions"))
      .toHaveValue(500);
    expect(screen.getByTestId("citation-edit-analytics-clicks"))
      .toHaveValue(40);
  });

  it("Save snapshot POSTs to /analytics + refreshes history", async () => {
    mockDefault();
    apiPost.mockResolvedValueOnce({
      snapshot: { impressions: 999, clicks: 50, actions: 10 },
      row: { impressions_last_30d: 999 },
    });
    renderPage();
    await openEditSheet();
    fireEvent.click(screen.getByTestId("citation-edit-tab-analytics"));
    await screen.findByTestId("citation-edit-analytics-history");
    // Bump impressions.
    fireEvent.change(screen.getByTestId("citation-edit-analytics-impressions"),
                      { target: { value: "999" } });
    fireEvent.click(screen.getByTestId("citation-edit-analytics-save"));
    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        "/citations/tenant/dir-gbp/analytics",
        expect.objectContaining({ impressions: 999 })
      );
    });
  });
});


describe("EditSheet · Duplicates tab", () => {
  it("switches to Duplicates tab + renders existing entry", async () => {
    mockDefault();
    renderPage();
    await openEditSheet();
    fireEvent.click(screen.getByTestId("citation-edit-tab-duplicates"));
    // Existing dup renders as item 0.
    expect(await screen.findByTestId("citation-edit-dup-item-0"))
      .toBeInTheDocument();
    expect(screen.getByTestId("citation-edit-dup-status-0")).toHaveValue("reported");
  });

  it("Adds a new duplicate URL to the list", async () => {
    mockDefault();
    renderPage();
    await openEditSheet();
    fireEvent.click(screen.getByTestId("citation-edit-tab-duplicates"));
    await screen.findByTestId("citation-edit-dup-item-0");
    fireEvent.change(screen.getByTestId("citation-edit-dup-new-url"),
                      { target: { value: "https://dup.example.com/b" } });
    fireEvent.click(screen.getByTestId("citation-edit-dup-add"));
    await waitFor(() => {
      expect(screen.getByTestId("citation-edit-dup-item-1")).toBeInTheDocument();
    });
  });

  it("Save duplicates PATCHes /duplicates with the current list", async () => {
    mockDefault();
    apiPatch.mockResolvedValueOnce({ ok: true });
    renderPage();
    await openEditSheet();
    fireEvent.click(screen.getByTestId("citation-edit-tab-duplicates"));
    await screen.findByTestId("citation-edit-dup-item-0");
    // Change status of existing dup to suppressed.
    fireEvent.change(screen.getByTestId("citation-edit-dup-status-0"),
                      { target: { value: "suppressed" } });
    fireEvent.click(screen.getByTestId("citation-edit-dup-save"));
    await waitFor(() => {
      expect(apiPatch).toHaveBeenCalledWith(
        "/citations/tenant/dir-gbp/duplicates",
        expect.objectContaining({
          duplicate_urls: expect.arrayContaining([
            expect.objectContaining({
              url: "https://dup.example.com/a", status: "suppressed",
            }),
          ]),
        })
      );
    });
  });

  it("Remove button deletes the item from the list", async () => {
    mockDefault();
    renderPage();
    await openEditSheet();
    fireEvent.click(screen.getByTestId("citation-edit-tab-duplicates"));
    await screen.findByTestId("citation-edit-dup-item-0");
    fireEvent.click(screen.getByTestId("citation-edit-dup-remove-0"));
    await waitFor(() => {
      expect(screen.queryByTestId("citation-edit-dup-item-0"))
        .not.toBeInTheDocument();
      expect(screen.getByTestId("citation-edit-dup-empty")).toBeInTheDocument();
    });
  });
});
