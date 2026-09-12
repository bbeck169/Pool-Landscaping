/**
 * Phase K79 · Feb-2026 — K79CustomerViewSection · descriptions +
 * preview. Grouped-layout toggle retired by Cleanup Dispatch A · Item
 * 3 (grouped is always ON for customer surfaces). This suite now
 * covers:
 *  1. Renders the retired-banner instead of the old toggle checkbox.
 *  2. Description editor is always shown (no longer gated on toggle).
 *  3. Description editor rows appear for each unique
 *     service_category_id in the doc.
 *  4. Saving a description PUTs the full customer_group_descriptions
 *     dict to the server.
 *  5. Preview modal opens/closes on button click.
 *  6. Empty hint renders when no line item carries a category.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const putSpy = vi.fn(async () => ({}));

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (url) => {
      if (url === "/service-categories") {
        return {
          items: [
            { id: "svc-pool", name: "Pool Cleaning", color: "#0EA5E9" },
            { id: "svc-tile", name: "Tile & Coping", color: "#22C55E" },
          ],
        };
      }
      return { items: [] };
    }),
    put: (...args) => putSpy(...args),
  },
}));

import K79CustomerViewSection
  from "@/components/quotes/K79CustomerViewSection";

const baseDoc = {
  id: "quote-1",
  customer_group_display: true,
  customer_group_descriptions: {},
  subtotal: 260,
  tax_rate: 0,
  tax: 0,
  total: 260,
  line_items: [
    {
      description: "Weekly cleaning", quantity: 4, unit_price: 40,
      service_category_id: "svc-pool",
    },
    {
      description: "Chlorine treatment", quantity: 1, unit_price: 60,
      service_category_id: "svc-pool",
    },
    {
      description: "Grout resealing", quantity: 1, unit_price: 200,
      service_category_id: "svc-tile",
    },
  ],
};


beforeEach(() => {
  putSpy.mockClear();
});


describe("Phase K79 · K79CustomerViewSection", () => {
  it("renders the retired-toggle banner (grouped locked ON)",
    async () => {
    render(<K79CustomerViewSection doc={baseDoc} onDocRefresh={vi.fn()} />);
    const banner = screen.getByTestId("k79-toggle-retired-banner");
    expect(banner).toBeTruthy();
    expect(banner.textContent).toContain("GROUPED LAYOUT (ON)");
    expect(banner.textContent).toContain("always on");
    // The old interactive checkbox is gone.
    expect(screen.queryByTestId("k79-toggle-checkbox")).toBeNull();
  });

  it("never PUTs customer_group_display (toggle retired)", async () => {
    render(<K79CustomerViewSection doc={baseDoc} onDocRefresh={vi.fn()} />);
    // Wait a tick to let effects flush.
    await waitFor(() => {
      expect(screen.getByTestId("k79-toggle-retired-banner")).toBeTruthy();
    });
    // No PUT for the toggle should have been fired.
    const flagPuts = putSpy.mock.calls.filter(([_, body]) =>
      body && "customer_group_display" in (body || {}),
    );
    expect(flagPuts).toHaveLength(0);
  });

  it("shows description editor rows for each unique service_category_id",
    async () => {
    render(<K79CustomerViewSection doc={baseDoc} onDocRefresh={vi.fn()} />);
    // Service categories fetched via mock — wait for editor rows.
    await waitFor(() => {
      expect(screen.getByTestId("k79-desc-row-svc-pool")).toBeTruthy();
      expect(screen.getByTestId("k79-desc-row-svc-tile")).toBeTruthy();
    });
  });

  it("descriptions editor is always shown regardless of the "
        + "(now-retired) customer_group_display value",
    async () => {
    const doc = { ...baseDoc, customer_group_display: false };
    render(<K79CustomerViewSection doc={doc} onDocRefresh={vi.fn()} />);
    // Editor is present even though customer_group_display=false —
    // proves the toggle no longer gates the editor.
    await waitFor(() => {
      expect(screen.getByTestId("k79-descriptions-editor")).toBeTruthy();
    });
  });

  it("saves a description via PUT with the full descriptions dict",
    async () => {
    render(<K79CustomerViewSection doc={baseDoc} onDocRefresh={vi.fn()} />);
    // Wait for editor to be ready.
    await waitFor(() => {
      expect(screen.getByTestId("k79-desc-input-svc-pool")).toBeTruthy();
    });
    // Type into the pool description.
    fireEvent.change(screen.getByTestId("k79-desc-input-svc-pool"), {
      target: { value: "Bundled pool care package." },
    });
    fireEvent.click(screen.getByTestId("k79-desc-save-svc-pool"));

    await waitFor(() => {
      expect(putSpy).toHaveBeenCalledWith(
        "/quotes/quote-1",
        { customer_group_descriptions: {
            "svc-pool": "Bundled pool care package.",
        }},
      );
    });
  });

  it("opens and closes the preview modal", async () => {
    render(<K79CustomerViewSection doc={baseDoc} onDocRefresh={vi.fn()} />);
    fireEvent.click(screen.getByTestId("k79-preview-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("k79-preview-modal")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("k79-preview-close"));
    await waitFor(() => {
      expect(screen.queryByTestId("k79-preview-modal")).toBeNull();
    });
  });

  it("shows the empty hint when no line item carries a category",
    async () => {
    const doc = {
      ...baseDoc,
      line_items: [
        { description: "Uncategorized service", quantity: 1, unit_price: 50 },
      ],
    };
    render(<K79CustomerViewSection doc={doc} onDocRefresh={vi.fn()} />);
    // The empty hint should render because no line has service_category_id.
    // Wait a tick for service-categories fetch to settle so the editor
    // completes its render pass.
    await waitFor(() => {
      expect(screen.getByTestId("k79-empty-hint")).toBeTruthy();
    });
  });
});
