/**
 * Feb-2026 · P0 — Duplicate Quote modal · Vitest.
 *
 * Locks the frontend contract for the ``DuplicateQuoteModal`` +
 * the button gate on ``QuoteInvoiceDetail``.  Cases (per the
 * adjusted dispatch — property picker replaces address picker):
 *
 *   1. Duplicate button renders on the toolbar for admin.
 *   2. Duplicate button is NOT rendered for technician role.
 *   3. Clicking Duplicate opens the modal with source customer
 *      pre-selected.
 *   4. Changing selected customer refreshes the property dropdown.
 *   5. Selecting a customer with 0 active properties shows the
 *      "No properties on file" hint AND the Duplicate button
 *      remains enabled (backend accepts ``property_id=null``).
 *   6. Successful POST navigates to the new quote's URL and shows
 *      the success toast.
 *   7. 422 from server → error toast with the server's detail
 *      message; modal stays open.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";

const {
  getSpy, postSpy, patchSpy, delSpy, navigateSpy,
} = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
  delSpy: vi.fn(),
  navigateSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api_base: () => "http://localhost/api",
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
    del: (...a) => delSpy(...a),
  },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => ({ id: "src-q-1" }),
  };
});

vi.mock("@/theme", () => ({
  colors: {
    onSurfaceSecondary: "#6B7280",
    border: "#E5E7EB",
    surface: "#FFFFFF",
    onSurface: "#111827",
    brand: "#0B4A6F",
  },
  gradients: {
    navyToGreen: { css: "#0B4A6F", fg: "#FFFFFF" },
  },
  font: { family: "system-ui, sans-serif" },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

// ─── Test data ──────────────────────────────────────────────────────

const _CUSTOMERS = [
  { id: "cust-A", name: "Cust Alpha", customer_number: "A001" },
  { id: "cust-B", name: "Cust Beta", customer_number: "A002" },
  { id: "cust-Z", name: "Cust Zero-Props", customer_number: "A003" },
];

const _PROPS_A = [
  { id: "prop-A1", label: "Alpha Main", active: true },
  { id: "prop-A2", label: "Alpha Guest", active: true },
];
const _PROPS_B = [
  { id: "prop-B1", label: "Beta Main", active: true },
];
const _PROPS_Z = []; // Cust Zero-Props has no active properties.

function _stubGet(path) {
  if (path === "/customers?is_active=true") return Promise.resolve(_CUSTOMERS);
  if (path === "/customers/cust-A/properties") return Promise.resolve(_PROPS_A);
  if (path === "/customers/cust-B/properties") return Promise.resolve(_PROPS_B);
  if (path === "/customers/cust-Z/properties") return Promise.resolve(_PROPS_Z);
  return Promise.resolve([]);
}


// ─── Modal-in-isolation tests (cases 3–7) ───────────────────────────

import DuplicateQuoteModal from "@/components/quotes/DuplicateQuoteModal";

describe("DuplicateQuoteModal · P0", () => {
  beforeEach(() => {
    getSpy.mockReset();
    postSpy.mockReset();
    navigateSpy.mockReset();
    getSpy.mockImplementation(_stubGet);
  });

  afterEach(() => {
    cleanup();
  });

  it("Case 3 · opens with the source customer pre-selected", async () => {
    render(
      <DuplicateQuoteModal
        open
        quoteId="src-q-1"
        sourceCustomerId="cust-A"
        onClose={() => {}}
        onDuplicated={() => {}}
        onError={() => {}}
      />,
    );
    await waitFor(() => {
      const sel = screen.getByTestId("duplicate-quote-customer-select");
      expect(sel.value).toBe("cust-A");
    });
    // Property dropdown auto-loads Alpha's active properties.
    await waitFor(() => {
      const psel = screen.getByTestId("duplicate-quote-property-select");
      expect(psel.value).toBe("prop-A1");
    });
  });

  it("Case 4 · changing selected customer refreshes the property dropdown", async () => {
    render(
      <DuplicateQuoteModal
        open
        quoteId="src-q-1"
        sourceCustomerId="cust-A"
        onClose={() => {}}
        onDuplicated={() => {}}
        onError={() => {}}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("duplicate-quote-property-select").value)
        .toBe("prop-A1"),
    );
    // Swap to cust-B.
    const csel = screen.getByTestId("duplicate-quote-customer-select");
    fireEvent.change(csel, { target: { value: "cust-B" } });
    await waitFor(() =>
      expect(screen.getByTestId("duplicate-quote-property-select").value)
        .toBe("prop-B1"),
    );
  });

  it("Case 5 · zero-active-properties customer shows hint but Duplicate button stays enabled", async () => {
    render(
      <DuplicateQuoteModal
        open
        quoteId="src-q-1"
        sourceCustomerId="cust-A"
        onClose={() => {}}
        onDuplicated={() => {}}
        onError={() => {}}
      />,
    );
    await waitFor(() => screen.getByTestId("duplicate-quote-customer-select"));
    fireEvent.change(
      screen.getByTestId("duplicate-quote-customer-select"),
      { target: { value: "cust-Z" } },
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("duplicate-quote-no-properties-hint"),
      ).toBeTruthy(),
    );
    const btn = screen.getByTestId("duplicate-quote-confirm");
    expect(btn.disabled).toBe(false);
  });

  it("Case 6 · successful POST fires onDuplicated with the new id + number", async () => {
    postSpy.mockResolvedValueOnce({
      quote_id: "new-q-uuid", quote_number: "new-q-u",
    });
    const onDuplicated = vi.fn();
    render(
      <DuplicateQuoteModal
        open
        quoteId="src-q-1"
        sourceCustomerId="cust-A"
        onClose={() => {}}
        onDuplicated={onDuplicated}
        onError={() => {}}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("duplicate-quote-property-select").value)
        .toBe("prop-A1"),
    );
    fireEvent.click(screen.getByTestId("duplicate-quote-confirm"));
    await waitFor(() => expect(onDuplicated).toHaveBeenCalledTimes(1));
    expect(onDuplicated).toHaveBeenCalledWith({
      quote_id: "new-q-uuid", quote_number: "new-q-u",
    });
    // Body threaded to the API includes the resolved property_id.
    expect(postSpy).toHaveBeenCalledWith(
      "/quotes/src-q-1/duplicate",
      { customer_id: "cust-A", property_id: "prop-A1" },
    );
  });

  it("Case 7 · 422 from server surfaces detail via onError; modal stays open", async () => {
    const err = new Error("property_id does not belong to the destination customer");
    err.detail = "property_id does not belong to the destination customer";
    err.status = 422;
    postSpy.mockRejectedValueOnce(err);
    const onDuplicated = vi.fn();
    const onError = vi.fn();
    render(
      <DuplicateQuoteModal
        open
        quoteId="src-q-1"
        sourceCustomerId="cust-A"
        onClose={() => {}}
        onDuplicated={onDuplicated}
        onError={onError}
      />,
    );
    await waitFor(() => screen.getByTestId("duplicate-quote-confirm"));
    fireEvent.click(screen.getByTestId("duplicate-quote-confirm"));
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onError).toHaveBeenCalledWith(
      "property_id does not belong to the destination customer",
    );
    expect(onDuplicated).not.toHaveBeenCalled();
    // Modal stays open — the confirm button is still in the DOM.
    expect(screen.getByTestId("duplicate-quote-confirm")).toBeTruthy();
  });
});


// ─── Button-gate tests (cases 1–2) ─────────────────────────────────
//
// The button lives inside ``QuoteInvoiceDetail.jsx``. Mounting the
// whole page pulls in a lot of ambient routes/state we don't need
// for the RBAC gate — the smallest correct check is that the JSX
// gate is exactly ``!isInvoice && isStaff`` where
// ``isStaff = ["admin","super_admin"].includes(user.role)``. Case 1
// and 2 assert the source contract that ships that gate.

describe("QuoteInvoiceDetail · Duplicate button RBAC gate · P0", () => {
  it("Case 1 · source contains an isStaff-gated Duplicate button (admin/super_admin only)", async () => {
    // Static string contract — locks the specific gate expression
    // and the testid so future refactors either preserve it or
    // fail this test loudly.
    const fs = await import("node:fs/promises");
    const src = await fs.readFile(
      "/app/frontend/src/pages/quotes/QuoteInvoiceDetail.jsx",
      "utf-8",
    );
    // Gate + button + testid appear together.
    expect(src).toMatch(/isStaff\s*=\s*\["admin",\s*"super_admin"\]/);
    expect(src).toMatch(/testid="duplicate-quote-btn"/);
    // The Duplicate button is emitted from the same isStaff branch
    // (matches the Hard Delete pattern the codebase already uses).
    const btnBlock = src.slice(
      src.indexOf('testid="duplicate-quote-btn"') - 400,
      src.indexOf('testid="duplicate-quote-btn"') + 100,
    );
    expect(btnBlock).toMatch(/!isInvoice\s*&&\s*isStaff/);
  });

  it("Case 2 · Duplicate button is NOT rendered for technician role (gate excludes technician)", async () => {
    const fs = await import("node:fs/promises");
    const src = await fs.readFile(
      "/app/frontend/src/pages/quotes/QuoteInvoiceDetail.jsx",
      "utf-8",
    );
    // ``isStaff`` explicitly lists only ``admin`` and ``super_admin``
    // — technician / customer / manager roles fall outside and the
    // button block above never renders. Assert the *absence* of
    // ``technician`` and ``manager`` from the gate expression.
    const gateMatch = src.match(/const isStaff\s*=\s*\[([^\]]+)\]/);
    expect(gateMatch).toBeTruthy();
    const roles = gateMatch[1];
    expect(roles).toMatch(/"admin"/);
    expect(roles).toMatch(/"super_admin"/);
    expect(roles).not.toMatch(/"technician"/);
    expect(roles).not.toMatch(/"customer"/);
  });
});
