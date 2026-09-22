/**
 * Phase P16 · Feb-2026 — MasterServiceCombobox behaviour.
 *
 * Locked-in behaviour:
 *   1. Typing filters the visible options case-insensitively.
 *   2. Picking a row fires ``onChange`` with
 *      ``{ name, default_price, category }``.
 *   3. Free-typing a NEW name shows the inline
 *      ``+ Add "<typed>" to Master Service List?`` row.
 *   4. Clicking that row opens the mini-modal prefilled with the
 *      typed name + the ``defaultPriceHint``.
 *   5. Saving the mini-modal POSTs to ``/master-services`` and
 *      auto-selects the newly-created service (fires ``onChange``
 *      with the new row's shape).
 *   6. Typed value that EXACTLY matches an existing service (case-
 *      insensitive on ``name``) does NOT surface the "+ Add" row.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  cleanup, fireEvent, render, screen, waitFor, within,
} from "@testing-library/react";


const { getSpy, postSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get:  (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0284C7", onBrand: "#FFFFFF", onSurface: "#111827",
    muted: "#6B7280", border: "#E5E7EB",
    surface: "#FFFFFF", surfaceSecondary: "#F8FAFC",
    searchIcon: "#0284C7", error: "#B91C1C",
  },
}));


import MasterServiceCombobox, {
  invalidateMasterServicesCache,
} from "@/components/services/MasterServiceCombobox";


const SERVICES = [
  { id: "svc-1", name: "Pool Cleaning",
    category: "Pool", default_price: 120 },
  { id: "svc-2", name: "Pool Chemistry Check",
    category: "Pool", default_price: 45 },
  { id: "svc-3", name: "Lawn Mowing",
    category: "Landscaping", default_price: 60 },
];


beforeEach(() => {
  // Reset the module-level cache so each test starts clean.
  invalidateMasterServicesCache();
  getSpy.mockReset();
  postSpy.mockReset();
  getSpy.mockImplementation(async (url) => {
    if (url === "/master-services") {
      return { items: SERVICES,
                counts: { active: 3, inactive: 0, total: 3 } };
    }
    if (url === "/master-services/categories") {
      return { items: [{ name: "Pool" }, { name: "Landscaping" }] };
    }
    return {};
  });
});

afterEach(() => { cleanup(); });


function ControlledHost({ initial = "" }) {
  const [name, setName] = React.useState(initial);
  const [price, setPrice] = React.useState(null);
  const [category, setCategory] = React.useState(null);
  return (
    <div>
      <MasterServiceCombobox
        value={name}
        onChange={({ name: n, default_price, category: c }) => {
          setName(n);
          if (default_price !== null && default_price !== undefined) {
            setPrice(default_price);
          }
          if (c) setCategory(c);
        }}
      />
      <div data-testid="host-name">{name}</div>
      <div data-testid="host-price">{price === null ? "" : String(price)}</div>
      <div data-testid="host-category">{category || ""}</div>
    </div>
  );
}


describe("Phase P16 · MasterServiceCombobox · typeahead + pick", () => {
  it("dropdown lists all active services when focused with empty input", async () => {
    render(<ControlledHost />);
    fireEvent.focus(screen.getByTestId("master-service-combobox-input"));
    await screen.findByTestId("master-service-combobox-option-svc-1");
    expect(screen.getByTestId("master-service-combobox-option-svc-2")).toBeTruthy();
    expect(screen.getByTestId("master-service-combobox-option-svc-3")).toBeTruthy();
  });

  it("typing filters options case-insensitively", async () => {
    render(<ControlledHost />);
    const input = screen.getByTestId("master-service-combobox-input");
    fireEvent.focus(input);
    await screen.findByTestId("master-service-combobox-option-svc-1");
    // Type "pool" — should match svc-1 + svc-2, drop svc-3.
    fireEvent.change(input, { target: { value: "pool" } });
    await waitFor(() => {
      expect(screen.getByTestId("master-service-combobox-option-svc-1")).toBeTruthy();
      expect(screen.getByTestId("master-service-combobox-option-svc-2")).toBeTruthy();
      expect(screen.queryByTestId("master-service-combobox-option-svc-3")).toBeNull();
    });
    // Uppercase input matches too.
    fireEvent.change(input, { target: { value: "POOL" } });
    await waitFor(() => {
      expect(screen.getByTestId("master-service-combobox-option-svc-1")).toBeTruthy();
      expect(screen.queryByTestId("master-service-combobox-option-svc-3")).toBeNull();
    });
  });

  it("picking a row fires onChange with { name, default_price, category }", async () => {
    render(<ControlledHost />);
    fireEvent.focus(screen.getByTestId("master-service-combobox-input"));
    const opt = await screen.findByTestId("master-service-combobox-option-svc-2");
    fireEvent.click(opt);
    // Host state now reflects the picked row.
    await waitFor(() => {
      expect(screen.getByTestId("host-name").textContent).toBe("Pool Chemistry Check");
      expect(screen.getByTestId("host-price").textContent).toBe("45");
      expect(screen.getByTestId("host-category").textContent).toBe("Pool");
    });
  });
});


describe("Phase P16 · MasterServiceCombobox · exact match suppresses + Add", () => {
  it("does NOT show the + Add row when the typed value exactly matches an existing service", async () => {
    render(<ControlledHost />);
    const input = screen.getByTestId("master-service-combobox-input");
    fireEvent.focus(input);
    await screen.findByTestId("master-service-combobox-option-svc-1");
    // Type the exact name — the + Add row must not appear.
    fireEvent.change(input, { target: { value: "Pool Cleaning" } });
    await waitFor(() => {
      expect(screen.getByTestId("master-service-combobox-option-svc-1")).toBeTruthy();
      expect(screen.queryByTestId("master-service-combobox-add-prompt")).toBeNull();
    });
    // Same but with mixed case — still an exact match, still no + Add.
    fireEvent.change(input, { target: { value: "pool cleaning" } });
    await waitFor(() => {
      expect(screen.queryByTestId("master-service-combobox-add-prompt")).toBeNull();
    });
  });
});


describe("Phase P16 · MasterServiceCombobox · + Add inline flow", () => {
  it("shows the + Add row when the typed value doesn't match any active service", async () => {
    render(<ControlledHost />);
    const input = screen.getByTestId("master-service-combobox-input");
    fireEvent.focus(input);
    await screen.findByTestId("master-service-combobox-option-svc-1");
    fireEvent.change(input, { target: { value: "Acid Wash" } });
    const addPrompt = await screen.findByTestId("master-service-combobox-add-prompt");
    expect(addPrompt.textContent).toMatch(/Add "Acid Wash"/);
  });

  it("clicking + Add opens the mini-modal prefilled with the typed name", async () => {
    render(<ControlledHost />);
    const input = screen.getByTestId("master-service-combobox-input");
    fireEvent.focus(input);
    await screen.findByTestId("master-service-combobox-option-svc-1");
    fireEvent.change(input, { target: { value: "Acid Wash" } });
    const addPrompt = await screen.findByTestId("master-service-combobox-add-prompt");
    fireEvent.click(addPrompt);
    const modal = await screen.findByTestId("master-service-add-modal");
    expect(within(modal)
      .getByTestId("master-service-add-modal-name").value).toBe("Acid Wash");
    // Categories dropdown seeded from /master-services/categories.
    await waitFor(() => {
      const opts = within(modal)
        .getByTestId("master-service-add-modal-category")
        .querySelectorAll("option");
      // Placeholder + 2 seeded categories.
      expect(opts.length).toBeGreaterThanOrEqual(3);
    });
  });

  it("saving the mini-modal POSTs and auto-selects the new service", async () => {
    postSpy.mockResolvedValue({
      id: "svc-new", name: "Acid Wash",
      category: "Pool", default_price: 350,
    });
    render(<ControlledHost />);
    const input = screen.getByTestId("master-service-combobox-input");
    fireEvent.focus(input);
    await screen.findByTestId("master-service-combobox-option-svc-1");
    fireEvent.change(input, { target: { value: "Acid Wash" } });
    fireEvent.click(await screen.findByTestId("master-service-combobox-add-prompt"));
    await screen.findByTestId("master-service-add-modal");
    // Fill price + category.
    fireEvent.change(screen.getByTestId("master-service-add-modal-price"),
      { target: { value: "350" } });
    fireEvent.change(screen.getByTestId("master-service-add-modal-category"),
      { target: { value: "Pool" } });
    fireEvent.click(screen.getByTestId("master-service-add-modal-save"));
    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    const [url, body] = postSpy.mock.calls[0];
    expect(url).toBe("/master-services");
    expect(body).toEqual({
      name: "Acid Wash", default_price: 350, category: "Pool",
    });
    // Auto-selection: host state updates to the new row.
    await waitFor(() => {
      expect(screen.getByTestId("host-name").textContent).toBe("Acid Wash");
      expect(screen.getByTestId("host-price").textContent).toBe("350");
      expect(screen.getByTestId("host-category").textContent).toBe("Pool");
    });
  });
});
