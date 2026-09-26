/**
 * Feb-2026 · N1 · <PageHeader> component tests.
 *
 * Covers:
 *   1. H1 renders the ``title`` prop.
 *   2. Search input renders with the exact placeholder.
 *   3. Search input carries the ``colors.inputBorder`` border color.
 *   4. Search band paints ``colors.nav.bg``.
 *   5. Typing "invoi" surfaces Invoices in the dropdown; ↓ + Enter
 *      commits via ``useNavigate``.
 *   6. Typing "pdf upload" surfaces PDF Import (alias match).
 *   7. Empty query hides the dropdown.
 *   8. Esc clears the input and hides the dropdown.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent,
} from "@testing-library/react";

const { navigateSpy } = vi.hoisted(() => ({ navigateSpy: vi.fn() }));
const { searchGlobalSpy } = vi.hoisted(() => ({ searchGlobalSpy: vi.fn() }));

// Mock react-router-dom's ``useNavigate``.
vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateSpy,
}));

// Mock the backend search client so no real fetch fires during
// component tests. Every test resets the spy in ``beforeEach`` and
// can install per-test behaviour (resolve, reject, hang). Default
// resolves with empty groups so existing synchronous tests keep
// working without touching timers.
vi.mock("@/lib/globalSearchClient", () => ({
  searchGlobal: (...args) => searchGlobalSpy(...args),
}));

// Mock the theme so tests are hermetic — the real theme.js file
// is asserted separately in navIndex-adjacent tests. Provide both
// tokens the component reaches for + a minimum viable surface set.
vi.mock("@/theme", () => ({
  colors: {
    surface: "#FFFFFF",
    surfaceSecondary: "#F4F4F5",
    onSurface: "#09090B",
    border: "#E4E4E7",
    muted: "#71717A",
    brandTertiary: "#E0F2FE",
    inputBorder: "#3B82F6",
    nav: { bg: "#1B1F5C", bgDeep: "#03002e" },
  },
}));

// Mock the sidebar so the search fixture is stable across changes
// to the real ``adminNav.js``.
vi.mock("@/nav/adminNav", () => ({
  ADMIN_NAV_V2: [
    { key: "finance", label: "Finance", entries: [
      { to: "/invoices", label: "Invoices",
        aliases: ["Bills", "Receivables"] },
      { to: "/admin/imports/pdf-invoice", label: "PDF Import",
        aliases: ["PDF Upload", "Bulk Import"] },
      { to: "/payments", label: "Payments" },
    ] },
    { key: "ops", label: "Operations", entries: [
      { to: "/schedule", label: "Schedule",
        aliases: ["Calendar", "Bookings"] },
      { to: "/customers", label: "Customers" },
    ] },
  ],
}));


// Import AFTER mocks so the module picks them up.
import { PageHeader } from "@/components/layout/PageHeader";


beforeEach(() => {
  navigateSpy.mockReset();
  searchGlobalSpy.mockReset();
  // Default: empty groups so existing synchronous tests don't
  // accidentally observe backend-driven rows.
  searchGlobalSpy.mockResolvedValue({ customers: [], documents: [] });
});
afterEach(() => {
  cleanup();
});


// Helpers ────────────────────────────────────────────────────────
function _input() {
  return screen.getByTestId("page-header-search-input");
}


describe("PageHeader · title + subtitle + actions", () => {
  it("renders the title prop as an <h1>", () => {
    render(<PageHeader title="Invoices" />);
    const h1 = screen.getByTestId("page-header-title");
    expect(h1.tagName.toLowerCase()).toBe("h1");
    expect(h1.textContent).toBe("Invoices");
  });

  it("renders subtitle when provided, omits it otherwise", () => {
    const { rerender } = render(
      <PageHeader title="Invoices" subtitle="All customer bills" />,
    );
    expect(screen.getByTestId("page-header-subtitle").textContent).toBe(
      "All customer bills",
    );
    rerender(<PageHeader title="Invoices" />);
    expect(screen.queryByTestId("page-header-subtitle")).toBeNull();
  });

  it("renders actions slot on the right when provided", () => {
    render(
      <PageHeader
        title="Invoices"
        actions={<button data-testid="fake-action">+ New</button>}
      />,
    );
    expect(screen.getByTestId("page-header-actions")).toBeTruthy();
    expect(screen.getByTestId("fake-action").textContent).toBe("+ New");
  });
});


describe("PageHeader · search input rendering + design tokens", () => {
  it("renders the exact placeholder copy from the spec", () => {
    render(<PageHeader title="Invoices" />);
    const input = _input();
    expect(input.getAttribute("placeholder")).toBe(
      "Jump to page... (e.g., PDF Upload, Invoices, Fuel Tracking)",
    );
  });

  it("search input wrapper is borderless (Global Command Bar spec)", () => {
    // N2' flip · the input was ``1px solid colors.inputBorder``
    // pre-flip; the Global Command Bar spec calls for a flat
    // white pill on the blue hero, so the input must render with
    // no border.  React strips ``border: "none"`` from the
    // rendered ``style`` attribute (verified: no ``border`` prop
    // survives the style-object serializer) and jsdom's
    // ``getComputedStyle`` returns ``""`` for border-related
    // props with no explicit value.  Both signals are equally
    // authoritative "no painted border" states.
    render(<PageHeader title="Invoices" />);
    const wrap = screen.getByTestId("page-header-search-input-wrap");
    const cs = window.getComputedStyle(wrap);
    const inline = wrap.getAttribute("style") || "";
    // Positive signal · nothing paints a visible border.
    const noStyle = (
      cs.borderStyle === "" || cs.borderStyle === "none"
    );
    const noWidth = (
      cs.borderWidth === "" || cs.borderWidth === "0px"
      || cs.borderWidth === "0"
    );
    expect(noStyle).toBe(true);
    expect(noWidth).toBe(true);
    // Negative signal · the pre-flip 1px blue border is gone.
    expect(inline).not.toMatch(/border-width:\s*1/);
    expect(inline).not.toMatch(/border-color:\s*(?:rgb\(59,\s*130,\s*246\)|#3B82F6)/i);
  });

  it("search band paints colors.inputBorder as background (blue hero)", () => {
    render(<PageHeader title="Invoices" />);
    const band = screen.getByTestId("page-header-search-band");
    const bg = window.getComputedStyle(band).backgroundColor;
    // #3B82F6 == rgb(59, 130, 246) · Global Command Bar blue.
    expect(
      bg === "#3B82F6" || bg === "rgb(59, 130, 246)",
    ).toBe(true);
  });

  it("search icon paints colors.nav.bg (navy on the white input)", () => {
    render(<PageHeader title="Invoices" />);
    const icon = screen.getByTestId("page-header-search-icon");
    const c = window.getComputedStyle(icon).color;
    // #1B1F5C == rgb(27, 31, 92) · navy.
    expect(
      c === "#1B1F5C" || c === "rgb(27, 31, 92)",
    ).toBe(true);
  });

  it("search input container is horizontally centered inside the hero", () => {
    // The direct child of the ``page-header-search-band`` is the
    // width-clamped container.  It must be centered — either
    // ``margin: 0 auto`` (auto margins on left AND right) or the
    // parent band uses flex ``justifyContent: center``.
    render(<PageHeader title="Invoices" />);
    const band = screen.getByTestId("page-header-search-band");
    const container = band.querySelector('[data-testid="page-header-search-input-wrap"]')
      .parentElement;
    const cs = window.getComputedStyle(container);
    const bandCs = window.getComputedStyle(band);
    const centeredViaMargin = (
      cs.marginLeft === "auto" && cs.marginRight === "auto"
    );
    const centeredViaFlex = (
      bandCs.display === "flex" && bandCs.justifyContent === "center"
    );
    expect(centeredViaMargin || centeredViaFlex).toBe(true);
    // Width is clamped so ``margin: 0 auto`` actually shifts the
    // container off the edge.  640px matches the spec.
    expect(cs.maxWidth).toBe("640px");
  });

  it("renders the ⌘K / Ctrl+K keyboard hint on the right", () => {
    render(<PageHeader title="Invoices" />);
    const hint = screen.getByTestId("page-header-search-kbd-hint");
    // Hint text should be one of the two, depending on platform
    // detection.  Both forms are acceptable — the platform is
    // jsdom-dependent, not a spec issue.
    expect(["\u2318K", "Ctrl+K"]).toContain(hint.textContent);
  });
});


describe("PageHeader · inline dropdown behavior", () => {
  it("empty input keeps the dropdown hidden", () => {
    render(<PageHeader title="Invoices" />);
    expect(screen.queryByTestId("page-header-search-dropdown")).toBeNull();
  });

  it("typing 'invoi' surfaces Invoices as the first row", () => {
    render(<PageHeader title="Invoices" />);
    fireEvent.change(_input(), { target: { value: "invoi" } });
    const dropdown = screen.getByTestId("page-header-search-dropdown");
    expect(dropdown).toBeTruthy();
    const first = screen.getByTestId("page-header-search-result-0");
    expect(first.textContent).toContain("Invoices");
    expect(first.textContent).toContain("/invoices");
  });

  it("↓ + Enter navigates to the highlighted row", () => {
    render(<PageHeader title="Invoices" />);
    fireEvent.change(_input(), { target: { value: "invoi" } });
    // Highlight defaults to 0 → Invoices. Enter commits immediately.
    fireEvent.keyDown(_input(), { key: "Enter" });
    expect(navigateSpy).toHaveBeenCalledTimes(1);
    expect(navigateSpy).toHaveBeenCalledWith("/invoices");
  });

  it("↓ moves highlight to the next result before Enter fires", () => {
    render(<PageHeader title="Invoices" />);
    // Query "s" — many matches; second visible result should be
    // a different path than the first.
    fireEvent.change(_input(), { target: { value: "s" } });
    const first = screen.getByTestId("page-header-search-result-0");
    const second = screen.queryByTestId("page-header-search-result-1");
    expect(second).not.toBeNull();
    fireEvent.keyDown(_input(), { key: "ArrowDown" });
    fireEvent.keyDown(_input(), { key: "Enter" });
    expect(navigateSpy).toHaveBeenCalledTimes(1);
    // Whatever the second-ranked row's path is, that's what we
    // committed — not the first.
    expect(navigateSpy.mock.calls[0][0]).not.toBe(
      // Extract path from the first row's rendered text.
      first.textContent.match(/(\/[\w\-/]+)$/)?.[1],
    );
  });

  it("alias match · 'pdf upload' surfaces PDF Import", () => {
    render(<PageHeader title="Invoices" />);
    fireEvent.change(_input(), { target: { value: "pdf upload" } });
    const first = screen.getByTestId("page-header-search-result-0");
    expect(first.textContent).toContain("PDF Import");
    expect(first.textContent).toContain("/admin/imports/pdf-invoice");
  });

  it("Esc clears the input and hides the dropdown", () => {
    render(<PageHeader title="Invoices" />);
    fireEvent.change(_input(), { target: { value: "invoi" } });
    expect(screen.getByTestId("page-header-search-dropdown")).toBeTruthy();
    fireEvent.keyDown(_input(), { key: "Escape" });
    expect(_input().value).toBe("");
    expect(screen.queryByTestId("page-header-search-dropdown")).toBeNull();
    // Esc must NOT trigger a navigation.
    expect(navigateSpy).not.toHaveBeenCalled();
  });

  it("clicking a result commits the navigation", () => {
    render(<PageHeader title="Invoices" />);
    fireEvent.change(_input(), { target: { value: "invoi" } });
    fireEvent.mouseDown(screen.getByTestId("page-header-search-result-0"));
    expect(navigateSpy).toHaveBeenCalledTimes(1);
    expect(navigateSpy).toHaveBeenCalledWith("/invoices");
  });
});


// ─────────────────────────────────────────────────────────────
// N4' · Grouped dropdown + debounced backend search
// ─────────────────────────────────────────────────────────────
import { act, waitFor } from "@testing-library/react";


describe("PageHeader · N4' grouped dropdown", () => {
  it("renders the three-section grouped shell when all groups populate", async () => {
    searchGlobalSpy.mockResolvedValue({
      customers: [
        { id: "c-1", name: "Smith Residence",
          address_line1: "123 Main St", city: "Austin",
          postal_code: "78701", match_field: "name" },
      ],
      documents: [
        { type: "invoice", id: "inv-1", display_id: "INV-2026-000048",
          title: "Weekly service", match_field: "number" },
        { type: "job", id: "job-1", display_id: "J-ab88fb26",
          title: "Pool Installation", match_field: "title" },
      ],
    });
    render(<PageHeader title="Invoices" />);
    // ``customer`` hits the Customers nav row (title match) + the
    // seeded backend customer/document rows all populate. All three
    // group headers must render.
    fireEvent.change(_input(), { target: { value: "customer" } });
    await waitFor(() => {
      expect(screen.queryByTestId("page-header-section-customer")).toBeTruthy();
    });
    expect(screen.getByTestId("page-header-section-page")).toBeTruthy();
    expect(screen.getByTestId("page-header-section-customer")).toBeTruthy();
    expect(screen.getByTestId("page-header-section-document")).toBeTruthy();
    // Count badges reflect the group sizes.
    expect(screen.getByTestId("page-header-section-count-customer").textContent).toBe("1");
    expect(screen.getByTestId("page-header-section-count-document").textContent).toBe("2");
  });

  it("customer row shows name and address subline", async () => {
    searchGlobalSpy.mockResolvedValue({
      customers: [
        { id: "c-42", name: "Smith Residence",
          address_line1: "123 Main St", city: "Austin",
          postal_code: "78701", match_field: "name" },
      ],
      documents: [],
    });
    render(<PageHeader title="Customers" />);
    fireEvent.change(_input(), { target: { value: "smith" } });
    await waitFor(() => {
      expect(screen.queryByTestId("page-header-section-customer")).toBeTruthy();
    });
    // The pages group is empty for "smith", so the customer row
    // is flat-index 0.
    const row = screen.getByTestId("customer-address-0");
    expect(row.textContent).toContain("123 Main St");
    expect(row.textContent).toContain("Austin");
    expect(row.textContent).toContain("78701");
  });

  it("document row shows type badge, display_id, and title", async () => {
    searchGlobalSpy.mockResolvedValue({
      customers: [],
      documents: [
        { type: "invoice", id: "inv-99", display_id: "INV-2026-000099",
          title: "Backup pump repair", match_field: "number" },
      ],
    });
    render(<PageHeader title="Docs" />);
    fireEvent.change(_input(), { target: { value: "backup" } });
    await waitFor(() => {
      expect(screen.queryByTestId("page-header-section-document")).toBeTruthy();
    });
    const badge = screen.getByTestId("doc-badge-0");
    expect(badge.textContent).toBe("Invoice");
    const row = screen.getByTestId("page-header-search-result-0");
    expect(row.textContent).toContain("INV-2026-000099");
    expect(row.textContent).toContain("Backup pump repair");
  });

  it("empty state renders when q >= 2 and every group is empty", async () => {
    searchGlobalSpy.mockResolvedValue({ customers: [], documents: [] });
    render(<PageHeader title="Search" />);
    // ``zzz`` has no nav matches AND no backend matches.
    fireEvent.change(_input(), { target: { value: "zzz" } });
    await waitFor(() => {
      expect(screen.queryByTestId("page-header-empty-state")).toBeTruthy();
    });
    expect(screen.getByTestId("page-header-empty-state").textContent)
      .toContain("zzz");
  });

  it("1-char query does not fire the backend", async () => {
    render(<PageHeader title="Search" />);
    fireEvent.change(_input(), { target: { value: "s" } });
    // Give the debounce timer more than enough time to fire.
    await new Promise((r) => setTimeout(r, 400));
    expect(searchGlobalSpy).not.toHaveBeenCalled();
  });

  it("keyboard ↓↓↓ traverses across groups (pages → customers → documents)", async () => {
    searchGlobalSpy.mockResolvedValue({
      customers: [
        { id: "c-1", name: "Smith Residence", match_field: "name" },
      ],
      documents: [
        { type: "invoice", id: "inv-1", display_id: "INV-1", title: "t",
          match_field: "number" },
      ],
    });
    render(<PageHeader title="X" />);
    fireEvent.change(_input(), { target: { value: "invoi" } });
    // Wait for the backend to populate customers + documents.
    await waitFor(() => {
      expect(screen.queryByTestId("page-header-section-document")).toBeTruthy();
    });
    // navIndex mock returns Invoices for "invoi" → 1 page row.
    // + 1 customer + 1 document = 3 flat rows.
    // ↓ moves to index 1 (customer), ↓ moves to index 2 (document).
    fireEvent.keyDown(_input(), { key: "ArrowDown" });
    fireEvent.keyDown(_input(), { key: "ArrowDown" });
    fireEvent.keyDown(_input(), { key: "Enter" });
    expect(navigateSpy).toHaveBeenCalledTimes(1);
    expect(navigateSpy).toHaveBeenCalledWith("/invoices/inv-1");
  });

  it("Enter on customer row navigates to /customers/:id", async () => {
    searchGlobalSpy.mockResolvedValue({
      customers: [
        { id: "cust-777", name: "Test Customer", match_field: "name" },
      ],
      documents: [],
    });
    render(<PageHeader title="X" />);
    // Use a query with no page matches so the customer is at flat idx 0.
    fireEvent.change(_input(), { target: { value: "test-customer" } });
    await waitFor(() => {
      expect(screen.queryByTestId("page-header-section-customer")).toBeTruthy();
    });
    fireEvent.keyDown(_input(), { key: "Enter" });
    expect(navigateSpy).toHaveBeenCalledWith("/customers/cust-777");
  });

  it("Enter on job row navigates to /jobs/:id", async () => {
    searchGlobalSpy.mockResolvedValue({
      customers: [],
      documents: [
        { type: "job", id: "job-321", display_id: "J-abcd1234",
          title: "Deep clean", match_field: "id" },
      ],
    });
    render(<PageHeader title="X" />);
    fireEvent.change(_input(), { target: { value: "deep-clean-query" } });
    await waitFor(() => {
      expect(screen.queryByTestId("page-header-section-document")).toBeTruthy();
    });
    fireEvent.keyDown(_input(), { key: "Enter" });
    expect(navigateSpy).toHaveBeenCalledWith("/jobs/job-321");
  });

  it("Enter on invoice row navigates to /invoices/:id", async () => {
    searchGlobalSpy.mockResolvedValue({
      customers: [],
      documents: [
        { type: "invoice", id: "inv-555", display_id: "INV-2026-000555",
          title: "Feb", match_field: "number" },
      ],
    });
    render(<PageHeader title="X" />);
    fireEvent.change(_input(), { target: { value: "feb-invoice-q" } });
    await waitFor(() => {
      expect(screen.queryByTestId("page-header-section-document")).toBeTruthy();
    });
    fireEvent.keyDown(_input(), { key: "Enter" });
    expect(navigateSpy).toHaveBeenCalledWith("/invoices/inv-555");
  });

  it("preserves prior results when the backend errors", async () => {
    // First keystroke → success, rows land.
    searchGlobalSpy.mockResolvedValueOnce({
      customers: [
        { id: "c-preserve", name: "Alpha", match_field: "name" },
      ],
      documents: [],
    });
    render(<PageHeader title="X" />);
    fireEvent.change(_input(), { target: { value: "alpha" } });
    await waitFor(() => {
      expect(screen.queryByTestId("page-header-section-customer")).toBeTruthy();
    });
    // Second keystroke → backend fails; the customer row must
    // NOT disappear from the dropdown.
    searchGlobalSpy.mockRejectedValueOnce(new Error("500 backend"));
    fireEvent.change(_input(), { target: { value: "alphaa" } });
    // Wait long enough for the debounced fetch to settle.
    await new Promise((r) => setTimeout(r, 450));
    // Customer row is still present.
    expect(screen.queryByTestId("page-header-section-customer")).toBeTruthy();
  });
});
