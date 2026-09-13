/**
 * Backlog #iii · Feb-2026 — Edit Item modal + inline row column-3
 * pencil deep-link. Covers R1-R5 refinements.
 *
 * Vitest suite — mount the modal in isolation with mocked API + auth.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, act, cleanup, within,
} from "@testing-library/react";

// ─── Shared mocks ───────────────────────────────────────────────
const { getMock, postMock, patchMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
  patchMock: vi.fn(),
}));
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    patch: (...a) => patchMock(...a),
    put: vi.fn(),
    del: vi.fn(),
  },
  TOKEN_KEY: "token",
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {}, {
    success: vi.fn(), error: vi.fn(), info: vi.fn(),
  }),
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin", email: "a@x" } }),
  AuthProvider: ({ children }) => children,
}));

// jsdom has no ResizeObserver + no pointer events — Radix Popover
// touches both.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
}
if (typeof window !== "undefined" && !window.HTMLElement.prototype.hasPointerCapture) {
  window.HTMLElement.prototype.hasPointerCapture = () => false;
  window.HTMLElement.prototype.scrollIntoView = () => {};
}

// Radix Popover portalizes its content behind an animated open state
// that jsdom can't drive reliably. Mock it to render inline so
// findByTestId sees the dropdown items immediately when the trigger
// is clicked.
vi.mock("@/components/ui/popover", async () => {
  const React = await import("react");
  const Ctx = React.createContext({ open: false, setOpen: () => {} });
  return {
    Popover: ({ children, open, onOpenChange }) => {
      const [_open, _setOpen] = React.useState(!!open);
      const setter = onOpenChange || _setOpen;
      const val = open != null ? open : _open;
      return (
        <Ctx.Provider value={{ open: val, setOpen: setter }}>
          {children}
        </Ctx.Provider>
      );
    },
    PopoverTrigger: ({ children }) => {
      const ctx = React.useContext(Ctx);
      const child = React.Children.only(children);
      return React.cloneElement(child, {
        onFocus: () => ctx.setOpen(true),
        onClick: () => ctx.setOpen(true),
      });
    },
    PopoverContent: ({ children }) => {
      const ctx = React.useContext(Ctx);
      return ctx.open ? <div>{children}</div> : null;
    },
    PopoverAnchor: ({ children }) => children,
  };
});

import EditItemModal from "@/components/pricebook/EditItemModal";


const _sampleItem = {
  id: "item-1",
  name: "Chlorine Tablets 25lb",
  category: "Chemical",
  unit: "25 lb",
  unit_price: 149.99,
  tax_rate: 8.6,
  labor_cost_default: 0,
  item_type: "product",
  service_category_id: "sc-chem",
  income_category_id: null,
  suppliers: [
    { id: "s1", supplier_name: "Pool360", supplier_sku: "P1", unit_cost: 45.5, unit_size: "25 lb", notes: "" },
    { id: "s2", supplier_name: "SiteOne", supplier_sku: "S1", unit_cost: 39.99, unit_size: "25 lb", notes: "" },
  ],
};

function _seed() {
  getMock.mockImplementation(async (path) => {
    if (path === "/income-categories") return { items: [
      { id: "ic-pool",   name: "Pool",       is_archived: false },
      { id: "ic-chem",   name: "Chemicals",  is_archived: false },
    ]};
    if (path === "/service-categories") return { items: [
      { id: "sc-pool",   name: "Pool",       is_archived: false },
      { id: "sc-chem",   name: "Chemicals",  is_archived: false },
    ]};
    if (path === "/pricebook/supplier-names") return {
      names: ["Ewing", "ePoolSupply", "Heritage", "Pool360", "SiteOne"],
      total: 5,
    };
    return [];
  });
  postMock.mockReset();
  patchMock.mockReset();
}


beforeEach(() => { _seed(); });
afterEach(() => { cleanup(); getMock.mockReset(); postMock.mockReset(); patchMock.mockReset(); });


describe("Backlog #iii · EditItemModal · General / tabs render", () => {
  it("renders 4 tabs and defaults to General", async () => {
    await act(async () => {
      render(<EditItemModal open item={_sampleItem}
                              onOpenChange={() => {}} onSaved={() => {}} />);
    });
    await screen.findByTestId("edit-item-modal");
    ["tab-general", "tab-pricing", "tab-suppliers", "tab-categories"].forEach((t) => {
      expect(screen.getByTestId(t)).toBeInTheDocument();
    });
    // General panel visible.
    expect(screen.getByTestId("tab-general-panel")).toBeInTheDocument();
    expect(screen.getByTestId("ei-name")).toHaveValue(_sampleItem.name);
  });

  it("deep-links to Suppliers tab when opened via the pencil (initialTab='suppliers')", async () => {
    await act(async () => {
      render(<EditItemModal open item={_sampleItem} initialTab="suppliers"
                              onOpenChange={() => {}} onSaved={() => {}} />);
    });
    // Suppliers panel visible because initialTab drove tab state.
    expect(screen.getByTestId("tab-suppliers-panel")).toBeInTheDocument();
  });
});


describe("Backlog #iii · Pricing tab · effective_cost read-out", () => {
  it("displays effective cost = min(supplier unit_costs) in the Pricing tab", async () => {
    await act(async () => {
      render(<EditItemModal open item={_sampleItem} initialTab="pricing"
                              onOpenChange={() => {}} onSaved={() => {}} />);
    });
    const ec = await screen.findByTestId("ei-effective-cost");
    // Both suppliers set — min is 39.99.
    expect(ec.textContent).toMatch(/\$39\.99/);
    expect(ec.textContent).toMatch(/min of 2 suppliers/i);
  });

  it("shows '—' when no supplier has a unit_cost set", async () => {
    const emptyItem = { ..._sampleItem, suppliers: [] };
    await act(async () => {
      render(<EditItemModal open item={emptyItem} initialTab="pricing"
                              onOpenChange={() => {}} onSaved={() => {}} />);
    });
    const ec = await screen.findByTestId("ei-effective-cost");
    expect(ec.textContent).toContain("—");
  });
});


describe("Backlog #iii · Suppliers tab · add / remove / edit + chemical guardrail", () => {
  it("renders existing supplier rows + Add / Remove buttons work", async () => {
    await act(async () => {
      render(<EditItemModal open item={_sampleItem} initialTab="suppliers"
                              onOpenChange={() => {}} onSaved={() => {}} />);
    });
    expect(screen.getByTestId("ei-supplier-row-0")).toBeInTheDocument();
    expect(screen.getByTestId("ei-supplier-row-1")).toBeInTheDocument();
    // Add a new blank row.
    await act(async () => {
      fireEvent.click(screen.getByTestId("ei-supplier-add"));
    });
    expect(screen.getByTestId("ei-supplier-row-2")).toBeInTheDocument();
    // Remove the middle row.
    await act(async () => {
      fireEvent.click(screen.getByTestId("ei-supplier-remove-1"));
    });
    // Only 2 rows left after removing index 1.
    expect(screen.queryByTestId("ei-supplier-row-2")).not.toBeInTheDocument();
  });

  it("shows the yellow empty-suppliers warning for a chemical with 0 rows", async () => {
    const emptyChem = { ..._sampleItem, suppliers: [], category: "Chemical" };
    await act(async () => {
      render(<EditItemModal open item={emptyChem} initialTab="suppliers"
                              onOpenChange={() => {}} onSaved={() => {}} />);
    });
    expect(screen.getByTestId("ei-suppliers-empty-warning")).toBeInTheDocument();
    expect(screen.getByTestId("ei-suppliers-empty-warning").textContent)
      .toMatch(/no suppliers/i);
  });

  it("does NOT show the empty-suppliers warning for a non-chemical", async () => {
    const emptyPart = { ..._sampleItem, suppliers: [], category: "Part" };
    await act(async () => {
      render(<EditItemModal open item={emptyPart} initialTab="suppliers"
                              onOpenChange={() => {}} onSaved={() => {}} />);
    });
    expect(screen.queryByTestId("ei-suppliers-empty-warning")).not.toBeInTheDocument();
  });

  it("effective-cost footer updates live when a supplier's cost changes", async () => {
    await act(async () => {
      render(<EditItemModal open item={_sampleItem} initialTab="suppliers"
                              onOpenChange={() => {}} onSaved={() => {}} />);
    });
    // Change row 1 (SiteOne) unit_cost from 39.99 → 10.00.
    const inp = screen.getByTestId("ei-supplier-cost-1");
    await act(async () => {
      fireEvent.change(inp, { target: { value: "10.00" } });
    });
    // Footer now shows $10.00.
    const footer = await screen.findByTestId("ei-effective-cost-footer");
    expect(footer.textContent).toMatch(/\$10\.00/);
  });
});


describe("Backlog #iii · Categories tab · autocomplete + resolve-or-create on save", () => {
  it("Save does NOT call resolve-or-create when the item already has a category id (no picker change)", async () => {
    // When the item already carries an income_category_id (from the
    // legacy inline path) and the user opens the modal + hits Save
    // without touching the categories, we must NOT re-resolve —
    // the id round-trips as-is.
    const preset = {
      ..._sampleItem, income_category_id: "ic-pool",
      income_category_name: "Pool",
    };
    patchMock.mockResolvedValue(preset);
    await act(async () => {
      render(<EditItemModal open item={preset} initialTab="general"
                              onOpenChange={() => {}} onSaved={() => {}} />);
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("ei-save"));
    });
    await waitFor(() => expect(patchMock).toHaveBeenCalled());
    const calls = postMock.mock.calls.map((c) => c[0]);
    expect(calls).not.toContain("/income-categories/resolve-or-create");
    expect(calls).not.toContain("/service-categories/resolve-or-create");
    expect(patchMock.mock.calls[0][1].income_category_id).toBe("ic-pool");
  });

  it("Save calls resolve-or-create for a NEW income category name typed on Categories tab", async () => {
    // Drive the flow via userEvent so Radix Popover + Command
    // dispatch focus/keyboard events correctly under jsdom.
    const userEvent = (await import("@testing-library/user-event")).default;
    const user = userEvent.setup();
    patchMock.mockResolvedValue({ ..._sampleItem });
    postMock.mockResolvedValueOnce({
      created: true,
      category: { id: "ic-brand-new", name: "Brand New Cat" },
    });
    await act(async () => {
      render(<EditItemModal open item={_sampleItem} initialTab="categories"
                              onOpenChange={() => {}} onSaved={() => {}} />);
    });
    // Feb-2026 · Housekeeping Batch A — the memo's original mock-
    // shape hypotheses were both wrong. The real root cause is a
    // testid-drift: the test called ``ei-income-cat-*`` but the
    // production ``CategoryAutocomplete`` component renders testids
    // scoped to its ``testidPrefix`` prop, which is
    // ``pricebook-income-category-select`` for the income-category
    // slot. Renaming to match — no production-side change.
    await screen.findByTestId("pricebook-income-category-select-input");
    const inp = screen.getByTestId("pricebook-income-category-select-input");
    await user.click(inp);
    await user.type(inp, "Brand New Cat");
    // Radix Popover portal renders the CommandItem outside the modal —
    // findByTestId still resolves it once mounted.
    const createBtn = await screen.findByTestId(
      "pricebook-income-category-select-create", {}, { timeout: 3000 },
    );
    await user.click(createBtn);
    await user.click(screen.getByTestId("ei-save"));
    await waitFor(() => {
      const paths = postMock.mock.calls.map((c) => c[0]);
      expect(paths).toContain("/income-categories/resolve-or-create");
    }, { timeout: 3000 });
    await waitFor(() => expect(patchMock).toHaveBeenCalled(), { timeout: 3000 });
    expect(patchMock.mock.calls[0][1].income_category_id).toBe("ic-brand-new");
  });
});


describe("Backlog #iii · Save posts full suppliers[] payload", () => {
  it("PATCH /items/{id} carries the full suppliers[] array cleaned + coerced", async () => {
    patchMock.mockResolvedValue({ ..._sampleItem });
    await act(async () => {
      render(<EditItemModal open item={_sampleItem} initialTab="suppliers"
                              onOpenChange={() => {}} onSaved={() => {}} />);
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("ei-save"));
    });
    await waitFor(() => expect(patchMock).toHaveBeenCalled());
    const [path, body] = patchMock.mock.calls[0];
    expect(path).toBe("/items/item-1");
    expect(Array.isArray(body.suppliers)).toBe(true);
    expect(body.suppliers).toHaveLength(2);
    expect(body.suppliers[0].supplier_name).toBe("Pool360");
    expect(body.suppliers[1].supplier_name).toBe("SiteOne");
    // unit_cost is coerced to a number.
    expect(typeof body.suppliers[0].unit_cost).toBe("number");
  });
});
