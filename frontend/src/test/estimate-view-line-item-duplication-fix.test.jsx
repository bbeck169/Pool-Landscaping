/**
 * Feb-2026 · Public estimate viewer — line-item duplication
 * regression guard.
 *
 * Root cause of the customer-facing bug: ``.ev-lines-cards``
 * (in ``EstimateView.css``) unconditionally declared
 * ``display: flex``, which won specificity ties against
 * Tailwind's ``.sm\:hidden { display: none }`` and rendered
 * the mobile card list alongside the desktop table on ≥640px
 * viewports. See ``FIX_ESTIMATE_VIEW_LINE_ITEM_DUPLICATION.md``.
 *
 * This test locks the invariant at the JSDOM layer: on a payload
 * with N line items, exactly N desktop rows AND N mobile cards
 * render (the CSS gate is what hides them at runtime; the DOM
 * itself always mounts both branches). More importantly — the
 * ``.ev-lines-cards`` selector no longer carries an
 * unconditional ``display`` declaration in the CSS source, so a
 * future edit that resurrects the bug cannot land silently.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({
  api: { get: vi.fn(() => Promise.resolve(null)),
             post: vi.fn(() => Promise.resolve(null)),
             patch: vi.fn(() => Promise.resolve(null)),
             put: vi.fn(() => Promise.resolve(null)),
             del: vi.fn(() => Promise.resolve(null)) },
}));
vi.mock("sonner", () => ({
  Toaster: () => null,
  toast:   { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import EstimateView from "@/components/EstimateView";
import { api } from "@/api";


function _payload() {
  return {
    company:          { name: "Aqua Terra" },
    bill_to:          { name: "Jane Customer" },
    property_address: "123 Main St",
    header: {
      doc_type:      "estimate",
      number:        "EST-42",
      customer_name: "Jane Customer",
    },
    line_items: Array.from({ length: 7 }, (_, i) => ({
      description: `Widget ${i + 1}`,
      qty_hr:      i + 1,
      visits:      1,
      total:       100 + i,
      customer_status: "pending",
    })),
    totals:     { subtotal: 700, tax: 0, total: 700 },
    payment_status: "unpaid",
  };
}


describe("EstimateView · line-item duplication regression guard", () => {
  it("renders exactly N desktop rows + N mobile cards (both branches mount, CSS hides at runtime)", async () => {
    const p = _payload();
    // ``EstimateView`` fetches its payload — surface it via the
    // mocked ``api.get`` so the component transitions from
    // ``data === null`` to ``data === _payload`` after mount.
    api.get.mockResolvedValue(p);
    render(
      <MemoryRouter>
        <EstimateView estimateId="est-1" isAdmin />
      </MemoryRouter>
    );
    // Wait for the table to hydrate (the ``data`` state kicks in
    // asynchronously via the ``load`` effect).
    await screen.findByTestId("estimate-line-items-table");
    // Desktop table rows — one per line item.
    const rows = document.querySelectorAll(
      "[data-testid^='estimate-line-item-row-']",
    );
    expect(rows.length).toBe(p.line_items.length);
    // Mobile card list — same count. Both mount in the DOM; the
    // CSS ``@media (max-width: 639.98px)`` block shows / hides
    // them at runtime (see ``EstimateView.css``).
    const cards = document.querySelectorAll(
      "[data-testid^='estimate-line-item-card-']",
    );
    expect(cards.length).toBe(p.line_items.length);
    // Wrappers carry the responsive Tailwind classes.
    const table = screen.getByTestId("estimate-line-items-table");
    const cardList = screen.getByTestId("estimate-line-items-cards");
    expect(table.className).toMatch(/\bhidden\b/);
    expect(table.className).toMatch(/\bsm:table\b/);
    expect(cardList.className).toMatch(/\bsm:hidden\b/);
  });
});


describe("EstimateView.css · ev-lines-cards CSS gate contract", () => {
  const CSS_RAW = fs.readFileSync(
    path.resolve(process.cwd(),
      "src/components/EstimateView.css"), "utf-8",
  );
  // Strip ``/* ... */`` comments so the regex assertions below
  // don't match the historical bug description that still lives
  // inside the source comment.
  const CSS = CSS_RAW.replace(/\/\*[\s\S]*?\*\//g, "");

  it("does NOT declare an unconditional ``display`` on .ev-lines-cards", () => {
    // Feb-2026 regression fix — the ``display: flex`` declaration
    // must live inside a ``@media (max-width: ...)`` block so it
    // no longer overrides Tailwind's ``sm:hidden`` at desktop
    // widths. Match the base rule (outside any ``@media``) only.
    const _outsideMedia = CSS.replace(/@media[^{]*\{[^{}]*\{[^}]*\}[^}]*\}/g, "");
    const _base = _outsideMedia.match(
      /\.ev-lines-cards\s*\{[^}]*\}/,
    )?.[0] || "";
    expect(_base).not.toMatch(/display\s*:/);
  });

  it("declares display:flex inside the mobile media block", () => {
    // Locks the mobile-scoped rule (source-order agnostic — the
    // media query itself is the gate, not the cascade).
    const mediaBlock = CSS.match(
      /@media\s*\(\s*max-width:\s*639\.98px\s*\)\s*\{[^}]*\.ev-lines-cards\s*\{[^}]*\}/,
    );
    expect(mediaBlock).toBeTruthy();
    expect(mediaBlock[0]).toMatch(/display\s*:\s*flex/);
  });
});
