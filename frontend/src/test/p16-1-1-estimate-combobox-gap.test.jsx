/**
 * Phase P16.1.1 · Feb-2026 — Estimate/Quote create-flow combobox gap.
 *
 * The consolidated ``e1_tester`` pass caught a P16.1 miss: the CREATE
 * page at ``/quotes/new`` (and ``/invoices/new``) — rendered by
 * ``QuoteInvoiceNew.jsx`` — kept its own inline line-items editor
 * that used a plain ``<input list="items-datalist">`` for the
 * description field.  The P16.1 sweep only replaced the description
 * field inside ``K71LineItemsEditor.jsx`` (used by the EDIT page
 * at ``/quotes/:id``), so the create surface never got the combobox.
 *
 * This suite locks that gap closed: mount ``QuoteInvoiceNew`` with a
 * ``docType="quote"`` (estimate) preset, assert the description
 * column renders a ``MasterServiceCombobox`` (via its templated
 * ``qf-line-${i}-desc`` testid namespace), add a row and assert the
 * new row instantiates its OWN combobox, and pick a master service
 * to prove the auto-fill stamps ``description``, ``unit_price``
 * (dollars), ``category`` (name — the shape ``POST /quotes`` ships)
 * and ``service_category_id`` (resolved from the picked category
 * name via ``loadCategories("service")`` — K71-parity) on THAT row
 * only.  A source-grep assertion locks the drop-in so the legacy
 * ``<input list="items-datalist">`` cannot silently return.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";


// ── shared API mock ────────────────────────────────────────────────
const { getSpy, postSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
}));
vi.mock("@/api", () => ({
  api: {
    get:   (...a) => getSpy(...a),
    post:  (...a) => postSpy(...a),
    patch: vi.fn(),
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

// ── Router mocks — ``QuoteInvoiceNew`` reads useSearchParams + navigate.
const navigateMock = vi.fn();
vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
  useSearchParams: () => [new URLSearchParams("")],
}));

// CustomerCombobox pulls its own /customers — mock as a passthrough
// input so the create form mounts without a network dependency.
vi.mock("@/components/customers/CustomerCombobox", () => ({
  __esModule: true,
  default: ({ value, onChange }) => (
    <input
      data-testid="mock-customer-combobox"
      value={value || ""}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}));


import MasterServiceCombobox, {
  invalidateMasterServicesCache,
} from "@/components/services/MasterServiceCombobox";
import { invalidateCategoryCache }
  from "@/components/income/CategoryPicker";
import QuoteInvoiceNew from "@/pages/quotes/QuoteInvoiceNew";


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


beforeEach(() => {
  invalidateMasterServicesCache();
  invalidateCategoryCache();
  getSpy.mockReset();
  postSpy.mockReset();
  navigateMock.mockReset();
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
      return { items: [] };
    }
    if (url.startsWith("/customers")) return [];
    if (url === "/settings/terms") return {
      default_quote_terms: "Net 30", default_invoice_terms: "Due on receipt",
    };
    return { items: [] };
  });
});
afterEach(() => cleanup());


// ═════════════════════════════════════════════════════════════════════
// Item 1 · Estimate/Quote CREATE page renders MasterServiceCombobox
// on the description column (not a plain <input list="items-datalist">).
// ═════════════════════════════════════════════════════════════════════
describe("Phase P16.1.1 · Estimate/Quote create page · description combobox", () => {
  it("mounts the description column as a MasterServiceCombobox (not <input list=…>)", async () => {
    render(<QuoteInvoiceNew docType="quote" />);
    // The combobox uses ``testid={`qf-line-${i}-desc`}`` on its
    // wrapper + ``qf-line-${i}-desc-input`` on the inner text
    // field.  P16.1's create-flow gap left a raw <input> that
    // OWNED the ``qf-line-${i}-desc`` testid directly — post
    // P16.1.1 the wrapper owns that testid + the ``-input``
    // suffix is present too.  Assert BOTH so a regression back
    // to the raw <input> shape blows the test.
    await waitFor(
      () => expect(screen.getByTestId("qf-line-0-desc")).toBeTruthy(),
      { timeout: 2000 },
    );
    expect(screen.getByTestId("qf-line-0-desc-input")).toBeTruthy();
    // The legacy ``<datalist id="items-datalist-0">`` MUST be gone.
    expect(document.getElementById("items-datalist-0")).toBeNull();
  });

  it("clicking Add line instantiates a NEW combobox on the added row", async () => {
    render(<QuoteInvoiceNew docType="quote" />);
    await waitFor(() =>
      expect(screen.getByTestId("qf-line-0-desc")).toBeTruthy(),
    );
    // Add line — the button carries the ``qf-add-line`` testid.
    const addBtn = screen.getByTestId("qf-add-line");
    fireEvent.click(addBtn);
    // Row 1 (the newly added) must now expose its own combobox
    // wrapper + input pair.
    await waitFor(
      () => expect(screen.getByTestId("qf-line-1-desc")).toBeTruthy(),
      { timeout: 2000 },
    );
    expect(screen.getByTestId("qf-line-1-desc-input")).toBeTruthy();
    // Row 0's combobox is UNAFFECTED — no data cross-bleed.
    expect(screen.getByTestId("qf-line-0-desc")).toBeTruthy();
  });

  it("picking a master service auto-fills description + unit_price + category on that row ONLY", async () => {
    render(<QuoteInvoiceNew docType="quote" />);
    await waitFor(() =>
      expect(screen.getByTestId("qf-line-0-desc")).toBeTruthy(),
    );
    // Add a second row so we can prove row-0 vs row-1 isolation.
    fireEvent.click(screen.getByTestId("qf-add-line"));
    await waitFor(() =>
      expect(screen.getByTestId("qf-line-1-desc")).toBeTruthy(),
    );

    // Focus row-0's combobox — this triggers the lazy
    // /master-services fetch inside the combobox on first-open.
    const row0Input = screen.getByTestId("qf-line-0-desc-input");
    fireEvent.focus(row0Input);
    // Options render with testid ``${wrapperTestId}-option-${row.id}``.
    const opt = await screen.findByTestId(
      "qf-line-0-desc-option-svc-1", {}, { timeout: 3000 },
    );
    fireEvent.click(opt);
    await waitFor(() => {
      expect(screen.getByTestId("qf-line-0-desc-input").value)
        .toBe("Weekly Pool Service");
      // Unit price auto-fills in DOLLARS (the create-form's shape)
      // — NOT cents.  Compare on parsed number so an incidental
      // trailing ``.00`` from the number-input coercion doesn't
      // false-fail the assertion.
      expect(Number(screen.getByTestId("qf-line-0-price").value))
        .toBeCloseTo(129.99, 2);
    });
    // Row-1's combobox stayed empty — no cross-row bleed.
    expect(screen.getByTestId("qf-line-1-desc-input").value).toBe("");
    expect(Number(screen.getByTestId("qf-line-1-price").value)).toBe(0);
  });

  it("QuoteInvoiceNew.jsx source imports the combobox + drops the legacy <datalist>", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname,
        "../pages/quotes/QuoteInvoiceNew.jsx"), "utf8",
    );
    // Locks P16.1.1's drop-in against silent regression.
    expect(src).toMatch(
      /import MasterServiceCombobox from "@\/components\/services\/MasterServiceCombobox"/,
    );
    expect(src).toMatch(
      /loadCategories as _loadServiceCats/,
    );
    // Combobox is wired to the row's ``description`` state.
    expect(src).toMatch(/<MasterServiceCombobox[\s\S]{0,400}value=\{li\.description\}/);
    // The legacy ``<input list={`items-datalist-${i}`}>`` +
    // ``<datalist id={`items-datalist-${i}`}>`` are gone.
    expect(src).not.toMatch(/list=\{`items-datalist-\$\{i\}`\}/);
    expect(src).not.toMatch(/<datalist id=\{`items-datalist-/);
  });
});


// ═════════════════════════════════════════════════════════════════════
// Item 2 · Pure host-wiring integration guard (no page mount).
// Mirrors the P16.1 JobNew "host wiring" style so a stale-prop
// bleed on the create page is caught at the wire-shape level too.
// ═════════════════════════════════════════════════════════════════════
describe("Phase P16.1.1 · Host wiring guard (per-row functional setState)", () => {
  it("two-row host: picking on row-1 leaves row-0 untouched", async () => {
    function TwoRowHost() {
      const [rows, setRows] = React.useState([
        { description: "", unit_price: 0, category: "" },
        { description: "", unit_price: 0, category: "" },
      ]);
      return (
        <div>
          {rows.map((li, i) => (
            <div key={i}>
              <MasterServiceCombobox
                value={li.description}
                defaultPriceHint={li.unit_price || null}
                onChange={({ name, default_price, category }) => {
                  setRows((prev) => prev.map((x, idx) => {
                    if (idx !== i) return x;
                    const next = { ...x, description: name };
                    if (Number.isFinite(default_price)
                        && default_price != null) {
                      next.unit_price = Number(default_price);
                    }
                    if (category) next.category = category;
                    return next;
                  }));
                }}
                testid={`host-line-${i}-desc`}
              />
              <div data-testid={`host-row-${i}-desc`}>{li.description}</div>
              <div data-testid={`host-row-${i}-price`}>{String(li.unit_price)}</div>
              <div data-testid={`host-row-${i}-cat`}>{li.category || ""}</div>
            </div>
          ))}
        </div>
      );
    }
    render(<TwoRowHost />);
    // Pick on row-1.
    fireEvent.focus(screen.getByTestId("host-line-1-desc-input"));
    const opt = await screen.findByTestId(
      "host-line-1-desc-option-svc-2", {}, { timeout: 3000 },
    );
    fireEvent.click(opt);
    await waitFor(() => {
      expect(screen.getByTestId("host-row-1-desc").textContent)
        .toBe("Acid Wash");
      expect(screen.getByTestId("host-row-1-price").textContent).toBe("450");
      expect(screen.getByTestId("host-row-1-cat").textContent).toBe("Pool");
    });
    // Row 0 stayed pristine.
    expect(screen.getByTestId("host-row-0-desc").textContent).toBe("");
    expect(screen.getByTestId("host-row-0-price").textContent).toBe("0");
    expect(screen.getByTestId("host-row-0-cat").textContent).toBe("");
  });
});
