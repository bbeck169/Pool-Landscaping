/**
 * Feb-2026 · P29b — Muted Reasons manager (settings CRUD page).
 *
 * Verifies the ``/settings/muted-reasons`` surface:
 *   1. Loads + renders seeded rows from GET /settings/muted-reasons.
 *   2. Add flow POSTs to /settings/muted-reasons and reloads.
 *   3. Rename flow PATCHes the row's label.
 *   4. Archive flow DELETEs the row (soft-deactivate).
 *   5. Restore flow PATCHes ``is_active: true`` on an archived row.
 *   6. "Show archived" toggle re-fetches with ``?include_inactive=true``.
 *
 * The page itself is thin (`@/api` fetch wrapper) so the mocks cover
 * every HTTP verb the page issues.
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

import MutedReasonsPage from "@/pages/settings/MutedReasonsPage";


const _seed = () => ([
  { id: "r-1", label: "Billing dispute",     is_active: true,  sort_order: 0 },
  { id: "r-2", label: "Requested no contact", is_active: true, sort_order: 10 },
  { id: "r-3", label: "Deceased",             is_active: true, sort_order: 20 },
]);


beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
  mockDelete.mockReset();
  mockPost.mockResolvedValue({});
  mockPatch.mockResolvedValue({});
  mockDelete.mockResolvedValue({});
});


describe("MutedReasonsPage · P29b settings CRUD", () => {
  it("loads and renders active reasons", async () => {
    mockGet.mockResolvedValue({ items: _seed(), total: 3 });
    render(<MutedReasonsPage />);
    await waitFor(() => expect(screen.getByTestId("muted-reasons-page")).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId("muted-reasons-row-r-1")).toBeTruthy());
    expect(screen.getByTestId("muted-reasons-row-r-2")).toBeTruthy();
    expect(screen.getByTestId("muted-reasons-row-r-3")).toBeTruthy();
    // Default fetch — no ``?include_inactive`` on the URL.
    expect(mockGet).toHaveBeenCalledWith("/settings/muted-reasons");
  });

  it("posts new reason on Add + refetches", async () => {
    mockGet.mockResolvedValue({ items: _seed(), total: 3 });
    render(<MutedReasonsPage />);
    await waitFor(() => expect(screen.getByTestId("muted-reasons-add-input")).toBeTruthy());

    fireEvent.change(screen.getByTestId("muted-reasons-add-input"),
      { target: { value: "Legal / collections" } });
    fireEvent.click(screen.getByTestId("muted-reasons-add-submit"));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/settings/muted-reasons", { label: "Legal / collections" },
    ));
    // Reload after the successful add.
    await waitFor(() => expect(mockGet.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("rename PATCHes the row's label", async () => {
    mockGet.mockResolvedValue({ items: _seed(), total: 3 });
    render(<MutedReasonsPage />);
    await waitFor(() => expect(screen.getByTestId("muted-reasons-row-r-1")).toBeTruthy());

    fireEvent.click(screen.getByTestId("muted-reasons-rename-r-1"));
    const input = await screen.findByTestId("muted-reasons-rename-input-r-1");
    fireEvent.change(input, { target: { value: "Billing dispute (open)" } });
    fireEvent.click(screen.getByTestId("muted-reasons-rename-save-r-1"));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      "/settings/muted-reasons/r-1", { label: "Billing dispute (open)" },
    ));
  });

  it("archive DELETEs (soft-deactivate) the row", async () => {
    mockGet.mockResolvedValue({ items: _seed(), total: 3 });
    render(<MutedReasonsPage />);
    await waitFor(() => expect(screen.getByTestId("muted-reasons-row-r-1")).toBeTruthy());

    fireEvent.click(screen.getByTestId("muted-reasons-archive-r-1"));
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith(
      "/settings/muted-reasons/r-1",
    ));
  });

  it("toggling 'Show archived' re-fetches with include_inactive=true", async () => {
    mockGet.mockResolvedValue({ items: _seed(), total: 3 });
    render(<MutedReasonsPage />);
    await waitFor(() => expect(screen.getByTestId("muted-reasons-include-inactive")).toBeTruthy());

    fireEvent.click(screen.getByTestId("muted-reasons-include-inactive"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(calls).toContain("/settings/muted-reasons?include_inactive=true");
    });
  });

  it("restore PATCHes is_active=true on an archived row", async () => {
    const rows = _seed();
    rows.push({ id: "r-9", label: "Retired reason", is_active: false, sort_order: 40 });
    mockGet.mockResolvedValue({ items: rows, total: rows.length });
    render(<MutedReasonsPage />);
    // Turn on "show archived" so the retired row renders with a restore btn.
    await waitFor(() => expect(screen.getByTestId("muted-reasons-include-inactive")).toBeTruthy());
    fireEvent.click(screen.getByTestId("muted-reasons-include-inactive"));
    await waitFor(() => expect(screen.getByTestId("muted-reasons-restore-r-9")).toBeTruthy());

    fireEvent.click(screen.getByTestId("muted-reasons-restore-r-9"));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      "/settings/muted-reasons/r-9", { is_active: true },
    ));
  });
});
