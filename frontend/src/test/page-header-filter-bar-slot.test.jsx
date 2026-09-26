/**
 * N5.filterBar · Feb-2026 — Optional filter-bar slot tests.
 *
 * Preflight for the N5-T2 sweep. Locks four contracts:
 *
 *   1. Prop omitted → NO filter-bar slot rendered. Every existing
 *      PageHeader consumer stays byte-identical to pre-B DOM.
 *   2. Prop present → slot renders inside ``<header>`` with the
 *      dedicated testid ``page-header-filter-bar-slot`` so E2E can
 *      target it directly.
 *   3. DOM order — slot lives BELOW the title row. Combined with
 *      the prior reorder commit (search band above title row) the
 *      full order becomes: search-band → title-row → filter-bar.
 *   4. Slot's 24px horizontal padding aligns filterBar chips with
 *      the title-row + search-band edges. No vertical padding —
 *      the child (typically ``<NavyFilterBar>``) supplies its own
 *      ``mb-4`` for below-spacing.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ─── Same theme mock as page-header-search.test.jsx ─────────────
vi.mock("@/theme", () => ({
  colors: {
    surface: "#ffffff",
    surfaceSecondary: "#F5F5F5",
    onSurface: "#111111",
    onSurfaceSecondary: "#555555",
    border: "#DDD",
    divider: "#EEE",
    muted: "#71717A",
    searchIcon: "#1B1F5C",
    inputBorder: "#3B82F6",
    nav: {
      bg: "#1B1F5C", bgDeep: "#03002e",
      border: "rgba(255, 255, 255, 0.10)",
    },
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(() => new Promise(() => {})),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    del: vi.fn(() => Promise.resolve({})),
  },
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { role: "admin", id: "u-1" },
    role: "admin",
    loading: false,
  }),
}));


beforeEach(() => {
  window.localStorage?.clear?.();
});
afterEach(() => {
  cleanup();
});


// ═════════════════════════════════════════════════════════════════
// 1 · Prop omitted → slot NOT rendered
// ═════════════════════════════════════════════════════════════════
describe("PageHeader filterBar slot · backwards compat", () => {
  it("does NOT render the slot when filterBar prop is omitted", async () => {
    const { PageHeader } = await import("@/components/layout/PageHeader");
    render(
      <MemoryRouter>
        <PageHeader title="Invoices" />
      </MemoryRouter>,
    );
    expect(
      screen.queryByTestId("page-header-filter-bar-slot"),
    ).toBeNull();
  });

  it("does NOT render the slot when filterBar={null}", async () => {
    const { PageHeader } = await import("@/components/layout/PageHeader");
    render(
      <MemoryRouter>
        <PageHeader title="Invoices" filterBar={null} />
      </MemoryRouter>,
    );
    expect(
      screen.queryByTestId("page-header-filter-bar-slot"),
    ).toBeNull();
  });

  it("does NOT render the slot when filterBar={false}", async () => {
    const { PageHeader } = await import("@/components/layout/PageHeader");
    render(
      <MemoryRouter>
        <PageHeader title="Invoices" filterBar={false} />
      </MemoryRouter>,
    );
    expect(
      screen.queryByTestId("page-header-filter-bar-slot"),
    ).toBeNull();
  });
});


// ═════════════════════════════════════════════════════════════════
// 2 · Prop present → slot renders + child accessible
// ═════════════════════════════════════════════════════════════════
describe("PageHeader filterBar slot · render contract", () => {
  it("renders the slot inside <header> with its dedicated testid", async () => {
    const { PageHeader } = await import("@/components/layout/PageHeader");
    render(
      <MemoryRouter>
        <PageHeader
          title="Chemical Applications"
          filterBar={(
            <div data-testid="scratch-chip-row">
              chip A · chip B · chip C
            </div>
          )}
        />
      </MemoryRouter>,
    );
    const slot = await screen.findByTestId(
      "page-header-filter-bar-slot",
    );
    expect(slot).toBeTruthy();
    // Slot MUST live inside the <header> — the semantic anchor N5-T2
    // consumers rely on for layout composition.
    const header = screen.getByTestId("page-header");
    expect(header.contains(slot)).toBe(true);
    // Child content accessible via its own testid — the slot is a
    // pass-through, so any deep child testid keeps working.
    expect(
      screen.getByTestId("scratch-chip-row").textContent,
    ).toContain("chip A · chip B · chip C");
  });

  it("slot has 24px horizontal padding to align chips with title/search insets", async () => {
    const { PageHeader } = await import("@/components/layout/PageHeader");
    render(
      <MemoryRouter>
        <PageHeader
          title="Sample"
          filterBar={<div>chips</div>}
        />
      </MemoryRouter>,
    );
    const slot = await screen.findByTestId(
      "page-header-filter-bar-slot",
    );
    const cs = window.getComputedStyle(slot);
    expect(cs.paddingLeft).toBe("24px");
    expect(cs.paddingRight).toBe("24px");
    // Zero vertical padding — child owns its own ``mb-4``.
    expect(cs.paddingTop).toBe("0px");
    expect(cs.paddingBottom).toBe("0px");
  });
});


// ═════════════════════════════════════════════════════════════════
// 3 · DOM order — search-band → title-row → filter-bar
// ═════════════════════════════════════════════════════════════════
describe("PageHeader filterBar slot · DOM order", () => {
  it("filter-bar slot renders BELOW the title row", async () => {
    const { PageHeader } = await import("@/components/layout/PageHeader");
    const { container } = render(
      <MemoryRouter>
        <PageHeader
          title="Sample"
          filterBar={<div>chips</div>}
        />
      </MemoryRouter>,
    );
    const titleRow = container.querySelector(
      '[data-testid="page-header-title-row"]',
    );
    const slot = container.querySelector(
      '[data-testid="page-header-filter-bar-slot"]',
    );
    // eslint-disable-next-line no-bitwise
    expect(
      titleRow.compareDocumentPosition(slot)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("filter-bar slot renders BELOW the search band (row 3)", async () => {
    const { PageHeader } = await import("@/components/layout/PageHeader");
    const { container } = render(
      <MemoryRouter>
        <PageHeader
          title="Sample"
          filterBar={<div>chips</div>}
        />
      </MemoryRouter>,
    );
    const searchBand = container.querySelector(
      '[data-testid="page-header-search-band"]',
    );
    const slot = container.querySelector(
      '[data-testid="page-header-filter-bar-slot"]',
    );
    // eslint-disable-next-line no-bitwise
    expect(
      searchBand.compareDocumentPosition(slot)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});


// ═════════════════════════════════════════════════════════════════
// 4 · Slot doesn't disrupt search-input keyboard nav
// ═════════════════════════════════════════════════════════════════
describe("PageHeader filterBar slot · keyboard nav intact", () => {
  it("search input still receives keydown events when the slot renders", async () => {
    const { PageHeader } = await import("@/components/layout/PageHeader");
    render(
      <MemoryRouter>
        <PageHeader
          title="Sample"
          filterBar={<div data-testid="filter-scratch">chips</div>}
        />
      </MemoryRouter>,
    );
    const input = await screen.findByTestId(
      "page-header-search-input",
    );
    // Focus + type a couple of characters — the input controls its
    // own ``value`` via a controlled React state, so the query
    // makes it into the DOM without any listener conflict from the
    // new slot.
    input.focus();
    fireEvent.change(input, { target: { value: "invoices" } });
    await waitFor(() => {
      expect(input.value).toBe("invoices");
    });
    // Escape must clear the query (existing shortcut contract).
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => {
      expect(input.value).toBe("");
    });
  });
});
