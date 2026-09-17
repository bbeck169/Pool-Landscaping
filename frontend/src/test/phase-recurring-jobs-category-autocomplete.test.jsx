/**
 * Feb-2026 · Recurring Jobs · category autocomplete typeahead.
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


describe("CategoryComboCell · autocomplete typeahead", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    mockPatch.mockReset();
  });

  it("typing filters the master-list suggestions", async () => {
    mockGet.mockResolvedValue({ items: [
      { id: "c-pool", name: "Pool" },
      { id: "c-chem", name: "Chemicals" },
      { id: "c-repair", name: "Repair" },
    ] });
    render(
      <CategoryComboCell
        axis="income"
        row={{ id: "tpl-A" }}
        value=""
        onPatched={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("recurring-cat-income-tpl-A-display"));
    const input = await screen.findByTestId("recurring-cat-income-tpl-A-input");
    // Wait for options to load.
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    fireEvent.change(input, { target: { value: "che" } });
    await waitFor(() =>
      expect(screen.getByTestId("recurring-cat-income-tpl-A-suggestion-c-chem"))
        .toBeInTheDocument(),
    );
    expect(screen.queryByTestId("recurring-cat-income-tpl-A-suggestion-c-pool"))
      .toBeNull();
    expect(screen.queryByTestId("recurring-cat-income-tpl-A-suggestion-c-repair"))
      .toBeNull();
  });

  it("clicking a suggestion populates the input", async () => {
    mockGet.mockResolvedValue({ items: [
      { id: "c-chem", name: "Chemicals" },
    ] });
    render(
      <CategoryComboCell
        axis="income"
        row={{ id: "tpl-B" }}
        value=""
        onPatched={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("recurring-cat-income-tpl-B-display"));
    const suggestion = await screen.findByTestId(
      "recurring-cat-income-tpl-B-suggestion-c-chem",
    );
    fireEvent.click(suggestion);
    const input = screen.getByTestId("recurring-cat-income-tpl-B-input");
    expect(input.value).toBe("Chemicals");
  });

  it("saving a NEW name calls resolve-or-create with the typed value", async () => {
    mockGet.mockResolvedValue({ items: [] });
    mockPost.mockResolvedValue({
      created: true,
      category: { id: "c-new", name: "Warranty Work" },
    });
    mockPatch.mockResolvedValue({});
    render(
      <CategoryComboCell
        axis="income"
        row={{ id: "tpl-C" }}
        value=""
        onPatched={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("recurring-cat-income-tpl-C-display"));
    const input = await screen.findByTestId("recurring-cat-income-tpl-C-input");
    fireEvent.change(input, { target: { value: "Warranty Work" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/income-categories/resolve-or-create",
      { name: "Warranty Work" },
    ));
  });
});
