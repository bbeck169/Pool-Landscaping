/**
 * Phase P3 · Feb-2026 — Restore Edit affordance on Recurring Jobs.
 *
 * Two entry points must both open the Edit modal for the correct
 * row:
 *   (a) row click anywhere except the row's bulk-select checkbox
 *   (b) a new 3-dot Actions menu on the far-right column with
 *       Edit / Pause-Resume / Delete permanently
 *
 * This suite verifies each behaviour against the real component
 * mounted with a mocked API (same mocking pattern as
 * ``recurring-jobs-is-active-and-hard-delete.test.jsx``).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { getSpy, delSpy, postSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  delSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    del: (...a) => delSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(),
             info: vi.fn(), warning: vi.fn() },
}));
vi.mock("@/theme", () => ({
  colors: {
    brand: "#0284C7", onBrand: "#FFFFFF", onSurface: "#111827",
    onSurfaceInverse: "#FFFFFF", onBrandTertiary: "#0F172A",
    brandTertiary: "#E0F2FE", muted: "#6B7280",
    border: "#E5E7EB", surface: "#FFFFFF",
    surfaceSecondary: "#F8FAFC", searchIcon: "#0284C7",
    error: "#B91C1C",
    // Task E · Feb-2026 — NavyFilterBar tokens.
    nav: { bg: "#1B1F5C", border: "rgba(255,255,255,0.10)", fg: "#FFFFFF", fgMuted: "rgba(255,255,255,0.72)" },
    gradient: { css: "linear-gradient(90deg, #22C55E 0%, #1B1F5C 100%)", fg: "#FFFFFF", textShadow: "0 1px 2px rgba(0, 0, 0, 0.25)" },
    inputBorder: "#3B82F6",
  },
}));
vi.mock("@/components/customers/CustomerCombobox", () => ({
  default: () => null,
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: "admin", effectiveRole: "admin", can: () => true,
    loading: false, matrix: {}, previewRole: null,
    setPreviewRole: () => {}, isPreviewing: false, canPreview: false,
  }),
}));


import RecurringJobs from "@/pages/admin/RecurringJobs";


const ROW = {
  id: "row-p3",
  customer_id: "cust-p3",
  customer_name: "P3 Cust",
  service_type: "Weekly Pool",
  frequency: "weekly", day_of_week: 0,
  start_date: "2026-02-02",
  price_cents: 12000,
  active: true, is_active: true,
  upcoming: [],
};


beforeEach(() => {
  getSpy.mockReset();
  delSpy.mockReset();
  postSpy.mockReset();
  patchSpy.mockReset();
  getSpy.mockImplementation(async (path) => {
    if (path === "/recurring-jobs" || path.startsWith("/recurring-jobs?")) {
      return { items: [ROW] };
    }
    if (path.startsWith("/customers")) return { items: [] };
    if (path === "/technicians") return { items: [] };
    if (path === "/crews") return { items: [] };
    if (path === "/recurring-jobs/orphans") return { count: 0, items: [] };
    return null;
  });
  patchSpy.mockResolvedValue({ ...ROW });
  delSpy.mockResolvedValue({ ok: true });
});


const mount = () =>
  render(<MemoryRouter><RecurringJobs /></MemoryRouter>);


// ─────────────────────────────────────────────────────────────
// Entry point (a) — row click
// ─────────────────────────────────────────────────────────────
describe("Phase P3 · row click restoration", () => {
  it("clicking the row body opens the Edit modal preloaded with the row", async () => {
    mount();
    const row = await screen.findByTestId("recurring-job-row-row-p3");
    fireEvent.click(row);
    // The modal renders its Save button + price field ONLY after
    // ``modalOpen && editing`` is truthy, so this is a clean signal
    // the edit modal opened for the right row.
    await waitFor(() =>
      expect(screen.getByTestId("recurring-jobs-price")).toBeInTheDocument(),
    );
    // Preloaded price (row.price_cents ÷ 100 → "120.00").
    expect(screen.getByTestId("recurring-jobs-price").value).toBe("120.00");
  });

  it("clicking the bulk-select checkbox does NOT open the modal", async () => {
    mount();
    // Wait for the row to be present first so we can find the
    // checkbox under it.
    await screen.findByTestId("recurring-job-row-row-p3");
    const box = screen.getByTestId("recurring-row-checkbox-row-p3");
    fireEvent.click(box);
    // Give the render a beat.
    await new Promise((r) => setTimeout(r, 30));
    // Modal must NOT be open — the price field is only rendered
    // when the modal is open.
    expect(screen.queryByTestId("recurring-jobs-price")).toBeNull();
  });
});


// ─────────────────────────────────────────────────────────────
// Entry point (b) — 3-dot Actions menu
// ─────────────────────────────────────────────────────────────
describe("Phase P3 · 3-dot Actions menu", () => {
  it("clicking the 3-dot Actions button opens a menu with Edit / Pause / Delete permanently", async () => {
    mount();
    const btn = await screen.findByTestId("recurring-row-actions-btn-row-p3");
    fireEvent.click(btn);
    // Menu items present.
    expect(screen.getByTestId("recurring-row-actions-edit-row-p3"))
      .toBeInTheDocument();
    expect(screen.getByTestId("recurring-row-actions-pause-resume-row-p3"))
      .toBeInTheDocument();
    expect(screen.getByTestId("recurring-row-actions-hard-delete-row-p3"))
      .toBeInTheDocument();
    // Popover has role="menu" for a11y.
    expect(screen.getByTestId("recurring-row-actions-menu-row-p3")
      .getAttribute("role")).toBe("menu");
    // Trigger button carries aria-label + aria-haspopup="menu".
    expect(btn.getAttribute("aria-haspopup")).toBe("menu");
    expect(btn.getAttribute("aria-label")).toMatch(/actions for/i);
  });

  it("clicking the trigger button does NOT open the row's Edit modal (menu-only)", async () => {
    mount();
    const btn = await screen.findByTestId("recurring-row-actions-btn-row-p3");
    fireEvent.click(btn);
    // The trigger opens the popover — NOT the Edit modal.
    expect(screen.queryByTestId("recurring-jobs-price")).toBeNull();
    // ...but the menu itself is up.
    expect(screen.getByTestId("recurring-row-actions-menu-row-p3"))
      .toBeInTheDocument();
  });

  it("menu → Edit opens the Edit modal for the correct row", async () => {
    mount();
    fireEvent.click(
      await screen.findByTestId("recurring-row-actions-btn-row-p3"),
    );
    fireEvent.click(screen.getByTestId("recurring-row-actions-edit-row-p3"));
    await waitFor(() =>
      expect(screen.getByTestId("recurring-jobs-price")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("recurring-jobs-price").value).toBe("120.00");
  });

  it("menu → Pause calls PATCH /recurring-jobs/{id} with is_active + active both false", async () => {
    mount();
    fireEvent.click(
      await screen.findByTestId("recurring-row-actions-btn-row-p3"),
    );
    fireEvent.click(
      screen.getByTestId("recurring-row-actions-pause-resume-row-p3"),
    );
    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    const [url, body] = patchSpy.mock.calls[0];
    expect(url).toBe("/recurring-jobs/row-p3");
    // Phase P18 · Feb-2026 — the pause PATCH now carries BOTH the
    // canonical ``is_active`` and the legacy ``active`` mirror so
    // the backend detects the True→False transition on the
    // canonical field and fires the auto-cancel side-effect.
    expect(body).toEqual({ is_active: false, active: false });
  });

  it("menu → Resume calls PATCH /recurring-jobs/{id} with is_active + active both true when row is paused", async () => {
    // Re-seed a paused row.
    const pausedRow = { ...ROW, active: false, is_active: false };
    getSpy.mockImplementation(async (path) => {
      if (path === "/recurring-jobs" || path.startsWith("/recurring-jobs?")) return { items: [pausedRow] };
      if (path.startsWith("/customers")) return { items: [] };
      if (path === "/technicians") return { items: [] };
      if (path === "/crews") return { items: [] };
      if (path === "/recurring-jobs/orphans") return { count: 0, items: [] };
      return null;
    });
    mount();
    fireEvent.click(
      await screen.findByTestId("recurring-row-actions-btn-row-p3"),
    );
    const item = screen.getByTestId("recurring-row-actions-pause-resume-row-p3");
    // Label reflects the paused state.
    expect(item.textContent).toMatch(/Resume/);
    fireEvent.click(item);
    await waitFor(() => expect(patchSpy).toHaveBeenCalled());
    // Phase P18 · Feb-2026 — see the Pause test above; the same
    // dual-key contract applies to Resume so the backend detects
    // the False→True transition on the canonical field.
    expect(patchSpy.mock.calls[0][1]).toEqual({ is_active: true, active: true });
  });

  it("menu → Delete permanently opens the confirm dialog (no direct DELETE fire yet)", async () => {
    mount();
    fireEvent.click(
      await screen.findByTestId("recurring-row-actions-btn-row-p3"),
    );
    fireEvent.click(
      screen.getByTestId("recurring-row-actions-hard-delete-row-p3"),
    );
    // Confirmation modal renders (dedicated hard-delete flow).
    await waitFor(() =>
      expect(
        screen.getByTestId("recurring-job-hard-delete-confirm-modal"),
      ).toBeInTheDocument(),
    );
    // The DELETE has NOT fired yet — user must confirm first.
    expect(delSpy).not.toHaveBeenCalled();
    // Now confirm.
    fireEvent.click(
      screen.getByTestId("recurring-job-hard-delete-confirm-btn"),
    );
    await waitFor(() => expect(delSpy).toHaveBeenCalled());
    expect(delSpy.mock.calls[0][0]).toBe(
      "/recurring-jobs/row-p3?hard=true",
    );
  });
});
