/**
 * P2 #4 · Feb-2026 — "Linked to lead" chip + Unlink on QuoteInvoiceNew.
 *
 * Locks three invariants:
 *   1. Visiting ``/quotes/new?recipient_type=lead&recipient_id=<id>``
 *      renders a visible chip above the recipient picker with the
 *      hydrated lead name (fetched via GET /leads/<id>).
 *   2. Clicking Unlink clears the recipient AND navigates to a clean
 *      ``/quotes/new`` (replaces history).
 *   3. The chip does NOT render on a clean /quotes/new (no preselect)
 *      — the picker itself surfaces mid-form picks.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup }
  from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { apiGetSpy, apiPostSpy, navigateMock } = vi.hoisted(() => ({
  apiGetSpy: vi.fn(),
  apiPostSpy: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGetSpy(...a),
    post: (...a) => apiPostSpy(...a),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin" } }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});


import QuoteInvoiceNew from "@/pages/quotes/QuoteInvoiceNew";


beforeEach(() => {
  apiGetSpy.mockReset();
  apiPostSpy.mockReset();
  navigateMock.mockReset();
  apiGetSpy.mockImplementation((url) => {
    if (url.startsWith("/customers"))
      return Promise.resolve([]);
    if (url.startsWith("/leads/lead-xyz"))
      return Promise.resolve({ id: "lead-xyz", name: "Larry Lead" });
    if (url.startsWith("/settings/terms"))
      return Promise.resolve({ default_quote_terms: "" });
    return Promise.resolve(null);
  });
  apiPostSpy.mockResolvedValue({ id: "q-1" });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});


function _mount(initialPath) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <QuoteInvoiceNew docType="quote" />
    </MemoryRouter>,
  );
}


describe("P2 #4 — Linked-to-lead chip on QuoteInvoiceNew", () => {
  it("renders chip with hydrated lead name when URL preselects a Lead", async () => {
    _mount("/quotes/new?recipient_type=lead&recipient_id=lead-xyz");
    const chip = await screen.findByTestId("qf-linked-lead-chip");
    expect(chip).toBeTruthy();
    const nameNode = await waitFor(() => {
      const n = screen.getByTestId("qf-linked-lead-name");
      expect(n.textContent).toContain("Larry Lead");
      return n;
    });
    expect(nameNode.textContent).toContain("Larry Lead");
  });

  it("Unlink clears the recipient AND navigates to clean /quotes/new", async () => {
    _mount("/quotes/new?recipient_type=lead&recipient_id=lead-xyz");
    const btn = await screen.findByTestId("qf-linked-lead-unlink");
    fireEvent.click(btn);
    expect(navigateMock).toHaveBeenCalledWith("/quotes/new", { replace: true });
    // Chip should disappear after unlink.
    await waitFor(() => {
      expect(screen.queryByTestId("qf-linked-lead-chip")).toBeNull();
    });
  });

  it("does NOT render chip on a clean /quotes/new (no preselect)", async () => {
    _mount("/quotes/new");
    // Wait a tick for effects to settle.
    await waitFor(() => {
      expect(screen.getByTestId("quote-new-page")).toBeTruthy();
    });
    expect(screen.queryByTestId("qf-linked-lead-chip")).toBeNull();
  });
});
