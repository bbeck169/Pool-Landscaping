/**
 * Phase 56-a.5 · Aug-2026 — Pricebook Suppliers admin page contract.
 *
 * Guards:
 *   • admin/super_admin see the Add button, Edit + Trash icons per
 *     row, and "Show deleted" toggle.
 *   • non-admin roles (manager/technician/customer) see a
 *     "no permission" gate and NO table or actions.
 *   • click Add → fill modal → Save → POST fires → new row appears.
 *   • click trash → confirmation modal → Confirm → DELETE fires →
 *     row disappears from default view.
 *   • toggle Show deleted → GET refetches with ?include_deleted=true
 *     and deleted rows re-appear with a "Deleted" pill + Restore icon.
 *   • click Restore → confirmation → POST /restore fires → row
 *     un-mutes and Restore icon flips back to Edit + Trash.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
const postMock = vi.fn();
const patchMock = vi.fn();
const delMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    patch: (...a) => patchMock(...a),
    del: (...a) => delMock(...a),
  },
  TOKEN_KEY: "token",
}));

const authState = { user: { id: "u1", email: "admin@x", role: "admin" } };
vi.mock("@/auth", () => ({
  useAuth: () => authState,
  AuthProvider: ({ children }) => children,
}));

vi.mock("sonner", () => ({
  toast: Object.assign(
    (msg) => msg,
    { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  ),
}));

vi.mock("@/components/ui-kit", () => ({
  PageHeader: ({ title, subtitle }) => (
    <div>
      <h1>{title}</h1><p>{subtitle}</p>
    </div>
  ),
}));

import PricebookSuppliersAdmin from "@/pages/settings/PricebookSuppliersAdmin";


// Categories fixture — Pool + Landscaping only, matching preflight §4.
const CATS = { items: [
  { id: "cat-pool", name: "Pool" },
  { id: "cat-land", name: "Landscaping" },
]};

function seed(rows, categoriesResp = CATS) {
  getMock.mockImplementation(async (url) => {
    if (url === "/income-categories") return categoriesResp;
    // /pricebook/suppliers?...
    return rows;
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <PricebookSuppliersAdmin />
    </MemoryRouter>,
  );
}

// Row factory — matches the shape the backend serialises.
function supp(id, overrides = {}) {
  return {
    id,
    tenant_id: "t1",
    slug: overrides.slug || `s-${id}`,
    display_name: overrides.display_name || `Supplier ${id}`,
    income_category_id: overrides.income_category_id || "cat-pool",
    is_active: overrides.is_active ?? true,
    is_seed: overrides.is_seed ?? true,
    deleted_at: overrides.deleted_at ?? null,
  };
}


describe("PricebookSuppliersAdmin · admin view", () => {
  beforeEach(() => {
    authState.user = { id: "u1", email: "admin@x", role: "admin" };
    getMock.mockReset(); postMock.mockReset();
    patchMock.mockReset(); delMock.mockReset();
  });
  afterEach(() => {
    getMock.mockReset(); postMock.mockReset();
    patchMock.mockReset(); delMock.mockReset();
  });

  it("renders all 13 seeded rows for admin", async () => {
    const rows = Array.from({ length: 13 },
      (_, i) => supp(`r${i + 1}`, {
        display_name: `Row ${i + 1}`,
        income_category_id: i < 4 ? "cat-pool" : "cat-land",
      }),
    );
    seed(rows);
    await act(async () => renderPage());
    await waitFor(() => screen.getByTestId("pricebook-supplier-row-r1"));

    for (let i = 1; i <= 13; i += 1) {
      expect(screen.getByTestId(`pricebook-supplier-row-r${i}`)).toBeInTheDocument();
    }
    // Admin toolbar controls are all present.
    expect(screen.getByTestId("pricebook-suppliers-add-button")).toBeInTheDocument();
    expect(screen.getByTestId("pricebook-suppliers-show-deleted-toggle")).toBeInTheDocument();
    expect(screen.getByTestId("pricebook-suppliers-filter-category")).toBeInTheDocument();
    // Every row shows Edit + Trash.
    expect(screen.getByTestId("pricebook-supplier-row-edit-r1")).toBeInTheDocument();
    expect(screen.getByTestId("pricebook-supplier-row-delete-r1")).toBeInTheDocument();
    // Seeded pill on seed rows.
    expect(screen.getByTestId("pricebook-supplier-seeded-pill-r1")).toBeInTheDocument();
  });

  it("Add → fill modal → Save fires POST with the correct payload → new row appears", async () => {
    seed([]);
    const created = supp("new1", {
      slug: "watkins", display_name: "Watkins Wholesale",
      income_category_id: "cat-pool", is_seed: false,
    });
    postMock.mockResolvedValueOnce(created);
    await act(async () => renderPage());
    await waitFor(() => screen.getByTestId("pricebook-suppliers-empty"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("pricebook-suppliers-add-button"));
    });
    const modal = await screen.findByTestId("pricebook-supplier-create-modal");
    await act(async () => {
      fireEvent.change(within(modal).getByTestId("pricebook-supplier-create-name"),
        { target: { value: "Watkins Wholesale" } });
      // Slug should auto-derive to "watkins_wholesale"; override to
      // "watkins" to prove the immutable input still accepts edits
      // pre-create.
      fireEvent.change(within(modal).getByTestId("pricebook-supplier-create-slug"),
        { target: { value: "watkins" } });
      fireEvent.change(within(modal).getByTestId("pricebook-supplier-create-category"),
        { target: { value: "cat-pool" } });
    });
    await act(async () => {
      fireEvent.click(within(modal).getByTestId("pricebook-supplier-create-save"));
    });
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith("/pricebook/suppliers", {
        slug: "watkins",
        display_name: "Watkins Wholesale",
        income_category_id: "cat-pool",
      }),
    );
    // New row is prepended optimistically.
    await waitFor(() =>
      expect(screen.getByTestId("pricebook-supplier-row-new1")).toBeInTheDocument(),
    );
  });

  it("Delete → confirmation → confirm → DELETE fires → row drops", async () => {
    const rows = [supp("r1"), supp("r2")];
    seed(rows);
    delMock.mockResolvedValueOnce({ ok: true, id: "r1", deleted: true });
    await act(async () => renderPage());
    await waitFor(() => screen.getByTestId("pricebook-supplier-row-r1"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("pricebook-supplier-row-delete-r1"));
    });
    const modal = await screen.findByTestId("pricebook-supplier-delete-confirm");
    expect(within(modal).getByTestId("pricebook-supplier-delete-confirm-title").textContent)
      .toMatch(/Delete supplier/i);

    await act(async () => {
      fireEvent.click(screen.getByTestId("pricebook-supplier-delete-confirm-btn"));
    });
    await waitFor(() =>
      expect(delMock).toHaveBeenCalledWith("/pricebook/suppliers/r1"),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("pricebook-supplier-row-r1")).not.toBeInTheDocument(),
    );
    // r2 is still there.
    expect(screen.getByTestId("pricebook-supplier-row-r2")).toBeInTheDocument();
  });

  it("Show deleted toggle → GET refetches with ?include_deleted=true → deleted rows appear muted", async () => {
    // First fetch (categories → items). Third fetch (after toggle) → include deleted.
    getMock.mockImplementation(async (url) => {
      if (url === "/income-categories") return CATS;
      if (url.includes("include_deleted=true")) {
        return [supp("r1"), supp("r2", { deleted_at: "2026-08-09T00:00:00" })];
      }
      return [supp("r1")];
    });
    await act(async () => renderPage());
    await waitFor(() => screen.getByTestId("pricebook-supplier-row-r1"));
    expect(screen.queryByTestId("pricebook-supplier-row-r2")).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByTestId("pricebook-suppliers-show-deleted-toggle"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("pricebook-supplier-row-r2")).toBeInTheDocument(),
    );
    // Deleted row shows the DELETED pill + Restore icon.
    expect(screen.getByTestId("pricebook-supplier-deleted-pill-r2")).toBeInTheDocument();
    expect(screen.getByTestId("pricebook-supplier-row-restore-r2")).toBeInTheDocument();
    expect(screen.queryByTestId("pricebook-supplier-row-delete-r2")).not.toBeInTheDocument();
    // At least one fetch used the include_deleted=true query flag.
    const usedFlag = getMock.mock.calls.some(
      (c) => typeof c[0] === "string" && c[0].includes("include_deleted=true"),
    );
    expect(usedFlag).toBe(true);
  });

  it("Restore → confirmation → POST /restore fires → row un-mutes", async () => {
    seed([supp("r2", { deleted_at: "2026-08-09T00:00:00" })]);
    postMock.mockResolvedValueOnce({ ok: true, id: "r2", restored: true });
    await act(async () => renderPage());
    await waitFor(() => screen.getByTestId("pricebook-supplier-row-r2"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("pricebook-supplier-row-restore-r2"));
    });
    const modal = await screen.findByTestId("pricebook-supplier-restore-confirm");
    expect(within(modal).getByRole("heading").textContent).toMatch(/Restore supplier/i);

    await act(async () => {
      fireEvent.click(screen.getByTestId("pricebook-supplier-restore-confirm-btn"));
    });
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/pricebook/suppliers/r2/restore", {},
      ),
    );
    // Row un-mutes: restore icon disappears, edit + trash return.
    await waitFor(() => {
      expect(screen.queryByTestId("pricebook-supplier-row-restore-r2")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("pricebook-supplier-row-delete-r2")).toBeInTheDocument();
    expect(screen.getByTestId("pricebook-supplier-row-edit-r2")).toBeInTheDocument();
  });
});


describe("PricebookSuppliersAdmin · non-admin roles", () => {
  beforeEach(() => {
    getMock.mockReset(); postMock.mockReset();
    patchMock.mockReset(); delMock.mockReset();
  });

  it.each([["manager"], ["technician"], ["customer"]])(
    "renders 'no permission' gate for role=%s and NO Add/Trash/Edit/Show-deleted controls",
    async (role) => {
      authState.user = { id: "u1", email: "x@x", role };
      seed([supp("r1"), supp("r2")]);
      await act(async () => renderPage());

      // Permission gate rendered.
      expect(screen.getByTestId("pricebook-suppliers-no-permission")).toBeInTheDocument();
      // NONE of the admin controls exist.
      expect(screen.queryByTestId("pricebook-suppliers-add-button")).not.toBeInTheDocument();
      expect(screen.queryByTestId("pricebook-suppliers-show-deleted-toggle")).not.toBeInTheDocument();
      expect(screen.queryByTestId("pricebook-supplier-row-delete-r1")).not.toBeInTheDocument();
      expect(screen.queryByTestId("pricebook-supplier-row-edit-r1")).not.toBeInTheDocument();
      // Table itself is not rendered — the gate short-circuits.
      expect(screen.queryByTestId("pricebook-suppliers-table")).not.toBeInTheDocument();
      // And the fetch was never issued (no data leak on the wire).
      expect(getMock.mock.calls.some(
        (c) => typeof c[0] === "string" && c[0].startsWith("/pricebook/suppliers"),
      )).toBe(false);
    },
  );
});
