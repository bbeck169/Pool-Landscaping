/**
 * Feb-2026 · P38 — AI-suggested duplicate tags (Vitest).
 *
 * Pins the P38 UX contract on ``CustomerTagsSettingsPage``:
 *   1. Suggested-duplicates GET happens on mount alongside catalog GET.
 *   2. Cluster renders canonical + victims + confidence percentage.
 *   3. One-click "Merge" POSTs to the existing merge endpoint with the
 *      canonical id + the remaining tag ids as victims, then reloads
 *      both catalog + suggestions.
 *   4. "Dismiss" hides the cluster and persists to ``sessionStorage``.
 *   5. Empty response renders the "no duplicate suggestions" hint.
 *   6. API failure on suggestions never breaks the primary catalog UI.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPatch = vi.fn();
const mockDelete = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
    delete: (...a) => mockDelete(...a),
  },
}));

import CustomerTagsSettingsPage from "@/pages/settings/CustomerTagsSettingsPage";


const _catalogItems = [
  { id: "t-land", name: "Landscaping", usage_count: 12, is_active: true,
    is_system: false },
  { id: "t-lands", name: "Landscape", usage_count: 5, is_active: true,
    is_system: false },
  { id: "t-pool", name: "Pool", usage_count: 20, is_active: true,
    is_system: false },
];

const _cluster = {
  tag_ids: ["t-land", "t-lands"],
  labels: ["Landscaping", "Landscape"],
  suggested_canonical: "Landscaping",
  suggested_canonical_id: "t-land",
  confidence: 0.9,
  signature: "landscape|landscaping",
};


function _installMockGet({ clusters = [], catalog = _catalogItems,
                            suggestReject = false } = {}) {
  mockGet.mockImplementation((path) => {
    if (path && path.startsWith("/customer-tags/suggest-duplicates")) {
      if (suggestReject) return Promise.reject(new Error("boom"));
      return Promise.resolve({ ok: true, clusters, ratio_threshold: 0.8 });
    }
    return Promise.resolve({ items: catalog, total: catalog.length });
  });
}


beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
  mockDelete.mockReset();
  mockPost.mockResolvedValue({ ok: true, merged_victims: 1,
    customers_updated: 3 });
  mockPatch.mockResolvedValue({ ok: true });
  mockDelete.mockResolvedValue({ ok: true, archived: true });
  // Clean session-scoped dismissed set between tests.
  try { sessionStorage.clear(); } catch (_e) { /* noop */ }
});


describe("CustomerTagsSettingsPage · P38 suggestions", () => {
  it("fetches /customer-tags/suggest-duplicates on mount and renders a cluster",
      async () => {
    _installMockGet({ clusters: [_cluster] });
    render(<CustomerTagsSettingsPage />);

    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(calls).toContain("/customer-tags/suggest-duplicates");
    });

    const suggestion = await screen.findByTestId(
      `customer-tags-suggestion-${_cluster.signature}`);
    expect(suggestion).toBeTruthy();
    // Canonical label appears once, victims appear separately.
    expect(suggestion.textContent).toMatch(/Landscaping/);
    expect(suggestion.textContent).toMatch(/Landscape/);
    // Confidence rendered as an integer percentage.
    const conf = screen.getByTestId(
      `customer-tags-suggestion-confidence-${_cluster.signature}`);
    expect(conf.textContent).toMatch(/90%/);
    // Count badge reflects visible clusters.
    expect(screen.getByTestId("customer-tags-suggestions-count").textContent)
      .toBe("1");
  });

  it("Merge on a cluster POSTs canonical + remaining ids and refetches",
      async () => {
    _installMockGet({ clusters: [_cluster] });
    render(<CustomerTagsSettingsPage />);
    const btn = await screen.findByTestId(
      `customer-tags-suggestion-merge-${_cluster.signature}`);
    fireEvent.click(btn);
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/customer-tags/merge",
      { canonical_id: "t-land", victim_ids: ["t-lands"] },
    ));
    // Success message uses the merged victim count returned by API.
    await waitFor(() => {
      const okBox = screen.queryByTestId("customer-tags-ok");
      expect(okBox && /Merged 1 tag/.test(okBox.textContent)).toBeTruthy();
    });
    // Both endpoints re-fetched after the merge.
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const suggestCalls = calls.filter(
        (p) => p === "/customer-tags/suggest-duplicates").length;
      expect(suggestCalls).toBeGreaterThanOrEqual(2);
    });
  });

  it("Dismiss hides the cluster and persists the signature to sessionStorage",
      async () => {
    _installMockGet({ clusters: [_cluster] });
    render(<CustomerTagsSettingsPage />);
    const dismissBtn = await screen.findByTestId(
      `customer-tags-suggestion-dismiss-${_cluster.signature}`);
    fireEvent.click(dismissBtn);
    await waitFor(() => expect(screen.queryByTestId(
      `customer-tags-suggestion-${_cluster.signature}`)).toBeNull());
    // Persisted in sessionStorage.
    const raw = sessionStorage.getItem("p38.dismissedDupeSignatures");
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw)).toContain(_cluster.signature);
    // No merge POST should have fired.
    expect(mockPost).not.toHaveBeenCalledWith(
      "/customer-tags/merge", expect.anything());
  });

  it("Empty clusters response renders the no-duplicates hint", async () => {
    _installMockGet({ clusters: [] });
    render(<CustomerTagsSettingsPage />);
    const empty = await screen.findByTestId(
      "customer-tags-suggestions-empty");
    expect(empty).toBeTruthy();
    // The section itself should NOT render when there's nothing to show.
    expect(screen.queryByTestId("customer-tags-suggestions")).toBeNull();
  });

  it("Failure on suggestions endpoint does not break the primary catalog",
      async () => {
    _installMockGet({ suggestReject: true });
    render(<CustomerTagsSettingsPage />);
    // Primary catalog still renders.
    await waitFor(() => expect(screen.getByTestId("customer-tags-row-t-land"))
      .toBeTruthy());
    // Suggestions section is absent; empty hint may or may not appear.
    expect(screen.queryByTestId("customer-tags-suggestions")).toBeNull();
  });

  it("Previously-dismissed signature stays hidden on remount", async () => {
    sessionStorage.setItem(
      "p38.dismissedDupeSignatures",
      JSON.stringify([_cluster.signature]));
    _installMockGet({ clusters: [_cluster] });
    render(<CustomerTagsSettingsPage />);
    // Give the effect a chance to fire.
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(calls).toContain("/customer-tags/suggest-duplicates");
    });
    // Even with the cluster in the API response, it's hidden.
    expect(screen.queryByTestId(
      `customer-tags-suggestion-${_cluster.signature}`)).toBeNull();
  });
});
