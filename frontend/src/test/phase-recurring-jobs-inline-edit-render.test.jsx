/**
 * Feb-2026 · Recurring Jobs · inline-edit render smoke.
 *
 * Verifies the two new columns (Service Category + Income Category)
 * mount as ``<CategoryComboCell>`` in click-to-edit mode, and that
 * clicking the display state enters edit + fires the resolve-or-create
 * roundtrip on save.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPatch = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {},
    { success: () => {}, error: () => {} }),
}));

import CategoryComboCell from "../components/recurring/CategoryComboCell";


describe("CategoryComboCell · inline edit render", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    mockPatch.mockReset();
  });

  it("renders display state with the current value", () => {
    render(
      <CategoryComboCell
        axis="income"
        row={{ id: "tpl-1" }}
        value="Pool"
        patchUrl="/recurring-jobs/tpl-1"
        onPatched={() => {}}
      />,
    );
    const display = screen.getByTestId("recurring-cat-income-tpl-1-display");
    expect(display.textContent).toContain("Pool");
  });

  it("click enters edit mode + loads options", async () => {
    mockGet.mockResolvedValue({ items: [
      { id: "cat-1", name: "Pool" },
      { id: "cat-2", name: "Chemicals" },
    ] });
    render(
      <CategoryComboCell
        axis="income"
        row={{ id: "tpl-2" }}
        value=""
        patchUrl="/recurring-jobs/tpl-2"
        onPatched={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("recurring-cat-income-tpl-2-display"));
    await waitFor(() =>
      expect(screen.getByTestId("recurring-cat-income-tpl-2-input"))
        .toBeInTheDocument(),
    );
    expect(mockGet).toHaveBeenCalledWith(
      "/income-categories?include_archived=false",
    );
  });

  it("Enter triggers resolve-or-create then PATCH", async () => {
    mockGet.mockResolvedValue({ items: [] });
    mockPost.mockResolvedValue({
      created: true,
      category: { id: "cat-new", name: "Weekly Service" },
    });
    mockPatch.mockResolvedValue({});
    const onPatched = vi.fn();
    render(
      <CategoryComboCell
        axis="service"
        row={{ id: "tpl-3" }}
        value=""
        patchUrl="/recurring-jobs/tpl-3"
        onPatched={onPatched}
      />,
    );
    fireEvent.click(screen.getByTestId("recurring-cat-service-tpl-3-display"));
    const input = await screen.findByTestId("recurring-cat-service-tpl-3-input");
    fireEvent.change(input, { target: { value: "Weekly Service" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost).toHaveBeenCalledWith(
      "/service-categories/resolve-or-create",
      { name: "Weekly Service" },
    );
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      "/recurring-jobs/tpl-3",
      { service_category_id: "cat-new" },
    ));
    await waitFor(() => expect(onPatched).toHaveBeenCalledWith({
      service_category_id: "cat-new",
      service_category_name: "Weekly Service",
    }));
  });

  it("ESC cancels without any network call", async () => {
    mockGet.mockResolvedValue({ items: [] });
    render(
      <CategoryComboCell
        axis="income"
        row={{ id: "tpl-4" }}
        value="Pool"
        patchUrl="/recurring-jobs/tpl-4"
        onPatched={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("recurring-cat-income-tpl-4-display"));
    const input = await screen.findByTestId("recurring-cat-income-tpl-4-input");
    fireEvent.change(input, { target: { value: "Chemicals" } });
    fireEvent.keyDown(input, { key: "Escape" });
    // After ESC, editor tears down + no POST/PATCH.
    await waitFor(() =>
      expect(screen.queryByTestId("recurring-cat-income-tpl-4-input"))
        .toBeNull(),
    );
    expect(mockPost).not.toHaveBeenCalled();
    expect(mockPatch).not.toHaveBeenCalled();
  });
});
