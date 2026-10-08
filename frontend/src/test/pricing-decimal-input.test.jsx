/**
 * PRICING-DECIMAL-INPUT-PARITY · Feb-2026 — close out the three
 * pricing-field surfaces the chemistry sweep deliberately scoped
 * out (follow-up ticket noted in commit ``0f5e7886f``).
 *
 * All three previously rendered as HTML5 number inputs which (per
 * spec) make Chrome / Firefox / iOS Safari return
 * ``e.target.value === ""`` for intermediate decimal states like
 * ``"1."`` or ``".5"`` — users were effectively locked out of
 * typing anything other than whole-dollar / whole-cent amounts.
 *
 * Fix mirrors the shared pattern from ``ChemistryConfiguration
 * Settings`` + ``CustomerChemistry`` (``type="text"`` +
 * ``inputMode="decimal"`` + keystroke regex guard, LIVE string
 * state).  Not using the shared ``<DecimalInput>`` because every
 * callsite reads the field LIVE (immediate save-button click, or
 * a live ``centsToDollars`` preview) — the component's blur-only
 * commit semantics would race the save handler + strand the
 * preview on the pre-keystroke value.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

/* Shared mocks — api / sonner / auth are hit by all three parents. */
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (p) => {
      if (p && p.startsWith("/customers/")) {
        return { id: "cx1", name: "Test Customer" };
      }
      if (p === "/chemicals/catalog") return [];
      if (p === "/admin/chemical-costs") {
        // Seed one row for ChemicalCosts so the pricing input is
        // rendered inside the admin table.
        return {
          items: [{
            chemical_slug: "liquid_chlorine",
            name:          "Liquid Chlorine",
            unit_kind:     "gal",
            cost_per_unit_cents: 450,
            updated_at:    "2026-02-01T00:00:00+00:00",
          }],
        };
      }
      if (p && p.includes("/chemical-products")) {
        return { items: [] };
      }
      return null;
    }),
    post: vi.fn(async () => ({ ok: true })),
    put:  vi.fn(async () => ({ ok: true })),
  },
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u1", name: "Admin" } }),
}));

import CustomerChemistry
  from "@/pages/customers/CustomerChemistry.jsx";
import ChemicalsPage
  from "@/pages/settings/ChemicalsPage.jsx";
import ChemicalCosts
  from "@/pages/admin/ChemicalCosts.jsx";


afterEach(() => cleanup());


/* ═══════════════════════════════════════════════════════════════
 * Site 1 · CustomerChemistry · Add Chemical modal · UNIT PRICE
 * ═══════════════════════════════════════════════════════════════ */
describe("CustomerChemistry · Add Chemical modal · unit_price",
         () => {
  it("accepts intermediate decimal state '1.' and finishes '1.25'",
     async () => {
    render(
      <MemoryRouter initialEntries={["/customers/cx1/chemistry"]}>
        <Routes>
          <Route path="/customers/:id/chemistry"
                  element={<CustomerChemistry />} />
        </Routes>
      </MemoryRouter>,
    );
    // Open the Add modal.
    fireEvent.click(await screen.findByTestId("cx-add-chem"));
    const input = await screen.findByTestId("cx-add-unit-price");
    // Keystroke contract: text + inputMode (never number — number
    // would blank "1." before "1.25" could be typed).
    expect(input.getAttribute("type")).toBe("text");
    expect(input.getAttribute("inputmode")).toBe("decimal");

    fireEvent.change(input, { target: { value: "1" } });
    expect(input.value).toBe("1");
    fireEvent.change(input, { target: { value: "1." } });
    expect(input.value).toBe("1.");
    fireEvent.change(input, { target: { value: "1.2" } });
    expect(input.value).toBe("1.2");
    fireEvent.change(input, { target: { value: "1.25" } });
    expect(input.value).toBe("1.25");
  });

  it("rejects letters at keystroke, state holds at the last-valid "
     + "snapshot", async () => {
    render(
      <MemoryRouter initialEntries={["/customers/cx1/chemistry"]}>
        <Routes>
          <Route path="/customers/:id/chemistry"
                  element={<CustomerChemistry />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByTestId("cx-add-chem"));
    const input = await screen.findByTestId("cx-add-unit-price");
    fireEvent.change(input, { target: { value: "1.25" } });
    expect(input.value).toBe("1.25");
    fireEvent.change(input, { target: { value: "1.25a" } });
    // Letter rejected — state holds at the last-valid value.
    expect(input.value).toBe("1.25");
  });
});


/* ═══════════════════════════════════════════════════════════════
 * Site 2 · ChemicalsPage · product-edit modal · unit_cost_cents
 * ═══════════════════════════════════════════════════════════════ */
describe("ChemicalsPage · product-edit modal · unit_cost_cents",
         () => {
  it("accepts intermediate '125.' and finishes '125.5'; the live "
     + "``centsToDollars`` preview updates per keystroke", async () => {
    render(<ChemicalsPage />);
    // Open the "new product" modal via the admin-only button.
    const newBtn = await screen.findByTestId("chem-product-new");
    fireEvent.click(newBtn);
    const input = await screen.findByTestId("chem-product-cost");
    expect(input.getAttribute("type")).toBe("text");
    expect(input.getAttribute("inputmode")).toBe("decimal");

    fireEvent.change(input, { target: { value: "125" } });
    expect(input.value).toBe("125");
    fireEvent.change(input, { target: { value: "125." } });
    // Regression lock: pre-fix the type="number" input would blank
    // this to "" because "125." is not a valid HTML5 number literal.
    expect(input.value).toBe("125.");
    fireEvent.change(input, { target: { value: "125.5" } });
    expect(input.value).toBe("125.5");

    // Live-preview sanity — the Storage-in-cents line below the
    // input reads ``editing.unit_cost_cents`` per render.  If a
    // blur-only ``<DecimalInput>`` was used the preview would be
    // stale until focus leaves the field.
    expect(screen.getByText(/Storage in cents\./i)).toBeInTheDocument();
  });
});


/* ═══════════════════════════════════════════════════════════════
 * Site 3 · ChemicalCosts · admin table row · dollars
 * ═══════════════════════════════════════════════════════════════ */
describe("ChemicalCosts · admin table row · dollars column", () => {
  it("accepts intermediate '1.' and finishes '1.25' (keystroke-safe)",
     async () => {
    render(<ChemicalCosts />);
    // Wait for the row to render after the mocked GET resolves.
    const input = await waitFor(() =>
      screen.getByTestId("chemical-cost-dollars-liquid_chlorine"),
    );
    expect(input.getAttribute("type")).toBe("text");
    expect(input.getAttribute("inputmode")).toBe("decimal");

    // Clear the prefilled $4.50 and retype a decimal.
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.change(input, { target: { value: "1" } });
    expect(input.value).toBe("1");
    fireEvent.change(input, { target: { value: "1." } });
    expect(input.value).toBe("1.");
    fireEvent.change(input, { target: { value: "1.2" } });
    expect(input.value).toBe("1.2");
    fireEvent.change(input, { target: { value: "1.25" } });
    expect(input.value).toBe("1.25");
  });
});


/* ═══════════════════════════════════════════════════════════════
 * Cross-field · all 3 reject letters, accept leading-dot entry
 * ═══════════════════════════════════════════════════════════════ */
describe("PRICING-DECIMAL-INPUT-PARITY · cross-field happy path",
         () => {
  it("CustomerChemistry · Add modal unit_price accepts '.5' "
     + "(leading-dot regex guard)", async () => {
    render(
      <MemoryRouter initialEntries={["/customers/cx1/chemistry"]}>
        <Routes>
          <Route path="/customers/:id/chemistry"
                  element={<CustomerChemistry />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByTestId("cx-add-chem"));
    const input = await screen.findByTestId("cx-add-unit-price");
    fireEvent.change(input, { target: { value: "." } });
    expect(input.value).toBe(".");
    fireEvent.change(input, { target: { value: ".5" } });
    expect(input.value).toBe(".5");
  });

  it("ChemicalsPage · unit_cost_cents accepts '.5' (leading-dot)",
     async () => {
    render(<ChemicalsPage />);
    fireEvent.click(await screen.findByTestId("chem-product-new"));
    const input = await screen.findByTestId("chem-product-cost");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.change(input, { target: { value: "." } });
    expect(input.value).toBe(".");
    fireEvent.change(input, { target: { value: ".5" } });
    expect(input.value).toBe(".5");
  });

  it("ChemicalCosts · dollars rejects multi-dot '1.2.5' (regex guard)",
     async () => {
    render(<ChemicalCosts />);
    const input = await waitFor(() =>
      screen.getByTestId("chemical-cost-dollars-liquid_chlorine"),
    );
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.change(input, { target: { value: "1.2" } });
    expect(input.value).toBe("1.2");
    // Second-dot paste fails the regex and is dropped.
    fireEvent.change(input, { target: { value: "1.2.5" } });
    expect(input.value).toBe("1.2");
  });
});
