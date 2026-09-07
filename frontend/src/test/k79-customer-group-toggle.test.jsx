/**
 * Phase K79 · Feb-2026 — K79CustomerViewSection · toggle + descriptions.
 *
 * Coverage:
 *  1. Renders the toggle checkbox reflecting doc.customer_group_display.
 *  2. Toggling OFF PUTs the flag to the server; toggling ON PUTs true.
 *  3. Description editor rows appear when enabled AND line_items carry
 *     service_category_id values.
 *  4. Description editor hides when the toggle is off.
 *  5. Saving a description PUTs the full customer_group_descriptions
 *     dict to the server.
 *  6. Preview modal opens on button click; closes on X.
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
  it("renders the toggle checkbox reflecting doc.customer_group_display",
    async () => {
    render(<K79CustomerViewSection doc={baseDoc} onDocRefresh={vi.fn()} />);
    const box = screen.getByTestId("k79-toggle-checkbox");
    expect(box.checked).toBe(true);
  });

  it("PUTs customer_group_display=false when unchecked", async () => {
    render(<K79CustomerViewSection doc={baseDoc} onDocRefresh={vi.fn()} />);
    fireEvent.click(screen.getByTestId("k79-toggle-checkbox"));
    await waitFor(() => {
      expect(putSpy).toHaveBeenCalledWith(
        "/quotes/quote-1",
        { customer_group_display: false },
      );
    });
  });

  it("PUTs customer_group_display=true when re-checked", async () => {
    const doc = { ...baseDoc, customer_group_display: false };
    render(<K79CustomerViewSection doc={doc} onDocRefresh={vi.fn()} />);
    fireEvent.click(screen.getByTestId("k79-toggle-checkbox"));
    await waitFor(() => {
      expect(putSpy).toHaveBeenCalledWith(
        "/quotes/quote-1",
        { customer_group_display: true },
      );
    });
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

  it("hides the description editor when toggle is off", () => {
    const doc = { ...baseDoc, customer_group_display: false };
    render(<K79CustomerViewSection doc={doc} onDocRefresh={vi.fn()} />);
    expect(screen.queryByTestId("k79-descriptions-editor")).toBeNull();
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
