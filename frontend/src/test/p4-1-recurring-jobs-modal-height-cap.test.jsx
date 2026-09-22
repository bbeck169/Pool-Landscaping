/**
 * Phase P4.1 · Feb-2026 — Edit Recurring Job Modal height cap +
 * scrollable body.
 *
 * Fixes Save being unreachable on short viewports.  The modal
 * becomes a three-section flex column:
 *
 *   Root    max-h-[90vh] flex flex-col       ← height-capped column
 *   Header  shrink-0                          ← pinned top
 *   Body    overflow-y-auto flex-1 min-h-0    ← scrolls internally
 *   Footer  shrink-0                          ← pinned bottom
 *
 * ``min-h-0`` closes the flex-overflow gotcha where the scroll
 * won't kick in inside a flex parent whose default min-height is
 * ``auto``.
 *
 * These assertions are DOM-shape locks so a future refactor can't
 * silently undo the fix.
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
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
    info: vi.fn(), warning: vi.fn(),
  }),
}));
vi.mock("@/theme", () => ({
  colors: {
    brand: "#0284C7", onBrand: "#FFFFFF", onSurface: "#111827",
    onSurfaceInverse: "#FFFFFF", onBrandTertiary: "#0F172A",
    brandTertiary: "#E0F2FE", muted: "#6B7280",
    border: "#E5E7EB", surface: "#FFFFFF",
    surfaceSecondary: "#F8FAFC", searchIcon: "#0284C7",
    error: "#B91C1C",
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
  id: "row-p41",
  customer_id: "cust-p41",
  customer_name: "P4.1 Cust",
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
    if (path === "/recurring-jobs" || path.startsWith("/recurring-jobs?")) return { items: [ROW] };
    if (path === "/service-categories") return { items: [], total: 0 };
    if (path === "/income-categories")  return { items: [], total: 0 };
    if (path.startsWith("/customers"))  return { items: [] };
    if (path === "/technicians")        return { items: [] };
    if (path === "/crews")              return { items: [] };
    if (path === "/recurring-jobs/orphans")
      return { count: 0, items: [] };
    return null;
  });
});


const openModal = async () => {
  render(<MemoryRouter><RecurringJobs /></MemoryRouter>);
  fireEvent.click(await screen.findByTestId("recurring-job-row-row-p41"));
  // The modal renders its Save button only when open.
  await waitFor(() =>
    expect(screen.getByTestId("recurring-jobs-save")).toBeInTheDocument(),
  );
};


describe("Phase P4.1 · Edit Recurring Job modal height cap", () => {
  it("root modal container carries ``max-h-[90vh] flex flex-col``", async () => {
    await openModal();
    // Walk up from Save → footer → root modal container.
    const save = screen.getByTestId("recurring-jobs-save");
    const footer = save.parentElement;                   // Cancel/Save row
    const root = footer.parentElement;                    // modal root
    expect(root.className).toMatch(/max-h-\[90vh\]/);
    expect(root.className).toMatch(/(?:^|\s)flex(?:\s|$)/);
    expect(root.className).toMatch(/flex-col/);
  });

  it("header row carries ``shrink-0`` so it can't collapse under scroll pressure", async () => {
    await openModal();
    // The header hosts the modal close ``X`` button — anchor on
    // that stable testid rather than the heading text so a copy
    // change doesn't break the shape lock.
    const closeBtn = screen.getByTestId("recurring-jobs-modal-close");
    const header = closeBtn.parentElement;
    expect(header.className).toMatch(/shrink-0/);
  });

  it("body carries ``overflow-y-auto flex-1 min-h-0`` — the three classes that make internal scroll work in a flex column", async () => {
    await openModal();
    // The body is the sibling between header and footer inside
    // the modal root.  Find it by walking down from the
    // recurring-jobs-service input (which is inside the body).
    const bodyChild = screen.getByTestId("recurring-jobs-service");
    // The service input is nested inside a <label>; the body is
    // the <label>'s parent.
    const body = bodyChild.closest("label").parentElement;
    expect(body.className).toMatch(/overflow-y-auto/);
    expect(body.className).toMatch(/(?:^|\s)flex-1(?:\s|$)/);
    expect(body.className).toMatch(/min-h-0/);
  });

  it("footer carries ``shrink-0`` so Save stays pinned at short viewports", async () => {
    await openModal();
    const save = screen.getByTestId("recurring-jobs-save");
    const footer = save.parentElement;
    expect(footer.className).toMatch(/shrink-0/);
  });

  it("regression · short viewport (700px) — Save is present + not display:none + inside a shrink-0 footer whose parent is a flex column", async () => {
    // Simulate a phone-tall / laptop-short viewport.  React
    // components don't re-render on ``innerHeight`` change unless
    // they subscribe — this test only proves the DOM/CSS shape is
    // right, which is the actual carrier of the fix.
    Object.defineProperty(window, "innerHeight",
      { writable: true, configurable: true, value: 700 });
    Object.defineProperty(window, "innerWidth",
      { writable: true, configurable: true, value: 1280 });
    window.dispatchEvent(new Event("resize"));

    await openModal();
    const save = screen.getByTestId("recurring-jobs-save");
    // Save is in the DOM — not conditionally hidden.
    expect(save).toBeInTheDocument();
    // No inline ``display: none`` on Save or its ancestors up to
    // the modal root.
    let cur = save;
    while (cur) {
      expect(cur.style.display).not.toBe("none");
      if (cur.className && cur.className.includes && cur.className.includes("max-h-[90vh]")) break;
      cur = cur.parentElement;
    }
    // Footer's ancestor chain: footer.shrink-0 → root.flex.flex-col
    const footer = save.parentElement;
    expect(footer.className).toMatch(/shrink-0/);
    const root = footer.parentElement;
    expect(root.className).toMatch(/(?:^|\s)flex(?:\s|$)/);
    expect(root.className).toMatch(/flex-col/);
  });

  it("no wrapper between header/body/footer has a competing ``overflow-*`` value", async () => {
    // The body is the ONLY node inside the modal root that owns
    // an ``overflow-y-auto``.  A future refactor that adds a
    // wrapper with its own ``overflow-hidden`` around the body
    // would silently kill the internal scroll — pin the invariant.
    await openModal();
    const save = screen.getByTestId("recurring-jobs-save");
    const root = save.parentElement.parentElement;
    // Direct children of root: [header, body, footer].
    const kids = Array.from(root.children);
    expect(kids.length).toBe(3);
    // Only ONE child carries ``overflow-`` — the body.  Header +
    // footer must NOT carry any ``overflow-*`` class.
    const overflowKids = kids.filter(
      (k) => /(^|\s)overflow-/.test(k.className || ""),
    );
    expect(overflowKids.length).toBe(1);
    expect(overflowKids[0].className).toMatch(/overflow-y-auto/);
  });
});
