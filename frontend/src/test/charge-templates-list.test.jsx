/**
 * Phase F2 · Feb-2026 — Admin Charge Templates list page tests.
 *
 * Covers:
 *   • renders the list from GET /api/charge-templates
 *   • search filters the visible rows without hitting the network
 *   • "Add template" opens the editor modal
 *   • ArmToDelete calls DELETE and refreshes the list on success
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockGet = vi.fn();
const mockDel = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();

vi.mock("../api", () => ({
  api: {
    get: (...args) => mockGet(...args),
    del: (...args) => mockDel(...args),
    post: (...args) => mockPost(...args),
    put: (...args) => mockPut(...args),
  },
}));

import AdminChargeTemplatesPage from "@/pages/admin/AdminChargeTemplatesPage";

const T1 = {
  id: "tpl-1", name: "Chlorine Shock Combo", description: "3-item chem bundle",
  category: "chemicals", last_used_at: "2026-02-05T10:00:00Z",
  line_items: [
    { name: "Cal-Hypo 1lb", unit_price: 12.5, quantity: 2 },
    { name: "Brush", unit_price: 15.0, quantity: 1 },
    { name: "Labor", unit_price: 45.0, quantity: 1 },
  ],
};
const T2 = {
  id: "tpl-2", name: "Filter Service", description: "Media + labor",
  category: "maintenance", last_used_at: null,
  line_items: [
    { name: "Filter Media", unit_price: 60.0, quantity: 1 },
    { name: "Labor", unit_price: 75.0, quantity: 1 },
  ],
};

beforeEach(() => {
  mockGet.mockReset(); mockDel.mockReset();
  mockPost.mockReset(); mockPut.mockReset();
  mockGet.mockResolvedValue({ templates: [T1, T2], count: 2 });
  mockDel.mockResolvedValue({ ok: true });
});

const renderPage = () =>
  render(<MemoryRouter><AdminChargeTemplatesPage /></MemoryRouter>);

describe("AdminChargeTemplatesPage · list", () => {
  it("renders templates loaded from /charge-templates", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`charge-template-row-${T1.id}`)).toBeTruthy(),
    );
    expect(screen.getByTestId(`charge-template-row-${T2.id}`)).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith("/charge-templates");
  });

  it("filters visible rows by the search box", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`charge-template-row-${T1.id}`)).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("charge-templates-search"), {
      target: { value: "filter" },
    });
    expect(screen.queryByTestId(`charge-template-row-${T1.id}`)).toBeNull();
    expect(screen.getByTestId(`charge-template-row-${T2.id}`)).toBeTruthy();
  });

  it("clicking Add template opens the editor modal", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`charge-template-row-${T1.id}`)).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("charge-template-new-btn"));
    expect(screen.getByTestId("charge-template-editor")).toBeTruthy();
    expect(screen.getByTestId("charge-template-editor-title").textContent)
      .toMatch(/new template/i);
  });

  it("Delete via ArmToDelete calls DELETE + re-fetches the list", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId(`charge-template-row-${T1.id}`)).toBeTruthy(),
    );
    // ArmToDelete renders a single button when count < threshold (1).
    const delBtn = screen.getByTestId(`charge-template-delete-${T1.id}-btn`);
    fireEvent.click(delBtn);
    await waitFor(() =>
      expect(mockDel).toHaveBeenCalledWith(`/charge-templates/${T1.id}`),
    );
    // list re-fetched.
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  });
});
