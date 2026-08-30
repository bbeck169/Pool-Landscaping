/**
 * Invoice category picker — inline "+ Add category" · Feb-2026
 *
 * Feb-2026 · Invoice inline edit sprint · Part B — verifies:
 *   * The dropdown renders the active categories fetched from
 *     ``/income-categories``.
 *   * The "+ Add category" option is present at the bottom.
 *   * Selecting "+ Add category" opens the inline create-modal;
 *     submitting it POSTs to ``/income-categories/resolve-or-create``
 *     and auto-selects the newly-created row.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

const postSpy = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (url) => {
      if (url === "/income-categories") {
        return { items: [{ id: "cat-pool", name: "Pool", color: "#0EA5E9" }] };
      }
      return {};
    }),
    post: (...args) => postSpy(...args),
  },
}));

import CategoryPicker, { invalidateCategoryCache }
  from "@/components/income/CategoryPicker";

async function tick() {
  await act(async () => { for (let i = 0; i < 4; i += 1) await Promise.resolve(); });
}

beforeEach(() => {
  invalidateCategoryCache();
  postSpy.mockReset();
});

describe("CategoryPicker · inline + Add category", () => {
  it("renders active categories + the + Add category footer", async () => {
    const onChange = vi.fn();
    render(<CategoryPicker value="" onChange={onChange}
                            testid="pk" required />);
    await tick();
    fireEvent.click(screen.getByTestId("pk-button"));
    await tick();
    expect(screen.getByTestId("pk-option-cat-pool")).toBeInTheDocument();
    expect(screen.getByTestId("pk-add-new")).toBeInTheDocument();
  });

  it("creates a new category on submit and auto-selects it", async () => {
    postSpy.mockResolvedValueOnce({
      category: { id: "cat-new", name: "Repairs", color: "#DC2626" },
    });
    const onChange = vi.fn();
    render(<CategoryPicker value="" onChange={onChange}
                            testid="pk" required />);
    await tick();
    fireEvent.click(screen.getByTestId("pk-button"));
    await tick();
    fireEvent.click(screen.getByTestId("pk-add-new"));
    await tick();
    const nameInput = screen.getByTestId("pk-new-name");
    fireEvent.change(nameInput, { target: { value: "Repairs" } });
    fireEvent.click(screen.getByTestId("pk-new-submit"));
    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    // Called with the right endpoint + body.
    expect(postSpy.mock.calls[0][0])
      .toBe("/income-categories/resolve-or-create");
    expect(postSpy.mock.calls[0][1]).toEqual({ name: "Repairs" });
    // onChange fired with the created id.
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("cat-new"));
  });

  it("renders the archived warning + red border when invalidReason=archived_category", async () => {
    const onChange = vi.fn();
    render(<CategoryPicker value="Common" onChange={onChange}
                            required testid="pk"
                            invalidReason="archived_category" />);
    await tick();
    expect(screen.getByTestId("pk-archived-warning")).toBeInTheDocument();
    // The button's border color is red when the invalidReason fires.
    const btn = screen.getByTestId("pk-button");
    expect(btn.getAttribute("data-invalid-reason")).toBe("archived_category");
  });
});
