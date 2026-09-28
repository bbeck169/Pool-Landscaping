/**
 * Phase K79-TOGGLE · Feb-2026 — K79CustomerViewSection · Switch.
 *
 * Locks the toggle re-enable:
 *
 *   1. Switch renders (NOT the retired banner) and its
 *      ``aria-checked`` reflects ``doc.customer_group_display``.
 *   2. Legacy default: field missing / null → checked=true.
 *   3. Clicking the Switch optimistically flips + PUTs
 *      ``customer_group_display`` with the new value.
 *   4. On PUT failure the Switch reverts to the prior state and a
 *      ``toast.error`` is fired.
 *   5. Pill label mirrors the toggle state (``GROUPED LAYOUT (ON)``
 *      / ``(OFF)``).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { putSpy, getSpy } = vi.hoisted(() => ({
  putSpy: vi.fn(),
  getSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    put: (...a) => putSpy(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { toast } from "sonner";
import K79CustomerViewSection
  from "@/components/quotes/K79CustomerViewSection";


const baseDoc = {
  id: "quote-1",
  customer_group_display: true,
  customer_group_descriptions: {},
  line_items: [
    { description: "Weekly cleaning", quantity: 4, unit_price: 40,
      service_category_id: "svc-pool" },
    { description: "Grout resealing", quantity: 1, unit_price: 200,
      service_category_id: "svc-tile" },
  ],
};


beforeEach(() => {
  putSpy.mockReset();
  getSpy.mockReset();
  getSpy.mockImplementation((url) => {
    if (url === "/service-categories") {
      return Promise.resolve({
        items: [
          { id: "svc-pool", name: "Pool Cleaning" },
          { id: "svc-tile", name: "Tile & Coping" },
        ],
      });
    }
    return Promise.resolve({ items: [] });
  });
});


describe("K79-TOGGLE · K79CustomerViewSection Switch", () => {
  it("renders the Switch (not the retired banner) with aria-checked=true "
     + "when customer_group_display=true", async () => {
    render(<K79CustomerViewSection doc={baseDoc} onDocRefresh={vi.fn()} />);
    const sw = screen.getByTestId("k79-grouped-toggle");
    expect(sw).toBeTruthy();
    expect(sw.getAttribute("aria-checked")).toBe("true");
    // Retired banner is NOT rendered.
    expect(screen.queryByTestId("k79-toggle-retired-banner")).toBeNull();
    // Pill label mirrors the state.
    expect(screen.getByTestId("k79-grouped-toggle-pill").textContent)
      .toContain("GROUPED LAYOUT (ON)");
  });

  it("Switch is aria-checked=false when customer_group_display=false",
    async () => {
    const doc = { ...baseDoc, customer_group_display: false };
    render(<K79CustomerViewSection doc={doc} onDocRefresh={vi.fn()} />);
    const sw = screen.getByTestId("k79-grouped-toggle");
    expect(sw.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByTestId("k79-grouped-toggle-pill").textContent)
      .toContain("GROUPED LAYOUT (OFF)");
  });

  it("legacy default: field undefined → Switch aria-checked=true",
    async () => {
    const { customer_group_display: _unused, ...rest } = baseDoc;
    render(<K79CustomerViewSection doc={rest} onDocRefresh={vi.fn()} />);
    const sw = screen.getByTestId("k79-grouped-toggle");
    expect(sw.getAttribute("aria-checked")).toBe("true");
  });

  it("legacy default: field null → Switch aria-checked=true", async () => {
    const doc = { ...baseDoc, customer_group_display: null };
    render(<K79CustomerViewSection doc={doc} onDocRefresh={vi.fn()} />);
    const sw = screen.getByTestId("k79-grouped-toggle");
    expect(sw.getAttribute("aria-checked")).toBe("true");
  });

  it("click flips optimistically and PUTs the new value", async () => {
    putSpy.mockResolvedValueOnce({});
    const refresh = vi.fn();
    render(<K79CustomerViewSection doc={baseDoc} onDocRefresh={refresh} />);
    const sw = screen.getByTestId("k79-grouped-toggle");
    expect(sw.getAttribute("aria-checked")).toBe("true");

    fireEvent.click(sw);
    // Optimistic flip is synchronous.
    expect(sw.getAttribute("aria-checked")).toBe("false");

    await waitFor(() => expect(putSpy).toHaveBeenCalledWith(
      "/quotes/quote-1",
      { customer_group_display: false },
    ));
    // Still off after resolve, refresh called.
    await waitFor(() => {
      expect(sw.getAttribute("aria-checked")).toBe("false");
      expect(refresh).toHaveBeenCalled();
    });
    // Pill label follows the state.
    expect(screen.getByTestId("k79-grouped-toggle-pill").textContent)
      .toContain("GROUPED LAYOUT (OFF)");
  });

  it("reverts + toasts error when the PUT fails", async () => {
    putSpy.mockRejectedValueOnce(new Error("boom"));
    render(<K79CustomerViewSection doc={baseDoc} onDocRefresh={vi.fn()} />);
    const sw = screen.getByTestId("k79-grouped-toggle");
    expect(sw.getAttribute("aria-checked")).toBe("true");

    fireEvent.click(sw);
    // Optimistic flip.
    expect(sw.getAttribute("aria-checked")).toBe("false");
    // Reverts after failure.
    await waitFor(() =>
      expect(sw.getAttribute("aria-checked")).toBe("true"),
    );
    expect(toast.error).toHaveBeenCalled();
  });
});
