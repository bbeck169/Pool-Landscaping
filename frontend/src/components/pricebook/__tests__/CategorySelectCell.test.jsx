/**
 * Pricebook Category UX fixes · Feb-2026 — Task A/B.
 *
 * Vitest coverage for the new native-select inline category cell
 * used on each Pricebook list row.
 *
 * Cases:
 *   1. Dropdown renders every category passed in via ``options``
 *      (no 12-row truncation). Options are alphabetised.
 *   2. Changing the <select> triggers ONE PATCH /items/{id} with
 *      the new ``service_category_id`` and calls ``onSaved``.
 *   3. On PATCH failure the <select> reverts to the previous
 *      value and a sonner error toast fires.
 *   4. Income axis renders a "— None —" option that PATCHes
 *      ``income_category_id: null`` when picked.
 *   5. Service axis renders a disabled "— Select category —"
 *      placeholder (no "— None —" — service is required
 *      server-side).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockPatch = vi.fn();
const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();

vi.mock("@/api", () => ({
  api: { patch: (...a) => mockPatch(...a) },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {},
    { success: (...a) => mockToastSuccess(...a),
       error: (...a) => mockToastError(...a) }),
}));

import CategorySelectCell from "@/components/pricebook/CategorySelectCell";

beforeEach(() => {
  mockPatch.mockReset();
  mockToastSuccess.mockReset();
  mockToastError.mockReset();
});

const _bigServiceOptions = Array.from({ length: 27 }, (_, i) => ({
  id: `svc-${String(i + 1).padStart(2, "0")}`,
  name: `Service Cat ${String.fromCharCode(65 + (i % 26))}${i}`,
}));

describe("<CategorySelectCell /> — rendering & full list", () => {
  it("renders every option passed via props (no 12-row truncation)", () => {
    render(
      <CategorySelectCell
        axis="service"
        row={{ id: "item-1" }}
        value="svc-05"
        options={_bigServiceOptions}
        patchUrl="/items/item-1"
      />,
    );
    const sel = screen.getByTestId("pb-cat-service-item-1-select");
    // Native option elements are children of the <select>. Count
    // the real category options (filter out the placeholder /
    // none sentinel if present).
    const optionIds = Array.from(sel.querySelectorAll("option"))
      .map((o) => o.getAttribute("value"))
      .filter((v) => v && v.startsWith("svc-"));
    expect(optionIds).toHaveLength(27);
  });

  it("sorts options alphabetically by name (case-insensitive)", () => {
    render(
      <CategorySelectCell
        axis="service"
        row={{ id: "item-s" }}
        value="svc-1"
        options={[
          { id: "svc-1", name: "zebra" },
          { id: "svc-2", name: "Alpha" },
          { id: "svc-3", name: "mango" },
        ]}
        patchUrl="/items/item-s"
      />,
    );
    const sel = screen.getByTestId("pb-cat-service-item-s-select");
    const labels = Array.from(sel.querySelectorAll("option"))
      .filter((o) => o.getAttribute("value"))
      .map((o) => o.textContent.trim());
    expect(labels).toEqual(["Alpha", "mango", "zebra"]);
  });
});

describe("<CategorySelectCell /> — save & rollback", () => {
  it("changing the <select> triggers ONE PATCH + onSaved call", async () => {
    mockPatch.mockResolvedValue({});
    const onSaved = vi.fn();
    render(
      <CategorySelectCell
        axis="service"
        row={{ id: "item-1" }}
        value="svc-01"
        options={_bigServiceOptions}
        patchUrl="/items/item-1"
        onSaved={onSaved}
      />,
    );
    const sel = screen.getByTestId("pb-cat-service-item-1-select");
    fireEvent.change(sel, { target: { value: "svc-10" } });
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    expect(mockPatch).toHaveBeenCalledWith(
      "/items/item-1",
      { service_category_id: "svc-10" },
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({
      service_category_id: "svc-10",
    }));
    expect(mockToastSuccess).toHaveBeenCalledWith("Category updated");
  });

  it("reverts to previous value + fires error toast on PATCH failure", async () => {
    mockPatch.mockRejectedValue(new Error("boom"));
    render(
      <CategorySelectCell
        axis="service"
        row={{ id: "item-x" }}
        value="svc-01"
        options={_bigServiceOptions}
        patchUrl="/items/item-x"
      />,
    );
    const sel = screen.getByTestId("pb-cat-service-item-x-select");
    fireEvent.change(sel, { target: { value: "svc-05" } });
    await waitFor(() => expect(mockToastError).toHaveBeenCalled());
    // Reverted to the original value — not the attempted new one.
    expect(sel.value).toBe("svc-01");
    expect(mockToastError.mock.calls[0][0]).toMatch(/reverted/);
  });
});

describe("<CategorySelectCell /> — axis-specific None option", () => {
  it("income axis exposes a '— None —' option that PATCHes null", async () => {
    mockPatch.mockResolvedValue({});
    const onSaved = vi.fn();
    render(
      <CategorySelectCell
        axis="income"
        row={{ id: "item-i" }}
        value="inc-1"
        options={[
          { id: "inc-1", name: "Chemical Sales" },
          { id: "inc-2", name: "Service Revenue" },
        ]}
        patchUrl="/items/item-i"
        onSaved={onSaved}
      />,
    );
    const sel = screen.getByTestId("pb-cat-income-item-i-select");
    const noneOpt = Array.from(sel.querySelectorAll("option"))
      .find((o) => o.textContent.trim() === "— None —");
    expect(noneOpt).toBeTruthy();
    fireEvent.change(sel, { target: { value: "" } });
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      "/items/item-i",
      { income_category_id: null },
    ));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({
      income_category_id: null,
    }));
  });

  it("service axis exposes a disabled '— Select category —' placeholder only when row has no category — no '— None —' option (service is required)", () => {
    render(
      <CategorySelectCell
        axis="service"
        row={{ id: "item-blank" }}
        value=""
        options={[{ id: "svc-1", name: "Weekly Service" }]}
        patchUrl="/items/item-blank"
      />,
    );
    const sel = screen.getByTestId("pb-cat-service-item-blank-select");
    const placeholder = screen.getByTestId("pb-cat-service-item-blank-display");
    expect(placeholder).toBeInTheDocument();
    expect(placeholder).toBeDisabled();
    const noneOpt = Array.from(sel.querySelectorAll("option"))
      .find((o) => o.textContent.trim() === "— None —");
    expect(noneOpt).toBeUndefined();
  });
});
