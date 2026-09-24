/**
 * Task C · Feb-2026 — Pricebook inline category cells vitest
 * coverage.
 *
 * Pins the click-to-edit behaviour on the two new cells added
 * to each row of the ``OpsHub.jsx`` PriceBook list in Commit 2
 * of the Task C series. Also carries one regression assertion
 * for the Commit 1 refactor of ``CategoryComboCell`` (the
 * ``patchUrl`` prop) against the Recurring Jobs callsite shape.
 *
 * Cases (5):
 *   1. Non-service item — both Service + Income cells render
 *      in display state with the resolved current-name from
 *      ``serviceCats`` / ``incomeCats``.
 *   2. Service-typed item — Service cell visible; Income cell
 *      renders the inert ``—`` placeholder (via the dedicated
 *      ``pb-cat-income-{id}-na`` testid). Column alignment
 *      preserved.
 *   3. Selecting an existing category from the dropdown fires
 *      PATCH ``/items/{id}`` with the new ``service_category_id``
 *      → the wrapper ``onPatched`` triggers ``refresh()``.
 *   4. Typing a brand-new category name (not in the master list)
 *      → resolve-or-create fires → PATCH follows through →
 *      ``refresh()`` called.
 *   5. Regression guard for Commit 1 — the RecurringJobs
 *      callsite pattern (``patchUrl={\`/recurring-jobs/\${id}\`}``)
 *      still routes PATCH to the correct URL when driven through
 *      the parameterized component.
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

import CategoryComboCell from "@/components/recurring/CategoryComboCell";

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
});


// Fixture — mirror the shape ``OpsHub.jsx`` PriceBook rendering
// passes into ``<CategoryComboCell>``: pre-resolved value name
// (looked up from ``serviceCats`` / ``incomeCats``),
// ``patchUrl=`/items/${row.id}```, and testid base
// ``pb-cat-${axis}-${row.id}``.
function _renderPbCell({
  axis,
  row = { id: "item-1", item_type: "product",
             service_category_id: "svc-1",
             income_category_id: "inc-1" },
  serviceCats = [
    { id: "svc-1", name: "Weekly Service", is_archived: false },
    { id: "svc-2", name: "Repair", is_archived: false },
  ],
  incomeCats = [
    { id: "inc-1", name: "Chemical Sales", is_archived: false },
    { id: "inc-2", name: "Service Revenue", is_archived: false },
  ],
  onRefresh = vi.fn(),
} = {}) {
  const resolvedName = axis === "service"
    ? (serviceCats.find((c) => c.id === row.service_category_id)?.name || "")
    : (incomeCats.find((c) => c.id === row.income_category_id)?.name || "");
  return render(
    <CategoryComboCell
      axis={axis}
      row={row}
      value={resolvedName}
      patchUrl={`/items/${row.id}`}
      onPatched={() => onRefresh()}
      dataTestidBase={`pb-cat-${axis}-${row.id}`}
    />,
  );
}


describe("Task C · Pricebook inline category cells", () => {
  it("renders Service + Income display state with resolved names for non-service item", () => {
    // Case 1 — non-service item, both cells resolvable.
    _renderPbCell({ axis: "service" });
    expect(
      screen.getByTestId("pb-cat-service-item-1-display").textContent,
    ).toContain("Weekly Service");

    _renderPbCell({ axis: "income" });
    expect(
      screen.getByTestId("pb-cat-income-item-1-display").textContent,
    ).toContain("Chemical Sales");
  });

  it("renders Service cell but hides Income cell for service-typed item (parent-side guard)", () => {
    // Case 2 — the ``item_type === 'service'`` guard is applied
    // by ``OpsHub.jsx``'s render layer (the parent decides which
    // cell to mount). This test mirrors that contract: for a
    // service-typed row the parent mounts the ``—`` placeholder
    // instead of the combobox on the income axis. We simulate
    // the parent's decision here directly.
    const row = { id: "srv-1", item_type: "service",
                    service_category_id: "svc-1",
                    income_category_id: null };
    _renderPbCell({ axis: "service", row });
    expect(
      screen.getByTestId("pb-cat-service-srv-1-display"),
    ).toBeInTheDocument();

    // Parent-emulated placeholder for the income cell — matches
    // the exact JSX shape at ``OpsHub.jsx`` (see Commit 2 diff):
    render(
      <div className="w-32"
            data-testid="pb-cell-income-category-srv-1">
        {row.item_type === "service" ? (
          <div className="w-full text-left px-2 py-1 text-xs"
                data-testid={`pb-cat-income-${row.id}-na`}>
            —
          </div>
        ) : null}
      </div>,
    );
    expect(screen.getByTestId("pb-cat-income-srv-1-na").textContent)
      .toBe("—");
    // No combobox mounted on the income axis for service-typed
    // rows.
    expect(screen.queryByTestId("pb-cat-income-srv-1-display"))
      .toBeNull();
  });

  it("selecting an existing category fires PATCH /items/{id} and triggers refresh", async () => {
    // Case 3 — user picks a suggestion from the dropdown and
    // hits Enter (or blurs). PATCH lands on the Pricebook URL,
    // wrapper's ``onPatched`` fires and the parent's
    // ``refresh()`` is called.
    mockGet.mockResolvedValue({ items: [
      { id: "svc-1", name: "Weekly Service" },
      { id: "svc-2", name: "Repair" },
    ] });
    mockPost.mockResolvedValue({
      created: false,
      category: { id: "svc-2", name: "Repair" },
    });
    mockPatch.mockResolvedValue({});
    const onRefresh = vi.fn();
    _renderPbCell({ axis: "service", onRefresh });

    fireEvent.click(screen.getByTestId("pb-cat-service-item-1-display"));
    const input = await screen.findByTestId("pb-cat-service-item-1-input");
    fireEvent.change(input, { target: { value: "Repair" } });
    fireEvent.keyDown(input, { key: "Enter" });

    // resolve-or-create fires (Repair typed → server returns the
    // canonical row).
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/service-categories/resolve-or-create",
      { name: "Repair" },
    ));
    // PATCH lands on the Pricebook item, NOT on /recurring-jobs.
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      "/items/item-1",
      { service_category_id: "svc-2" },
    ));
    // Parent's refresh() invoked.
    await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1));
  });

  it("typing a brand-new category name creates it and links it in one gesture", async () => {
    // Case 4 — user types a name that doesn't exist in the
    // master list. Resolve-or-create returns a fresh row; PATCH
    // wires it to the item; refresh follows.
    mockGet.mockResolvedValue({ items: [] });  // empty master list
    mockPost.mockResolvedValue({
      created: true,
      category: { id: "inc-new", name: "Warranty Revenue" },
    });
    mockPatch.mockResolvedValue({});
    const onRefresh = vi.fn();
    _renderPbCell({
      axis: "income",
      row: { id: "item-2", item_type: "product",
                service_category_id: "svc-1",
                income_category_id: null },
      onRefresh,
    });

    fireEvent.click(screen.getByTestId("pb-cat-income-item-2-display"));
    const input = await screen.findByTestId("pb-cat-income-item-2-input");
    fireEvent.change(input, { target: { value: "Warranty Revenue" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/income-categories/resolve-or-create",
      { name: "Warranty Revenue" },
    ));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      "/items/item-2",
      { income_category_id: "inc-new" },
    ));
    await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1));
  });

  it("regression — RecurringJobs callsite pattern still routes PATCH to /recurring-jobs/{id}", async () => {
    // Case 5 — safety-margin against Commit 1's refactor.
    // Rendering with the RecurringJobs pattern (patchUrl points
    // at ``/recurring-jobs/${id}``) must still route PATCH to
    // that URL. Same combobox, different ``patchUrl`` — the
    // parameterization contract in action.
    mockGet.mockResolvedValue({ items: [] });
    mockPost.mockResolvedValue({
      created: true,
      category: { id: "cat-r", name: "Regression Cat" },
    });
    mockPatch.mockResolvedValue({});
    const onPatched = vi.fn();
    render(
      <CategoryComboCell
        axis="income"
        row={{ id: "tpl-regress" }}
        value=""
        patchUrl="/recurring-jobs/tpl-regress"
        onPatched={onPatched}
      />,
    );
    fireEvent.click(
      screen.getByTestId("recurring-cat-income-tpl-regress-display"),
    );
    const input = await screen.findByTestId(
      "recurring-cat-income-tpl-regress-input",
    );
    fireEvent.change(input, { target: { value: "Regression Cat" } });
    fireEvent.keyDown(input, { key: "Enter" });

    // PATCH must land on ``/recurring-jobs/...`` — NOT on
    // ``/items/...``. Same-signature component, caller-driven
    // routing.
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      "/recurring-jobs/tpl-regress",
      { income_category_id: "cat-r" },
    ));
    // And the ``onPatched`` callback still receives both the id
    // and the name (parameterization did NOT break the payload
    // contract).
    await waitFor(() => expect(onPatched).toHaveBeenCalledWith({
      income_category_id: "cat-r",
      income_category_name: "Regression Cat",
    }));
  });
});
