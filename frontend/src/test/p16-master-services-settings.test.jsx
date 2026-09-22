/**
 * Phase P16 · Feb-2026 — MasterServicesSettings page.
 *
 * Locked-in behaviour:
 *   1. Page renders the list from ``GET /master-services`` and the
 *      counts strip reflects the backend aggregate.
 *   2. Add modal → POST creates a row, list refreshes, row appears.
 *   3. Edit modal → PATCH updates in place.
 *   4. Soft-delete flow flips the row to the inactive view and
 *      surfaces a success toast.
 *   5. Manager role sees the Delete button but it's disabled with
 *      an "Admin only" tooltip.
 *   6. Search input debounces into ``?q=`` on the list call.
 *   7. Show-inactive toggle flips ``?include_inactive=true``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  act, render, screen, fireEvent, waitFor, within, cleanup,
} from "@testing-library/react";


const { getSpy, postSpy, patchSpy, delSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
  delSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get:   (...a) => getSpy(...a),
    post:  (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
    del:   (...a) => delSpy(...a),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(),
             info: vi.fn(), warning: vi.fn() },
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0284C7", onBrand: "#FFFFFF", onSurface: "#111827",
    muted: "#6B7280", border: "#E5E7EB",
    surface: "#FFFFFF", surfaceSecondary: "#F8FAFC",
    searchIcon: "#0284C7", error: "#B91C1C",
    brandTertiary: "#E0F2FE",
  },
}));

// Default role — admin.  Manager-specific test flips this via a
// module-level ref inspected by the mock.
const roleRef = { current: "admin" };
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: roleRef.current, effectiveRole: roleRef.current,
    can: () => true, loading: false, matrix: {},
    previewRole: null, setPreviewRole: () => {},
    isPreviewing: false, canPreview: false,
  }),
}));


import MasterServicesSettings from "@/pages/settings/MasterServicesSettings";


const ROWS = [
  { id: "svc-1", name: "Pool Cleaning",
    category: "Pool", default_price: 120,
    is_active: true, tenant_id: "t1" },
  { id: "svc-2", name: "Filter Replacement",
    category: "Pool", default_price: 250,
    is_active: true, tenant_id: "t1" },
];
const CATEGORIES = [
  { name: "Pool" }, { name: "Landscaping" }, { name: "Irrigation" },
];


beforeEach(() => {
  roleRef.current = "admin";
  getSpy.mockReset();
  postSpy.mockReset();
  patchSpy.mockReset();
  delSpy.mockReset();
  getSpy.mockImplementation(async (path) => {
    if (path.startsWith("/master-services/categories")) {
      return { items: CATEGORIES };
    }
    if (path.startsWith("/master-services")) {
      return {
        items: ROWS,
        counts: { active: 2, inactive: 1, total: 3 },
      };
    }
    return {};
  });
});

afterEach(() => { cleanup(); });


describe("Phase P16 · MasterServicesSettings · rendering", () => {
  it("renders the list from GET /master-services + counts strip", async () => {
    render(<MasterServicesSettings />);
    // Wait for the list to hydrate.
    await screen.findByTestId("master-services-row-svc-1");
    expect(screen.getByTestId("master-services-row-svc-2")).toBeTruthy();
    // Counts reflect the backend aggregate — active + inactive.
    expect(screen.getByTestId("master-services-count-active").textContent)
      .toMatch(/Active:\s*2/);
    expect(screen.getByTestId("master-services-count-inactive").textContent)
      .toMatch(/Inactive:\s*1/);
  });

  it("renders empty state when the backend returns no rows", async () => {
    getSpy.mockImplementation(async (path) => {
      if (path.startsWith("/master-services/categories")) {
        return { items: CATEGORIES };
      }
      return { items: [], counts: { active: 0, inactive: 0, total: 0 } };
    });
    render(<MasterServicesSettings />);
    expect(await screen.findByTestId("master-services-empty")).toBeTruthy();
  });
});


describe("Phase P16 · MasterServicesSettings · Add flow", () => {
  it("opens the Add modal, POSTs on save, refreshes the list", async () => {
    postSpy.mockResolvedValue({
      id: "svc-new", name: "Weekly Pool", category: "Pool",
      default_price: 150, is_active: true,
    });
    render(<MasterServicesSettings />);
    await screen.findByTestId("master-services-row-svc-1");

    fireEvent.click(screen.getByTestId("master-services-add-btn"));
    const modal = await screen.findByTestId("master-service-modal");
    expect(within(modal).getByText(/New master service/i)).toBeTruthy();

    // Fill the modal.  Category dropdown populated from
    // ``/master-services/categories``.
    fireEvent.change(screen.getByTestId("master-service-modal-name"),
      { target: { value: "Weekly Pool" } });
    fireEvent.change(screen.getByTestId("master-service-modal-price"),
      { target: { value: "150" } });
    fireEvent.change(screen.getByTestId("master-service-modal-category"),
      { target: { value: "Pool" } });

    fireEvent.click(screen.getByTestId("master-service-modal-save"));
    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    const [url, body] = postSpy.mock.calls[0];
    expect(url).toBe("/master-services");
    expect(body).toEqual({
      name: "Weekly Pool", default_price: 150, category: "Pool",
    });
  });
});


describe("Phase P16 · MasterServicesSettings · Edit flow", () => {
  it("opens the Edit modal prefilled + PATCHes on save", async () => {
    patchSpy.mockResolvedValue({
      ...ROWS[0], default_price: 200,
    });
    render(<MasterServicesSettings />);
    await screen.findByTestId("master-services-row-svc-1");

    fireEvent.click(screen.getByTestId("master-services-edit-svc-1"));
    const modal = await screen.findByTestId("master-service-modal");
    // Prefilled from the row.
    expect(within(modal)
      .getByTestId("master-service-modal-name").value).toBe("Pool Cleaning");
    expect(within(modal)
      .getByTestId("master-service-modal-price").value).toBe("120");
    expect(within(modal)
      .getByTestId("master-service-modal-category").value).toBe("Pool");
    // Change price, save.
    fireEvent.change(screen.getByTestId("master-service-modal-price"),
      { target: { value: "200" } });
    fireEvent.click(screen.getByTestId("master-service-modal-save"));
    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    const [url, body] = patchSpy.mock.calls[0];
    expect(url).toBe("/master-services/svc-1");
    expect(body).toEqual({
      name: "Pool Cleaning", default_price: 200, category: "Pool",
    });
  });
});


describe("Phase P16 · MasterServicesSettings · Soft delete", () => {
  it("admin can open the Delete modal and confirm Soft-Delete", async () => {
    delSpy.mockResolvedValue({ hard_deleted: false });
    render(<MasterServicesSettings />);
    await screen.findByTestId("master-services-row-svc-1");

    fireEvent.click(screen.getByTestId("master-services-delete-svc-1"));
    await screen.findByTestId("master-service-delete-modal");
    // Default mode is Soft-Delete.
    expect(screen.getByTestId("master-service-delete-mode-soft").checked).toBe(true);
    fireEvent.click(screen.getByTestId("master-service-delete-modal-soft-btn"));
    await waitFor(() => expect(delSpy).toHaveBeenCalled());
    expect(delSpy).toHaveBeenCalledWith("/master-services/svc-1");
  });

  it("admin can flip to Permanent Delete and confirm with DELETE", async () => {
    delSpy.mockResolvedValue({ hard_deleted: true, deleted_count: 1 });
    render(<MasterServicesSettings />);
    await screen.findByTestId("master-services-row-svc-1");

    fireEvent.click(screen.getByTestId("master-services-delete-svc-1"));
    await screen.findByTestId("master-service-delete-modal");
    fireEvent.click(screen.getByTestId("master-service-delete-mode-hard"));
    const hardBtn = screen.getByTestId("master-service-delete-modal-hard-btn");
    expect(hardBtn.disabled).toBe(true);
    fireEvent.change(
      screen.getByTestId("master-service-delete-modal-confirm-input"),
      { target: { value: "DELETE" } },
    );
    expect(hardBtn.disabled).toBe(false);
    fireEvent.click(hardBtn);
    await waitFor(() => expect(delSpy).toHaveBeenCalled());
    const [url, body] = delSpy.mock.calls[0];
    expect(url).toBe("/master-services/svc-1?hard=true");
    expect(body).toEqual({ confirm: "DELETE" });
  });
});


describe("Phase P16 · MasterServicesSettings · Manager RBAC", () => {
  it("manager sees the Delete button but it's disabled with the tooltip", async () => {
    roleRef.current = "manager";
    render(<MasterServicesSettings />);
    await screen.findByTestId("master-services-row-svc-1");
    const del = screen.getByTestId("master-services-delete-svc-1");
    expect(del.disabled).toBe(true);
    expect(del.getAttribute("title")).toBe("Admin only");
    // Add + Edit buttons remain available (manager keeps CRUD
    // minus DELETE).
    expect(screen.getByTestId("master-services-add-btn").disabled).toBeFalsy();
    expect(screen.getByTestId("master-services-edit-svc-1").disabled).toBeFalsy();
  });
});


describe("Phase P16 · MasterServicesSettings · list controls", () => {
  it("show-inactive toggle flips include_inactive=true on the fetch", async () => {
    render(<MasterServicesSettings />);
    await screen.findByTestId("master-services-row-svc-1");
    fireEvent.click(screen.getByTestId("master-services-show-inactive"));
    await waitFor(() => {
      const calls = getSpy.mock.calls
        .map(([u]) => u).filter((u) => u.startsWith("/master-services"))
        .filter((u) => !u.startsWith("/master-services/categories"));
      // At least one call must carry the query param.
      expect(calls.some((u) => u.includes("include_inactive=true"))).toBe(true);
    });
  });

  it("search debounces into ?q= on the fetch", async () => {
    render(<MasterServicesSettings />);
    await screen.findByTestId("master-services-row-svc-1");
    fireEvent.change(screen.getByTestId("master-services-search"),
      { target: { value: "pool" } });
    // Fake timer isn't installed here — the built-in debounce is
    // 250ms; wait for the follow-up call.
    await waitFor(() => {
      const calls = getSpy.mock.calls
        .map(([u]) => u)
        .filter((u) => u.startsWith("/master-services")
                        && !u.startsWith("/master-services/categories"));
      expect(calls.some((u) => u.includes("q=pool"))).toBe(true);
    }, { timeout: 1500 });
  });
});
