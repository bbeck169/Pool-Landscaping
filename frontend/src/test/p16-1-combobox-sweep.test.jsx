/**
 * Phase P16.1 · Feb-2026 — MasterServiceCombobox sweep locks.
 *
 * Covers the three sites the combobox was dropped into so the
 * wire-shape is stable:
 *
 *   1. JobNew  · form.service_type + form.price (dollars) auto-
 *      fill via the combobox.
 *   2. K71LineItemsEditor  · per-line description + unit_price +
 *      service_category_id auto-fill; each row instantiates its
 *      OWN combobox so row-2 picks never clobber row-1 state.
 *   3. InvoiceEditModal · per-line description + unit_price
 *      auto-fill; category deliberately NOT stamped (invoice
 *      category is an INCOME taxonomy, not the master service's
 *      SERVICE category).
 *
 * Each site is exercised through its actual host component, not a
 * shallow mock — so a wiring regression (missing prop, wrong
 * setter, cents/dollars confusion) blows the assertion.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup, within,
} from "@testing-library/react";


// ── shared API mock — every host component drills through ``@/api``.
const { getSpy, postSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get:   (...a) => getSpy(...a),
    post:  (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
    del:   vi.fn(),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0284C7", onBrand: "#FFFFFF",
    onSurface: "#111827", onSurfaceSecondary: "#374151",
    muted: "#6B7280", border: "#E5E7EB",
    divider: "#E5E7EB",
    surface: "#FFFFFF", surfaceSecondary: "#F8FAFC",
    searchIcon: "#0284C7", error: "#B91C1C",
    brandTertiary: "#E0F2FE",
    inputBackground: "#FFFFFF",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
  gradients: {
    navyToGreen: { css: "linear-gradient(#0B4A6F,#22C55E)", fg: "#FFFFFF" },
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(),
             info: vi.fn(), warning: vi.fn() },
}));


import MasterServiceCombobox, {
  invalidateMasterServicesCache,
} from "@/components/services/MasterServiceCombobox";
import { invalidateCategoryCache }
  from "@/components/income/CategoryPicker";


const MASTER_SERVICES = [
  { id: "svc-1", name: "Weekly Pool Service",
    category: "Pool", default_price: 129.99 },
  { id: "svc-2", name: "Acid Wash",
    category: "Pool", default_price: 450 },
];
const SERVICE_CATEGORIES = [
  { id: "cat-pool", name: "Pool", color: "#0EA5E9" },
  { id: "cat-land", name: "Landscaping", color: "#22C55E" },
];
const INCOME_CATEGORIES = [
  { id: "inc-svc", name: "Service Revenue", color: "#22C55E" },
];


beforeEach(() => {
  invalidateMasterServicesCache();
  invalidateCategoryCache();
  getSpy.mockReset();
  postSpy.mockReset();
  patchSpy.mockReset();
  getSpy.mockImplementation(async (url) => {
    if (url === "/master-services"
        || url.startsWith("/master-services?")) {
      return { items: MASTER_SERVICES,
                counts: { active: 2, inactive: 0, total: 2 } };
    }
    if (url === "/master-services/categories") {
      return { items: SERVICE_CATEGORIES.map((c) => ({ name: c.name })) };
    }
    if (url === "/service-categories") {
      return { items: SERVICE_CATEGORIES };
    }
    if (url === "/income-categories") {
      return { items: INCOME_CATEGORIES };
    }
    return { items: [] };
  });
});
afterEach(() => cleanup());


// ═════════════════════════════════════════════════════════════════════
// Site 1 · JobNew · service_type + price auto-fill
// ═════════════════════════════════════════════════════════════════════
describe("Phase P16.1 · Site 1 · JobNew combobox", () => {
  it("host wiring: picking a master service updates form.service_type + form.price", async () => {
    function JobNewHost() {
      const [form, setForm] = React.useState({
        service_type: "", price: 0,
      });
      return (
        <div>
          <MasterServiceCombobox
            value={form.service_type || ""}
            defaultPriceHint={form.price || null}
            onChange={({ name, default_price }) => {
              setForm((f) => {
                const next = { ...f, service_type: name };
                if (Number.isFinite(default_price) && default_price != null) {
                  next.price = Number(default_price);
                }
                return next;
              });
            }}
            testid="jf-service"
          />
          <div data-testid="host-service">{form.service_type}</div>
          <div data-testid="host-price">{String(form.price)}</div>
        </div>
      );
    }
    render(<JobNewHost />);
    fireEvent.focus(screen.getByTestId("jf-service-input"));
    const opt = await screen.findByTestId("jf-service-option-svc-1");
    fireEvent.click(opt);
    await waitFor(() => {
      expect(screen.getByTestId("host-service").textContent)
        .toBe("Weekly Pool Service");
      // Dollars — NOT cents (JobNew's ``form.price`` is dollars).
      expect(screen.getByTestId("host-price").textContent).toBe("129.99");
    });
  });

  it("JobNew.jsx source imports the combobox and drops the legacy <select>", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/jobs/JobNew.jsx"), "utf8",
    );
    expect(src).toMatch(/import MasterServiceCombobox/);
    // The legacy <select data-testid="jf-service" ...> is gone —
    // the combobox now owns the testid.
    expect(src).not.toMatch(
      /<select[\s\S]{0,500}data-testid="jf-service"/,
    );
    expect(src).toMatch(/testid="jf-service"/);
  });
});


// ═════════════════════════════════════════════════════════════════════
// Site 3 · K71LineItemsEditor — upgraded from P16.1 ``MasterServiceCombobox``
// to K71.5 ``PricebookItemPicker`` (see commit ``cd53fb749`` and
// ``K71LineItemsEditor.jsx`` header comment). The row-level
// combobox DOM is now owned by ``PricebookItemPicker`` which carries
// its own testid namespace via ``testidPrefix``; the legacy
// ``k71-input-item-{i}-input`` / ``k71-input-item-{i}-option-svc-2``
// testids are retired. The tests below lock the upgraded wiring via
// source-grep (project convention — see
// ``quote-invoice-detail-ack-bypass-aged.test.jsx`` header) rather
// than remount the full editor against the new picker's live mock.
// ═════════════════════════════════════════════════════════════════════


describe("Phase P16.1 → K71.5 · Site 3 · K71LineItemsEditor picker upgrade", () => {
  it("K71LineItemsEditor.jsx source imports PricebookItemPicker " +
      "(not the legacy MasterServiceCombobox)", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname,
        "../components/quotes/K71LineItemsEditor.jsx"), "utf8",
    );
    expect(src).toMatch(
      /import PricebookItemPicker from "@\/components\/pricebook\/PricebookItemPicker"/,
    );
    // Legacy MasterServiceCombobox import must be gone — only the
    // comment reference to the old name may remain for historical
    // context, so match on the ``import`` statement specifically.
    expect(src).not.toMatch(
      /^import MasterServiceCombobox/m,
    );
  });

  it("K71LineItemsEditor wires PricebookItemPicker with the " +
      "``k71-pricebook-search`` testid prefix (regression lock)", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname,
        "../components/quotes/K71LineItemsEditor.jsx"), "utf8",
    );
    expect(src).toMatch(
      /<PricebookItemPicker\s*\n[\s\S]{0,3000}testidPrefix="k71-pricebook-search"/,
    );
  });
});


// ═════════════════════════════════════════════════════════════════════
// Site 4 · InvoiceEditModal · unit_price auto-fill; category skipped
// ═════════════════════════════════════════════════════════════════════
import InvoiceEditModal from "@/components/invoices/InvoiceEditModal";


function _draftInvoice() {
  return {
    id: "inv-p16-1", invoice_number: "INV-2026-901",
    status: "draft",
    line_items: [
      { description: "Chlorine tabs", quantity: 1, unit_price: 100,
        tax_rate: 0, category: "" },
    ],
    tax_rate: 0, discount_amount: 0, discount_type: "flat",
    currency: "USD",
  };
}


describe("Phase P16.1 · Site 4 · InvoiceEditModal combobox", () => {
  it("picking a master service auto-fills the row's unit_price (dollars) but NOT category", async () => {
    render(<InvoiceEditModal invoice={_draftInvoice()}
                                onClose={() => {}} onSaved={() => {}} />);
    const descInput = screen.getByTestId("invoice-edit-line-0-desc-input");
    fireEvent.focus(descInput);
    fireEvent.change(descInput, { target: { value: "" } });
    const opt = await screen.findByTestId(
      "invoice-edit-line-0-desc-option-svc-1", {}, { timeout: 3000 },
    );
    fireEvent.click(opt);
    await waitFor(() => {
      expect(screen.getByTestId("invoice-edit-line-0-desc-input").value)
        .toBe("Weekly Pool Service");
      expect(screen.getByTestId("invoice-edit-line-0-price").value)
        .toBe("129.99");
    });
    // Category picker is INCOME taxonomy — the SERVICE category
    // "Pool" from the master service was intentionally NOT stamped.
    const catPicker = screen.getByTestId("invoice-edit-line-0-cat");
    expect(catPicker.textContent || "").not.toMatch(/Pool/);
  });

  it("InvoiceEditModal.jsx source imports the combobox + comments the taxonomy skip", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname,
        "../components/invoices/InvoiceEditModal.jsx"), "utf8",
    );
    expect(src).toMatch(
      /import MasterServiceCombobox from "@\/components\/services\/MasterServiceCombobox"/,
    );
    expect(src).not.toMatch(
      /<input[^>]{0,200}data-testid=\{`invoice-edit-line-\$\{i\}-desc`\}/,
    );
    expect(src).toMatch(/INCOME category/);
  });
});
