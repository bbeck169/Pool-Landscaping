/**
 * Phase 2 B2 · T4 regression · Feb-2026 — proves `/quotes/new`
 * actually mounts the unified <QuoteRecipientPicker> with its
 * universal `data-testid="quote-recipient-picker"` present on the
 * trigger (NOT shadowed by a prop override). The sibling
 * `data-testid="qf-customer"` MUST be absent — the create form has
 * been migrated off the legacy picker.
 *
 * This test exists because a previous B2 vitest mounted the picker
 * in isolation (default testid) while QuoteInvoiceNew passed a
 * `testid="qf-customer"` prop override that stripped the universal
 * testid on the live preview. The red→green ordering is enforced
 * in the atomic bash script that lands this file.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u-1" }, token: "t" }),
}));

import { api } from "@/api";
import QuoteInvoiceNew from "@/pages/quotes/QuoteInvoiceNew";

beforeEach(() => {
  api.get.mockReset();
  // Prevent the mounted component from blowing up during its
  // ``/customers`` + ``/pricebook`` fetches — resolve empty.
  api.get.mockImplementation(async () => []);
});

describe("Phase 2 B2 · T4 regression — /quotes/new mounts the unified picker", () => {
  it("quote create route renders data-testid=quote-recipient-picker on the trigger", async () => {
    render(
      <MemoryRouter initialEntries={["/quotes/new"]}>
        <Routes>
          <Route
            path="/quotes/new"
            element={<QuoteInvoiceNew docType="quote" />}
          />
        </Routes>
      </MemoryRouter>,
    );
    const trigger = await waitFor(
      () => screen.getByTestId("quote-recipient-picker"),
      { timeout: 2000 },
    );
    expect(trigger).toBeInTheDocument();
    expect(trigger.tagName.toLowerCase()).toBe("button");
    // Legacy testid MUST NOT be present on the create form after
    // B2. If this ever re-appears, it means a prop override is
    // shadowing the universal testid again — regression.
    expect(screen.queryByTestId("qf-customer")).toBeNull();
  });

  it("invoice create route also renders data-testid=quote-recipient-picker (shared component)", async () => {
    render(
      <MemoryRouter initialEntries={["/invoices/new"]}>
        <Routes>
          <Route
            path="/invoices/new"
            element={<QuoteInvoiceNew docType="invoice" />}
          />
        </Routes>
      </MemoryRouter>,
    );
    const trigger = await waitFor(
      () => screen.getByTestId("quote-recipient-picker"),
      { timeout: 2000 },
    );
    expect(trigger).toBeInTheDocument();
    expect(screen.queryByTestId("qf-customer")).toBeNull();
  });
});
