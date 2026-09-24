/**
 * Task D · Feb-2026 — Employee Benefits vitest coverage.
 *
 * Pins the frontend UX contracts of
 * ``pages/workforce/EmployeeBenefits.jsx``:
 *   1. Admin view — "New Benefit" button + edit/delete controls
 *      on each tile.
 *   2. Technician view — no CRUD controls; tiles still clickable
 *      as ``<a target="_blank" rel="noopener noreferrer">``.
 *   3. "New Benefit" flow — click button → dialog opens → fill
 *      form → POST fires → grid refreshes → new tile appears.
 *   4. Edit flow — click edit → dialog opens with pre-filled
 *      values → PATCH fires → grid refreshes.
 *   5. Delete flow — click delete → confirm → DELETE fires →
 *      tile removed.
 *   6. Icon preset picker — all 12 curated Lucide names visible;
 *      selection persists into the form state via aria-pressed.
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

vi.mock("sonner", () => ({
  toast: Object.assign(() => {},
    { success: () => {}, error: () => {} }),
}));

let _mockRole = "admin";
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: _mockRole, effectiveRole: _mockRole,
    can: () => true, loading: false,
  }),
}));

import EmployeeBenefits, { ICON_ALLOWLIST } from "@/pages/workforce/EmployeeBenefits";


const _seededTile = {
  id: "b-1",
  tenant_id: "t-a",
  title: "Perks at Work",
  description: "Discounts and rewards on 30,000+ brands.",
  external_url: "https://www.perksatwork.com/login",
  icon: "gift",
  is_active: true,
  sort_order: 0,
  deleted_at: null,
};


beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
  mockDelete.mockReset();
  _mockRole = "admin";
});


describe("Task D · Employee Benefits page", () => {
  it("admin sees New Benefit button + edit/delete controls per tile", async () => {
    _mockRole = "admin";
    mockGet.mockResolvedValue({ items: [_seededTile], count: 1 });
    render(<EmployeeBenefits />);

    await waitFor(() =>
      expect(screen.getByTestId("benefit-tile-b-1")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("benefits-new-btn")).toBeInTheDocument();
    expect(screen.getByTestId("benefit-edit-b-1")).toBeInTheDocument();
    expect(screen.getByTestId("benefit-delete-b-1")).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith("/benefits");
  });

  it("technician sees tiles read-only — no CRUD controls, tile stays clickable", async () => {
    _mockRole = "technician";
    mockGet.mockResolvedValue({ items: [_seededTile], count: 1 });
    render(<EmployeeBenefits />);

    await waitFor(() =>
      expect(screen.getByTestId("benefit-tile-b-1")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("benefits-new-btn")).toBeNull();
    expect(screen.queryByTestId("benefit-edit-b-1")).toBeNull();
    expect(screen.queryByTestId("benefit-delete-b-1")).toBeNull();

    // Tile link is present with the correct target + rel.
    const link = screen.getByTestId("benefit-link-b-1");
    expect(link.getAttribute("href")).toBe(
      "https://www.perksatwork.com/login",
    );
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("New Benefit flow — dialog opens, POST fires, grid refreshes", async () => {
    _mockRole = "admin";
    // First GET returns [], second GET (after create) returns the
    // new tile.
    mockGet
      .mockResolvedValueOnce({ items: [], count: 0 })
      .mockResolvedValueOnce({ items: [
        { ..._seededTile, id: "b-new", title: "New Perk",
          external_url: "https://ex.com/new" },
      ], count: 1 });
    mockPost.mockResolvedValue({
      id: "b-new", title: "New Perk",
      external_url: "https://ex.com/new", icon: "coffee",
    });

    render(<EmployeeBenefits />);
    await waitFor(() =>
      expect(screen.getByTestId("benefits-empty")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId("benefits-new-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("benefit-modal")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByTestId("benefit-modal-title"),
      { target: { value: "New Perk" } });
    fireEvent.change(screen.getByTestId("benefit-modal-url"),
      { target: { value: "https://ex.com/new" } });
    fireEvent.click(screen.getByTestId("benefit-modal-icon-coffee"));
    fireEvent.click(screen.getByTestId("benefit-modal-save"));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/benefits",
      expect.objectContaining({
        title: "New Perk",
        external_url: "https://ex.com/new",
        icon: "coffee",
      }),
    ));

    // Grid refetch fired after save.
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  });

  it("Edit flow — dialog pre-fills, PATCH fires, grid refreshes", async () => {
    _mockRole = "admin";
    mockGet
      .mockResolvedValueOnce({ items: [_seededTile], count: 1 })
      .mockResolvedValueOnce({ items: [
        { ..._seededTile, description: "updated copy" },
      ], count: 1 });
    mockPatch.mockResolvedValue({
      ..._seededTile, description: "updated copy",
    });

    render(<EmployeeBenefits />);
    await waitFor(() =>
      expect(screen.getByTestId("benefit-tile-b-1")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId("benefit-edit-b-1"));
    await waitFor(() =>
      expect(screen.getByTestId("benefit-modal")).toBeInTheDocument(),
    );

    // Pre-filled with existing values.
    const titleInput = screen.getByTestId("benefit-modal-title");
    expect(titleInput.value).toBe("Perks at Work");

    fireEvent.change(
      screen.getByTestId("benefit-modal-description"),
      { target: { value: "updated copy" } },
    );
    fireEvent.click(screen.getByTestId("benefit-modal-save"));

    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      "/benefits/b-1",
      expect.objectContaining({ description: "updated copy" }),
    ));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  });

  it("Delete flow — confirm modal opens, DELETE fires, tile removed", async () => {
    _mockRole = "admin";
    mockGet
      .mockResolvedValueOnce({ items: [_seededTile], count: 1 })
      .mockResolvedValueOnce({ items: [], count: 0 });
    mockDelete.mockResolvedValue({ ok: true, deleted: true,
                                       benefit_id: "b-1" });

    render(<EmployeeBenefits />);
    await waitFor(() =>
      expect(screen.getByTestId("benefit-tile-b-1")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId("benefit-delete-b-1"));
    await waitFor(() =>
      expect(screen.getByTestId("benefit-delete-modal")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("benefit-delete-confirm"));

    await waitFor(() =>
      expect(mockDelete).toHaveBeenCalledWith("/benefits/b-1"),
    );
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  });

  it("Icon preset picker renders all 12 curated options + selection persists", async () => {
    _mockRole = "admin";
    mockGet.mockResolvedValue({ items: [], count: 0 });

    render(<EmployeeBenefits />);
    await waitFor(() =>
      expect(screen.getByTestId("benefits-empty")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByTestId("benefits-new-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("benefit-modal-icon-picker"))
        .toBeInTheDocument(),
    );

    // Every curated icon is present.
    for (const name of ICON_ALLOWLIST) {
      expect(screen.getByTestId(`benefit-modal-icon-${name}`))
        .toBeInTheDocument();
    }

    // Default selection is "gift"; clicking "shield" flips it.
    expect(
      screen.getByTestId("benefit-modal-icon-gift")
        .getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(screen.getByTestId("benefit-modal-icon-shield"));
    expect(
      screen.getByTestId("benefit-modal-icon-shield")
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      screen.getByTestId("benefit-modal-icon-gift")
        .getAttribute("aria-pressed"),
    ).toBe("false");
  });
});
