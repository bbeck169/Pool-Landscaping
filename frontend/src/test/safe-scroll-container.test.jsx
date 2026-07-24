/**
 * Feb-2026 · SafeScrollContainer smoke tests.
 *
 * Guards the base defaults against a regression that quietly re-adds
 * ``overflow: hidden`` or ``h-screen`` to the wrapper — either would
 * silently re-introduce the scroll-trap on every page that adopts
 * the convention.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import SafeScrollContainer from "@/components/layout/SafeScrollContainer";
import { assertNoScrollTrap } from "@/test/helpers/assertNoScrollTrap";


describe("SafeScrollContainer", () => {
  it("renders a div by default carrying the safe base classes", () => {
    render(
      <SafeScrollContainer data-testid="ssc-1">hi</SafeScrollContainer>,
    );
    const el = screen.getByTestId("ssc-1");
    expect(el.tagName).toBe("DIV");
    expect(el.className).toMatch(/\bmin-h-screen\b/);
    expect(el.className).toMatch(/\bw-full\b/);
    expect(el.className).toMatch(/\bpb-24\b/);
    assertNoScrollTrap(el);
  });

  it("respects the `as` prop for semantic tags", () => {
    render(
      <SafeScrollContainer as="main" data-testid="ssc-2">
        content
      </SafeScrollContainer>,
    );
    const el = screen.getByTestId("ssc-2");
    expect(el.tagName).toBe("MAIN");
    assertNoScrollTrap(el);
  });

  it("appends caller className while still passing the scroll-trap guard", () => {
    render(
      <SafeScrollContainer className="p-4 md:p-6 space-y-4" data-testid="ssc-3">
        body
      </SafeScrollContainer>,
    );
    const el = screen.getByTestId("ssc-3");
    expect(el.className).toMatch(/\bp-4\b/);
    expect(el.className).toMatch(/\bspace-y-4\b/);
    // Still safe.
    assertNoScrollTrap(el);
  });

  it("assertNoScrollTrap fails hard when a page-author re-adds overflow-hidden", () => {
    render(
      <div data-testid="ssc-bad" className="min-h-screen overflow-hidden">
        oops
      </div>,
    );
    const bad = screen.getByTestId("ssc-bad");
    let threw = false;
    try { assertNoScrollTrap(bad); } catch { threw = true; }
    expect(threw).toBe(true);
  });
});
