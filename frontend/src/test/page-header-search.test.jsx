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

// Mock react-router-dom's ``useNavigate``.
vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateSpy,
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
        aliases: ["PDF Upload", "Bulk Import", "Upload Invoices"] },
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

  it("search input wrapper carries colors.inputBorder as borderColor", () => {
    render(<PageHeader title="Invoices" />);
    const wrap = screen.getByTestId("page-header-search-input-wrap");
    const bc = window.getComputedStyle(wrap).borderColor;
    // Accept both hex-parsed and rgb-normalized forms.
    // #3B82F6 == rgb(59, 130, 246).
    expect(
      bc === "#3B82F6" || bc === "rgb(59, 130, 246)",
    ).toBe(true);
  });

  it("search band paints colors.nav.bg as background", () => {
    render(<PageHeader title="Invoices" />);
    const band = screen.getByTestId("page-header-search-band");
    const bg = window.getComputedStyle(band).backgroundColor;
    // #1B1F5C == rgb(27, 31, 92).
    expect(
      bg === "#1B1F5C" || bg === "rgb(27, 31, 92)",
    ).toBe(true);
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
