/**
 * warranties-expiring-tile · Feb-2026 · Polish bundle Item 3
 *
 * Locks the WarrantiesExpiringTile contract:
 *  1. Renders and hits ``GET /warranties/expiring-soon?days=30`` on mount.
 *  2. Empty state renders when ``items === []``.
 *  3. Populated rows render contract name, customer, days-remaining
 *     badge, linked_summary chip (when present), and a Renew shortcut.
 *  4. Row click navigates to ``/customers/{id}?tab=warranties``.
 *  5. Testids: ``warranties-expiring-tile`` + ``warranties-expiring-row-<i>``
 *     + per-row Renew button.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
const navigateMock = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...args) => getMock(...args),
    post: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    muted: "#666", brand: "#0B4A6F", onSurface: "#111", border: "#ddd",
    surfaceSecondary: "#F4F4F5",
    brandTertiary: "#E0F2FE", onBrandTertiary: "#0369A1",
  },
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useNavigate: () => navigateMock };
});

import WarrantiesExpiringTile from "@/components/admin/WarrantiesExpiringTile";


beforeEach(() => {
  getMock.mockReset();
  navigateMock.mockReset();
});

const _renderWith = (ui) =>
  render(<MemoryRouter>{ui}</MemoryRouter>);


describe("WarrantiesExpiringTile · Polish bundle Item 3", () => {
  it("fires GET /warranties/expiring-soon?days=30 on mount", async () => {
    getMock.mockResolvedValue({ items: [], days: 30 });
    _renderWith(<WarrantiesExpiringTile />);
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(getMock.mock.calls[0][0]).toContain("/warranties/expiring-soon");
    expect(getMock.mock.calls[0][0]).toContain("days=30");
  });

  it("renders empty state when items is empty", async () => {
    getMock.mockResolvedValue({ items: [], days: 30 });
    _renderWith(<WarrantiesExpiringTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("warranties-expiring-empty")).toBeTruthy(),
    );
    expect(screen.getByTestId("warranties-expiring-empty").textContent)
      .toContain("No warranties expiring");
  });

  it("renders rows with contract name, customer + days-remaining chip", async () => {
    getMock.mockResolvedValue({
      items: [
        { id: "w1", contract_name: "Extended Pool Warranty",
          customer_id: "c1", customer_name: "Alice Adams",
          coverage_end: "2026-02-13", days_remaining: 5,
          linked_summary: "Install job #a1b2" },
        { id: "w2", contract_name: "Basic Pool Warranty",
          customer_id: "c2", customer_name: "Bob Baker",
          coverage_end: "2026-02-28", days_remaining: 20 },
      ],
      days: 30,
    });
    _renderWith(<WarrantiesExpiringTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("warranties-expiring-row-0")).toBeTruthy(),
    );
    const row0 = screen.getByTestId("warranties-expiring-row-0");
    expect(row0.textContent).toContain("Extended Pool Warranty");
    expect(row0.textContent).toContain("Alice Adams");
    expect(row0.textContent).toContain("Install job #a1b2");
    expect(row0.textContent).toContain("5d");

    const row1 = screen.getByTestId("warranties-expiring-row-1");
    expect(row1.textContent).toContain("Basic Pool Warranty");
    expect(row1.textContent).toContain("Bob Baker");
    expect(row1.textContent).toContain("20d");
    // Unlinked row must NOT render the summary chip
    expect(row1.textContent).not.toContain("Install job");
  });

  it("truncates rows to top-5 client-side", async () => {
    getMock.mockResolvedValue({
      items: Array.from({ length: 8 }, (_v, i) => ({
        id: `w${i}`, contract_name: `Warranty ${i}`,
        customer_id: `c${i}`, customer_name: `Cust ${i}`,
        coverage_end: "2026-02-20", days_remaining: i + 1,
      })),
      days: 30,
    });
    _renderWith(<WarrantiesExpiringTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("warranties-expiring-row-4")).toBeTruthy(),
    );
    expect(screen.queryByTestId("warranties-expiring-row-5")).toBeNull();
  });

  it("row click navigates to customer warranties tab", async () => {
    getMock.mockResolvedValue({
      items: [
        { id: "w1", contract_name: "Extended Pool Warranty",
          customer_id: "cust-abc", customer_name: "Alice",
          coverage_end: "2026-02-13", days_remaining: 5 },
      ],
      days: 30,
    });
    _renderWith(<WarrantiesExpiringTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("warranties-expiring-row-0")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("warranties-expiring-row-0"));
    expect(navigateMock).toHaveBeenCalledWith(
      "/customers/cust-abc?tab=warranties",
    );
  });

  it("Renew button navigates to same route without double-firing", async () => {
    getMock.mockResolvedValue({
      items: [
        { id: "w1", contract_name: "Extended Pool Warranty",
          customer_id: "cust-abc", customer_name: "Alice",
          coverage_end: "2026-02-13", days_remaining: 5 },
      ],
      days: 30,
    });
    _renderWith(<WarrantiesExpiringTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("warranties-expiring-row-0-renew"))
        .toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("warranties-expiring-row-0-renew"));
    expect(navigateMock).toHaveBeenCalledWith(
      "/customers/cust-abc?tab=warranties",
    );
    // stopPropagation prevents the row's onClick from firing again
    expect(navigateMock).toHaveBeenCalledTimes(1);
  });

  it("carries the outer tile testid", async () => {
    getMock.mockResolvedValue({ items: [], days: 30 });
    _renderWith(<WarrantiesExpiringTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("warranties-expiring-tile")).toBeTruthy(),
    );
  });
});
