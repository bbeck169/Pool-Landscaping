/**
 * Task E · Feb-2026 · Commit 8a — Shared NavyFilterBar primitive
 * coverage.
 *
 * Covers every sub-primitive:
 *   • NavyFilterBar root — container renders w/ K52.1 marker,
 *     navy bg, and forwards ...rest data attrs.
 *   • .Search — solid-white card + permanent blue border + navy
 *     text; testid pass-through; onChange forwards raw string;
 *     onClear renders the X button w/ derived OR explicit
 *     clearTestid.
 *   • .Select — navy bg + white text; testid pass-through;
 *     onChange forwards option value; optional label renders
 *     10-px uppercase caption.
 *   • .Chip — gradient-active / white-outline-idle patterns;
 *     testid pass-through; active toggles.
 *   • .DatePicker — type="date" w/ optional label; testid pass-
 *     through; onChange forwards ISO date string.
 *   • .Combobox — passthrough shell renders children w/ optional
 *     label; child's own testid preserved.
 *   • Compound composition — mixed children render side-by-side
 *     without style bleed.
 *
 * NOTE — Cross-page symmetry (all 6 migrated filter bars carry
 * their K52.1 marker + full testid roster + unique page-scoped
 * root testid) lives in ``task-e-cross-page-symmetry.test.jsx``
 * as a source-body scan (no jsdom, no per-page mocks needed).
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import NavyFilterBar from "@/components/ui/NavyFilterBar";


describe("NavyFilterBar · root container", () => {
  it("renders children inside a navy-painted strip and forwards ...rest data attrs", () => {
    render(
      <NavyFilterBar data-testid="e-root" data-k52-navy-strip="true">
        <div data-testid="e-child">hi</div>
      </NavyFilterBar>
    );
    const strip = screen.getByTestId("e-root");
    expect(strip).toHaveAttribute("data-navy-filter-bar", "true");
    expect(strip).toHaveAttribute("data-k52-navy-strip", "true");
    // Navy paint applied inline.
    expect(strip.style.backgroundColor).toBeTruthy();
    // Children render inside.
    expect(screen.getByTestId("e-child")).toBeTruthy();
  });

  it("propagates custom className alongside the base flex/rounded classes", () => {
    render(
      <NavyFilterBar data-testid="e-root" className="mt-8">
        <span data-testid="e-child" />
      </NavyFilterBar>
    );
    const strip = screen.getByTestId("e-root");
    expect(strip.className).toMatch(/rounded-2xl/);
    expect(strip.className).toMatch(/flex-wrap/);
    expect(strip.className).toMatch(/mt-8/);
  });
});


describe("NavyFilterBar.Search", () => {
  it("renders a solid-white card w/ permanent #3B82F6 border and navy text", () => {
    const onChange = vi.fn();
    render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Search
          value=""
          onChange={onChange}
          placeholder="Search…"
          data-testid="e-search"
        />
      </NavyFilterBar>
    );
    const input = screen.getByTestId("e-search");
    // Solid-white bg (colors.surface) + navy foreground
    // (colors.nav.bg) — permanent-border color set via inline
    // style. Assert the style attrs exist rather than pinning
    // exact hex to remain resilient to token renames.
    expect(input.style.backgroundColor).toBeTruthy();
    expect(input.style.border).toMatch(/#3B82F6|rgb\(59, 130, 246\)/i);
    expect(input.style.color).toBeTruthy();
    expect(input.getAttribute("placeholder")).toBe("Search…");
  });

  it("forwards the raw string on onChange (no coercion)", () => {
    const onChange = vi.fn();
    render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Search
          value=""
          onChange={onChange}
          data-testid="e-search"
        />
      </NavyFilterBar>
    );
    fireEvent.change(screen.getByTestId("e-search"), { target: { value: "hello" } });
    expect(onChange).toHaveBeenCalledWith("hello");
  });

  it("renders the Clear button w/ derived {data-testid}-clear when onClear is passed", () => {
    const onChange = vi.fn();
    const onClear = vi.fn();
    render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Search
          value="q"
          onChange={onChange}
          onClear={onClear}
          data-testid="e-search"
        />
      </NavyFilterBar>
    );
    const clearBtn = screen.getByTestId("e-search-clear");
    fireEvent.click(clearBtn);
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("honours the explicit clearTestid override (RecurringJobs shape)", () => {
    const onChange = vi.fn();
    const onClear = vi.fn();
    render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Search
          value="q"
          onChange={onChange}
          onClear={onClear}
          data-testid="recurring-search-input"
          clearTestid="recurring-search-clear"
        />
      </NavyFilterBar>
    );
    // Explicit override wins over the derived pattern.
    expect(screen.getByTestId("recurring-search-clear")).toBeTruthy();
    expect(screen.queryByTestId("recurring-search-input-clear")).toBeNull();
  });

  it("omits the Clear button when value is empty", () => {
    const onChange = vi.fn();
    const onClear = vi.fn();
    render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Search
          value=""
          onChange={onChange}
          onClear={onClear}
          data-testid="e-search"
        />
      </NavyFilterBar>
    );
    expect(screen.queryByTestId("e-search-clear")).toBeNull();
  });
});


describe("NavyFilterBar.Select", () => {
  it("renders navy bg + white text and forwards data-testid onto the <select>", () => {
    const onChange = vi.fn();
    render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Select
          value="all"
          onChange={onChange}
          data-testid="e-status"
        >
          <option value="all">All</option>
          <option value="open">Open</option>
        </NavyFilterBar.Select>
      </NavyFilterBar>
    );
    const select = screen.getByTestId("e-status");
    expect(select.tagName).toBe("SELECT");
    expect(select.style.backgroundColor).toBeTruthy();
    expect(select.style.color).toBeTruthy();
  });

  it("forwards the option value on onChange (no wrapping event)", () => {
    const onChange = vi.fn();
    render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Select
          value="all"
          onChange={onChange}
          data-testid="e-status"
        >
          <option value="all">All</option>
          <option value="open">Open</option>
        </NavyFilterBar.Select>
      </NavyFilterBar>
    );
    fireEvent.change(screen.getByTestId("e-status"), { target: { value: "open" } });
    expect(onChange).toHaveBeenCalledWith("open");
  });

  it("renders the optional label as a 10-px uppercase caption above the control", () => {
    render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Select
          value=""
          onChange={() => {}}
          label="Technician"
          data-testid="e-tech"
        >
          <option value="">All</option>
        </NavyFilterBar.Select>
      </NavyFilterBar>
    );
    const label = screen.getByText("Technician");
    expect(label.tagName).toBe("LABEL");
    expect(label.className).toMatch(/text-\[10px\]/);
    expect(label.className).toMatch(/uppercase/);
    expect(label.className).toMatch(/font-bold/);
  });
});


describe("NavyFilterBar.Chip", () => {
  it("paints gradient background when active and transparent when idle", () => {
    const onClick = vi.fn();
    const { rerender } = render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Chip
          active={false}
          onClick={onClick}
          data-testid="e-chip"
        >
          Toggle
        </NavyFilterBar.Chip>
      </NavyFilterBar>
    );
    const idle = screen.getByTestId("e-chip");
    // Idle: transparent bg (or empty style.background — either way NOT the gradient).
    expect(idle.style.background === "" || idle.style.background === "transparent").toBe(true);
    // Toggle → active state should paint the gradient inline.
    rerender(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Chip
          active={true}
          onClick={onClick}
          data-testid="e-chip"
        >
          Toggle
        </NavyFilterBar.Chip>
      </NavyFilterBar>
    );
    const active = screen.getByTestId("e-chip");
    // JSDOM returns computed style.background as a linear-gradient
    // when active is true.
    expect(active.style.background).toMatch(/gradient|linear/i);
  });

  it("forwards clicks to onClick", () => {
    const onClick = vi.fn();
    render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Chip
          active={false}
          onClick={onClick}
          data-testid="e-chip"
        >
          Toggle
        </NavyFilterBar.Chip>
      </NavyFilterBar>
    );
    fireEvent.click(screen.getByTestId("e-chip"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("sets aria-pressed to match the active prop", () => {
    const { rerender } = render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Chip
          active={false}
          onClick={() => {}}
          data-testid="e-chip"
        >
          Toggle
        </NavyFilterBar.Chip>
      </NavyFilterBar>
    );
    expect(screen.getByTestId("e-chip").getAttribute("aria-pressed")).toBe("false");
    rerender(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Chip
          active={true}
          onClick={() => {}}
          data-testid="e-chip"
        >
          Toggle
        </NavyFilterBar.Chip>
      </NavyFilterBar>
    );
    expect(screen.getByTestId("e-chip").getAttribute("aria-pressed")).toBe("true");
  });
});


describe("NavyFilterBar.DatePicker", () => {
  it("renders type=\"date\" w/ navy bg and forwards ISO date on onChange", () => {
    const onChange = vi.fn();
    render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.DatePicker
          value=""
          onChange={onChange}
          label="Since"
          data-testid="e-date"
        />
      </NavyFilterBar>
    );
    const input = screen.getByTestId("e-date");
    expect(input.getAttribute("type")).toBe("date");
    // Label renders above.
    expect(screen.getByText("Since").tagName).toBe("LABEL");
    fireEvent.change(input, { target: { value: "2026-01-15" } });
    expect(onChange).toHaveBeenCalledWith("2026-01-15");
  });
});


describe("NavyFilterBar.Combobox", () => {
  it("passthrough — renders children unchanged with optional label", () => {
    render(
      <NavyFilterBar data-testid="e-root">
        <NavyFilterBar.Combobox label="Customer" minWidth={200}>
          <button data-testid="e-inner-combobox">All customers</button>
        </NavyFilterBar.Combobox>
      </NavyFilterBar>
    );
    // Child's own testid preserved.
    expect(screen.getByTestId("e-inner-combobox")).toBeTruthy();
    // Label renders above.
    const label = screen.getByText("Customer");
    expect(label.tagName).toBe("LABEL");
  });
});


describe("NavyFilterBar · compound composition", () => {
  it("renders a mixed strip with .Search + .Select + .Chip + raw children side-by-side", () => {
    render(
      <NavyFilterBar data-testid="e-root" data-k52-navy-strip="true">
        <NavyFilterBar.Search
          value=""
          onChange={() => {}}
          data-testid="e-search"
        />
        <NavyFilterBar.Select
          value=""
          onChange={() => {}}
          data-testid="e-status"
        >
          <option value="">All</option>
        </NavyFilterBar.Select>
        <NavyFilterBar.Chip
          active={false}
          onClick={() => {}}
          data-testid="e-chip"
        >
          Toggle
        </NavyFilterBar.Chip>
        {/* Raw child stays raw — matches Customers' Missing-card
            + More-filters pattern and Invoices' Has-declined-
            items + Category cluster pattern. */}
        <button data-testid="e-raw">Raw</button>
      </NavyFilterBar>
    );
    // All 4 children resolve.
    expect(screen.getByTestId("e-search")).toBeTruthy();
    expect(screen.getByTestId("e-status")).toBeTruthy();
    expect(screen.getByTestId("e-chip")).toBeTruthy();
    expect(screen.getByTestId("e-raw")).toBeTruthy();
    // K52.1 marker still attached to the container.
    expect(screen.getByTestId("e-root")).toHaveAttribute(
      "data-k52-navy-strip",
      "true",
    );
  });
});
