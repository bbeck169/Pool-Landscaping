/**
 * Feb-2026 · P36 — Customer Tags Settings Manager (Vitest).
 *
 * Pins the P29b-parity UX contract:
 *   1. Loads + renders active tags on mount.
 *   2. Add flow POSTs new tag + reloads.
 *   3. Rename flow PATCHes name + reloads.
 *   4. Archive flow DELETEs (soft-archive) + reloads.
 *   5. "Show archived" toggle re-fetches with ?include_inactive=true.
 *   6. Restore flow POSTs /restore + reloads.
 *   7. Duplicate 409 surfaces an inline error message.
 *   8. Merge modal submit POSTs {canonical_id, victim_ids[]} + reloads.
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


const _seed = (over = {}) => [
  { id: "t-1", name: "Landscaping", usage_count: 5, is_active: true,
    is_system: false },
  { id: "t-2", name: "Pool", usage_count: 12, is_active: true,
    is_system: false },
  { id: "t-3", name: "Active", usage_count: 100, is_active: true,
    is_system: true },
  ...(over.extra || []),
];


beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
  mockDelete.mockReset();
  mockPost.mockResolvedValue({ ok: true });
  mockPatch.mockResolvedValue({ ok: true });
  mockDelete.mockResolvedValue({ ok: true, archived: true });
});


describe("CustomerTagsSettingsPage · P36", () => {
  it("loads and renders active tags on mount", async () => {
    mockGet.mockResolvedValue({ items: _seed(), total: 3 });
    render(<CustomerTagsSettingsPage />);
    await waitFor(() => expect(screen.getByTestId("customer-tags-page")).toBeTruthy());
    expect(screen.getByTestId("customer-tags-row-t-1")).toBeTruthy();
    expect(screen.getByTestId("customer-tags-row-t-2")).toBeTruthy();
    expect(screen.getByTestId("customer-tags-row-t-3")).toBeTruthy();
    // System tag has no archive/rename/merge controls.
    expect(screen.queryByTestId("customer-tags-archive-t-3")).toBeNull();
    expect(screen.queryByTestId("customer-tags-merge-t-3")).toBeNull();
    expect(mockGet).toHaveBeenCalledWith("/customer-tags");
  });

  it("Add POSTs the new tag and reloads", async () => {
    mockGet.mockResolvedValue({ items: _seed() });
    render(<CustomerTagsSettingsPage />);
    await waitFor(() => expect(screen.getByTestId("customer-tags-add-input"))
      .toBeTruthy());
    fireEvent.change(screen.getByTestId("customer-tags-add-input"),
      { target: { value: "Weekly" } });
    fireEvent.click(screen.getByTestId("customer-tags-add-submit"));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/customer-tags", { name: "Weekly" },
    ));
    await waitFor(() => expect(mockGet.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("Duplicate name (409) surfaces an inline error", async () => {
    mockGet.mockResolvedValue({ items: _seed() });
    mockPost.mockRejectedValue({
      body: { detail: "duplicate_tag_name" },
      message: "Conflict",
    });
    render(<CustomerTagsSettingsPage />);
    await waitFor(() => expect(screen.getByTestId("customer-tags-add-input"))
      .toBeTruthy());
    fireEvent.change(screen.getByTestId("customer-tags-add-input"),
      { target: { value: "Pool" } });
    fireEvent.click(screen.getByTestId("customer-tags-add-submit"));
    const errBox = await waitFor(() => screen.getByTestId("customer-tags-error"));
    expect(errBox.textContent).toMatch(/duplicate/i);
  });

  it("Rename PATCHes the row's name", async () => {
    mockGet.mockResolvedValue({ items: _seed() });
    render(<CustomerTagsSettingsPage />);
    await waitFor(() => expect(screen.getByTestId("customer-tags-row-t-1"))
      .toBeTruthy());
    fireEvent.click(screen.getByTestId("customer-tags-rename-t-1"));
    const input = await screen.findByTestId("customer-tags-rename-input-t-1");
    fireEvent.change(input, { target: { value: "Landscaping (v2)" } });
    fireEvent.click(screen.getByTestId("customer-tags-rename-save-t-1"));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      "/customer-tags/t-1", { name: "Landscaping (v2)" },
    ));
  });

  it("Archive DELETEs (soft-archive) the row", async () => {
    mockGet.mockResolvedValue({ items: _seed() });
    render(<CustomerTagsSettingsPage />);
    await waitFor(() => expect(screen.getByTestId("customer-tags-row-t-1"))
      .toBeTruthy());
    fireEvent.click(screen.getByTestId("customer-tags-archive-t-1"));
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("/customer-tags/t-1"));
  });

  it("'Show archived' toggle re-fetches with include_inactive=true", async () => {
    mockGet.mockResolvedValue({ items: _seed() });
    render(<CustomerTagsSettingsPage />);
    await waitFor(() => expect(screen.getByTestId("customer-tags-include-inactive"))
      .toBeTruthy());
    fireEvent.click(screen.getByTestId("customer-tags-include-inactive"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(calls).toContain("/customer-tags?include_inactive=true");
    });
  });

  it("Restore POSTs /{id}/restore on an archived row", async () => {
    const rows = [
      ..._seed(),
      { id: "t-9", name: "Old tag", usage_count: 0, is_active: false,
        is_system: false, archived_at: "2026-01-01T00:00:00Z" },
    ];
    mockGet.mockResolvedValue({ items: rows });
    render(<CustomerTagsSettingsPage />);
    await waitFor(() => expect(screen.getByTestId("customer-tags-include-inactive"))
      .toBeTruthy());
    fireEvent.click(screen.getByTestId("customer-tags-include-inactive"));
    await waitFor(() => expect(screen.getByTestId("customer-tags-restore-t-9"))
      .toBeTruthy());
    fireEvent.click(screen.getByTestId("customer-tags-restore-t-9"));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/customer-tags/t-9/restore", {},
    ));
  });

  it("Merge modal submits {canonical_id, victim_ids} and reloads", async () => {
    mockGet.mockResolvedValue({ items: _seed() });
    mockPost.mockResolvedValue({
      ok: true, canonical_id: "t-1", merged_victims: 1,
      customers_updated: 3,
    });
    render(<CustomerTagsSettingsPage />);
    await waitFor(() => expect(screen.getByTestId("customer-tags-merge-t-1"))
      .toBeTruthy());
    fireEvent.click(screen.getByTestId("customer-tags-merge-t-1"));
    await waitFor(() => expect(screen.getByTestId("customer-tags-merge-modal"))
      .toBeTruthy());
    // Canonical t-1 is excluded; system tag t-3 excluded; only t-2 is a victim option.
    expect(screen.queryByTestId("customer-tags-merge-victim-t-1")).toBeNull();
    expect(screen.queryByTestId("customer-tags-merge-victim-t-3")).toBeNull();
    fireEvent.click(screen.getByTestId("customer-tags-merge-victim-t-2"));
    fireEvent.click(screen.getByTestId("customer-tags-merge-submit"));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/customer-tags/merge",
      { canonical_id: "t-1", victim_ids: ["t-2"] },
    ));
    // Post-submit: modal closes and list reloads.
    await waitFor(() => expect(screen.queryByTestId("customer-tags-merge-modal"))
      .toBeNull());
    expect(mockGet.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
