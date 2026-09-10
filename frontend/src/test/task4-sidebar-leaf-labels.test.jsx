/**
 * Feb-2026 · Task 4 · Sidebar leaf-label simplification.
 *
 * Guards:
 *   1. `pinPickerForRole('admin')` emits leaf-only labels — no
 *      `"Sales · Quotes"` / `"Schedule & Dispatch · Pricebook"`
 *      hierarchy strings.
 *   2. `QuickPinsRail` renders a legacy `"Sales · Quotes"` pin as
 *      just `"Quotes"` (defense-in-depth shim for pins persisted
 *      before this change).
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── #1 · pinPickerForRole registry contract ─────────────────
import { pinPickerForRole } from "@/nav/pinRegistry";

describe("pinPickerForRole (Task 4 · leaf labels)", () => {
  it("emits leaf labels — no ` · ` hierarchy in any admin entry", () => {
    const groups = pinPickerForRole("admin");
    const flat = groups.flatMap((g) => g.entries.map((e) => e.label));
    expect(flat.length).toBeGreaterThan(0);
    for (const label of flat) {
      expect(label.includes(" · ")).toBe(false);
    }
  });

  it("finds `Quotes` and `Pricebook` in the admin catalog", () => {
    const groups = pinPickerForRole("admin");
    const flat = groups.flatMap((g) => g.entries.map((e) => e.label));
    expect(flat).toContain("Quotes");
    expect(flat).toContain("Pricebook");
    expect(flat).not.toContain("Sales · Quotes");
    expect(flat).not.toContain("Schedule & Dispatch · Pricebook");
  });
});


// ── #2 · QuickPinsRail legacy-label shim ────────────────────
// Mock the heavy dnd-kit setup so we can render just the visual
// output. Wire minimal stubs for the sortable context.
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children }) => <div>{children}</div>,
  PointerSensor: class { },
  KeyboardSensor: class { },
  useSensor: () => ({}),
  useSensors: () => [],
  closestCenter: () => null,
}));
vi.mock("@dnd-kit/sortable", () => ({
  SortableContext: ({ children }) => <div>{children}</div>,
  sortableKeyboardCoordinates: () => null,
  useSortable: () => ({
    attributes: {}, listeners: {}, setNodeRef: () => {}, transform: null,
    transition: null, isDragging: false,
  }),
  arrayMove: (arr) => arr,
  verticalListSortingStrategy: null,
}));
vi.mock("@dnd-kit/utilities", () => ({
  CSS: { Transform: { toString: () => "" } },
}));
vi.mock("@/api", () => ({
  api: { get: vi.fn(async () => ({ pins: [], cap: 8 })),
         put: vi.fn(async () => ({ pins: [] })) },
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));
vi.mock("@/components/nav/AddPinModal", () => ({
  __esModule: true,
  default: () => null,
}));
vi.mock("@/components/nav/RemovePinConfirm", () => ({
  __esModule: true,
  default: () => null,
}));

// The rail file expects a `pins` array via API — force-hydrate by
// mounting the internal SortableRailPin with a legacy label directly.
// (Re-export not available; import the module and reach into it via
// a small custom harness component below.)

// Recreate the private `_displayLabel` behaviour by rendering the
// whole rail and letting it fetch mocked pins.
vi.mock("@/hooks/useQuickPins", () => ({
  useQuickPins: () => ({
    pins: [
      { to: "/quotes",     label: "Sales · Quotes",                  Icon: () => null, iconKey: "file_text" },
      { to: "/price-book", label: "Schedule & Dispatch · Pricebook", Icon: () => null, iconKey: "tag" },
      { to: "/customers",  label: "Customers",                        Icon: () => null, iconKey: "users" },
    ],
    addPin: async () => ({ ok: true }),
    removePin: async () => ({ ok: true }),
    reorderPins: async () => ({ ok: true }),
    atCap: false,
    cap: 8,
    pinnedRoutes: new Set(["/quotes", "/price-book", "/customers"]),
  }),
}));

vi.mock("@/api", () => ({
  api: { get: vi.fn(async () => ({})), put: vi.fn(async () => ({})) },
}));

import QuickPinsRail from "@/components/nav/QuickPinsRail";

describe("QuickPinsRail (Task 4 · legacy label shim)", () => {
  afterEach(() => cleanup());

  it("renders legacy `Sales · Quotes` pin as `Quotes`", async () => {
    render(
      <MemoryRouter>
        <QuickPinsRail role="admin" />
      </MemoryRouter>,
    );
    // The rail waits for the pin fetch — findByText retries.
    await screen.findByText("Quotes");
    expect(screen.queryByText("Sales · Quotes")).toBeNull();
    expect(await screen.findByText("Pricebook")).toBeInTheDocument();
    expect(screen.queryByText("Schedule & Dispatch · Pricebook")).toBeNull();
    // Unaffected pins render unchanged.
    expect(await screen.findByText("Customers")).toBeInTheDocument();
  });
});
