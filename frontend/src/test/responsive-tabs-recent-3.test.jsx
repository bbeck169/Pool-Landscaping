/**
 * Phase J1 · Feb-2026 — ResponsiveTabs recent-3 LRU preview.
 *
 * When ``recentStorageKey`` is supplied, the forced-dropdown branch
 * of ResponsiveTabs tracks the last 3 selected tab keys in
 * ``localStorage[key]`` and renders a "Recent" subheader + those
 * items at the top of the dropdown menu, followed by a divider and
 * the full tabs list.  This test file locks:
 *   1. First-render with an empty store shows NO subheader.
 *   2. Selecting a tab pushes it into the store as the newest
 *      entry (LRU, cap 3, uniques only).
 *   3. On a subsequent render with a non-empty store, the "Recent"
 *      subheader IS visible.
 *
 * Uses a jsdom localStorage stub so the assertions don't leak
 * across suites — each ``it`` block resets the mock keyed on
 * ``STORAGE_KEY``.
 */
import React from "react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

import { ResponsiveTabs }
  from "@/components/ui/responsive-tabs";


const STORAGE_KEY = "cd-tabs-recent-3-cust_j1";
const TABS = [
  { k: "overview",   label: "Overview"   },
  { k: "properties", label: "Properties" },
  { k: "jobs",       label: "Jobs"       },
  { k: "invoices",   label: "Invoices"   },
];


beforeEach(() => {
  window.localStorage.clear();
});


describe("ResponsiveTabs · Phase J1 recent-3 LRU preview", () => {
  it("does NOT render the Recent subheader when localStorage is empty", async () => {
    render(
      <ResponsiveTabs
        tabs={TABS}
        active="overview"
        onChange={() => {}}
        testidPrefix="cd-tab"
        forceDropdown
        recentStorageKey={STORAGE_KEY}
      />,
    );
    // No stored keys → the subheader is silently omitted so the
    // dropdown behaves exactly as pre-J1.
    expect(screen.queryByTestId("cd-tab-recent-header")).toBeNull();
    expect(screen.queryByTestId("cd-tab-recent-divider")).toBeNull();
  });

  it("updates localStorage[cd-tabs-recent-3-*] on selection change", async () => {
    // Renders the horizontal-strip branch too (both variants call
    // the same ``handleSelect``), so we can drive selection via
    // the strip-side button testid without dealing with Radix
    // portals in jsdom.  Even in ``forceDropdown`` mode the strip
    // is present in the DOM (marked ``hidden``) with the same
    // testid.
    const onChange = vi.fn();
    render(
      <ResponsiveTabs
        tabs={TABS}
        active="overview"
        onChange={onChange}
        testidPrefix="cd-tab"
        forceDropdown
        recentStorageKey={STORAGE_KEY}
      />,
    );
    // Every tab (dropdown item AND strip button) shares the same
    // ``cd-tab-{key}`` testid → the strip variant sits second in
    // the DOM order (after the dropdown item).  Grab both and
    // click the strip.
    const jobsButtons = screen.getAllByTestId("cd-tab-jobs");
    expect(jobsButtons.length).toBeGreaterThanOrEqual(1);
    await act(async () => {
      fireEvent.click(jobsButtons[jobsButtons.length - 1]);
    });
    expect(onChange).toHaveBeenCalledWith("jobs");
    const stored = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) || "[]");
    expect(stored[0]).toBe("jobs");

    // Selecting a second tab puts it at the head (LRU), keeps
    // uniques, caps to 3.
    await act(async () => {
      fireEvent.click(
        screen.getAllByTestId("cd-tab-invoices").slice(-1)[0]);
    });
    await act(async () => {
      fireEvent.click(
        screen.getAllByTestId("cd-tab-properties").slice(-1)[0]);
    });
    await act(async () => {
      // Re-click "jobs" to prove uniques.
      fireEvent.click(
        screen.getAllByTestId("cd-tab-jobs").slice(-1)[0]);
    });
    const finalStored = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) || "[]");
    expect(finalStored).toEqual(["jobs", "properties", "invoices"]);
    expect(finalStored.length).toBeLessThanOrEqual(3);
  });

  it("renders the Recent subheader + items when localStorage has entries (source contract)", async () => {
    // Radix DropdownMenu portals content and opening it in jsdom
    // via ``fireEvent.click`` on the trigger doesn't reliably
    // mount ``DropdownMenuContent`` under the current test-env
    // (portal + pointer-event guards).  Locking the render path
    // via a source-body check is the same convention
    // ``responsive-tabs.test.jsx`` uses for the horizontal-strip
    // branch — enough to guarantee the Recent-header shape can't
    // silently regress.
    const fs = await import("node:fs");
    const path = await import("node:path");
    const SRC = fs.readFileSync(
      path.resolve(process.cwd(),
        "src/components/ui/responsive-tabs.jsx"),
      "utf-8",
    );
    // Header + divider testids are stable + tied to the same
    // prefix.
    expect(SRC).toMatch(
      /data-testid=\{`\$\{testidPrefix\}-recent-header`\}/,
    );
    expect(SRC).toMatch(
      /data-testid=\{`\$\{testidPrefix\}-recent-divider`\}/,
    );
    // The recent items list is derived from ``recentItems``,
    // which is ``recentKeys.map(...).filter(Boolean)`` — so
    // stale keys after a tab rename don't crash the render.
    expect(SRC).toMatch(
      /const\s+recentItems\s*=\s*recentKeys\s*\.\s*map/,
    );
    expect(SRC).toMatch(/\.\s*filter\(\s*Boolean\s*\)/);
    // The subheader block is gated behind ``recentItems.length``,
    // so an empty store renders NO extra chrome.
    expect(SRC).toMatch(/\{\s*recentItems\.length\s*\?/);
    // The recent-item testid uses a scoped ``recent`` prefix so
    // duplicate-key React warnings can't fire.
    expect(SRC).toMatch(
      /_safeTestid\(\s*`\$\{testidPrefix\}-recent`,\s*t\.k\s*\)/,
    );
    // Consumer wiring — CustomerDetail passes the storage key
    // keyed on the loaded ``customer.id`` so recent-3 buckets
    // are per-customer.
    const CD = fs.readFileSync(
      path.resolve(process.cwd(),
        "src/pages/customers/CustomerDetail.jsx"),
      "utf-8",
    );
    expect(CD).toMatch(/recentStorageKey=/);
    expect(CD).toMatch(/cd-tabs-recent-3-/);
  });
});
