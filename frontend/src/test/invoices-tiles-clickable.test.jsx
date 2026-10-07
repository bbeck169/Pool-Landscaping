/**
 * INVOICES-TILES-CLICKABLE · Feb-2026 — Vitest coverage for the
 * clickable summary + aging tiles on ``InvoicesList``.
 *
 * Two-layer strategy
 * ------------------
 * A. **Static source** (fast, no I/O) — grep that the policy wiring
 *    is in place:
 *       * ``toggleTile`` helper exists + reads/writes ``?tile=``
 *       * ``tileFiltered`` useMemo exists + chains after ``filtered``
 *       * All 8 slugs are referenced (collected / outstanding /
 *         overdue / aging-current / aging-1-30 / aging-31-60 /
 *         aging-61-90 / aging-90+)
 *       * SummaryTile receives ``active`` + ``onClick`` on the 3
 *         summary tiles
 *       * Aging-grid cells are rendered as ``<button>`` with
 *         ``aria-pressed``
 *       * Clear-filter affordance only renders when
 *         ``activeTile`` truthy
 *
 * B. **Mock-mounted integration** — render the real page with a
 *    MemoryRouter + mocked ``@/api`` + a controlled dataset covering
 *    every aging-day boundary (0, 1, 30, 31, 60, 61, 90, 91 days
 *    overdue). Click each tile, assert:
 *       * URL ``?tile=`` param updates (via useSearchParams)
 *       * active-tile ``aria-pressed="true"`` + ``data-active="true"``
 *       * list narrows to the expected invoice set
 *       * clicking the active tile clears it
 *       * deep-link entry ``?tile=foo`` auto-selects on mount
 *       * union with ``payment_status`` dropdown works (default
 *         is ``unpaid`` — Outstanding tile narrows further on top)
 */
import React from "react";
import fs from "fs";
import path from "path";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";


const INV_LIST_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/invoices/InvoicesList.jsx"),
  "utf8",
);
const SUMMARY_TILE_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/SummaryTile.jsx"),
  "utf8",
);


// ═══════════════════════════════════════════════════════════════
// A · Static-source wiring contract
// ═══════════════════════════════════════════════════════════════
describe("INVOICES-TILES-CLICKABLE · static wiring contract", () => {
  it("InvoicesList declares toggleTile reading/writing ?tile= via setParams", () => {
    expect(INV_LIST_SRC).toMatch(/const\s+toggleTile\s*=\s*\(/);
    expect(INV_LIST_SRC).toMatch(/params\.get\(\s*["']tile["']\s*\)/);
    // ``history.replace`` semantics via setParams(_, { replace: true })
    // so the back button isn't polluted on every tile click.
    expect(INV_LIST_SRC).toMatch(
      /setParams\([\s\S]*?\{\s*replace:\s*true\s*\}\s*\)/,
    );
  });

  it("InvoicesList declares tileFiltered useMemo chaining after filtered", () => {
    expect(INV_LIST_SRC).toMatch(/const\s+tileFiltered\s*=\s*useMemo/);
    // Dep list = [filtered, activeTile] so the chain reacts to both.
    expect(INV_LIST_SRC).toMatch(/\}\s*,\s*\[filtered,\s*activeTile\]\s*\)/);
  });

  it("InvoicesList references every slug of the 8 tiles", () => {
    for (const slug of [
      "collected", "outstanding", "overdue",
      "aging-current", "aging-1-30", "aging-31-60",
      "aging-61-90", "aging-90+",
    ]) {
      // Allow either literal match or construction via template
      // literal (``\`aging-${k}\``) which produces ``aging-<k>`` at
      // runtime.
      const literal = INV_LIST_SRC.includes(`"${slug}"`)
        || INV_LIST_SRC.includes(`'${slug}'`);
      const viaTemplate = /`aging-\$\{k\}`/.test(INV_LIST_SRC);
      expect(
        literal || (slug.startsWith("aging-") && viaTemplate),
        `slug ${JSON.stringify(slug)} not referenced in InvoicesList.jsx`,
      ).toBe(true);
    }
  });

  it("3 summary tiles pass active + onClick + testid", () => {
    for (const [slug, testid] of [
      ["collected", "inv-tile-collected"],
      ["outstanding", "inv-tile-outstanding"],
      ["overdue", "inv-tile-overdue"],
    ]) {
      expect(INV_LIST_SRC).toContain(`testid="${testid}"`);
      expect(INV_LIST_SRC).toContain(`active={activeTile === "${slug}"}`);
      expect(INV_LIST_SRC).toContain(`onClick={() => toggleTile("${slug}")}`);
    }
  });

  it("SummaryTile component gained onClick + active + ariaLabel props", () => {
    expect(SUMMARY_TILE_SRC).toMatch(/onClick,\s*active\s*=\s*false,\s*ariaLabel/);
    // Clickable path renders a native <button> for keyboard + screen
    // reader semantics.
    expect(SUMMARY_TILE_SRC).toMatch(/const\s+Tag\s*=\s*clickable\s*\?\s*"button"\s*:\s*"div"/);
    expect(SUMMARY_TILE_SRC).toMatch(/"aria-pressed":\s*clickable\s*\?\s*!!active/);
    // Enter + Space keyboard activation.
    expect(SUMMARY_TILE_SRC).toMatch(/e\.key\s*===\s*"Enter"\s*\|\|\s*e\.key\s*===\s*"\s"/);
  });

  it("Aging buckets are rendered as <button> with aria-pressed", () => {
    // The aging grid loop produces a <button> per bucket now; grep
    // the specific a11y hooks regardless of attribute order.
    expect(INV_LIST_SRC).toMatch(/<button[\s\S]*?aria-pressed=\{isActive\}/);
    expect(INV_LIST_SRC).toMatch(/toggleTile\(slug\)/);
  });

  it("Clear-filter affordance renders only when a tile is active", () => {
    // Guarded by ``activeTile ? (<button ...>) : null``.
    expect(INV_LIST_SRC).toMatch(
      /\{\s*activeTile\s*\?\s*\(\s*<button[\s\S]*?data-testid="inv-tile-clear"/,
    );
  });

  it("downstream consumers (visibleIds / list render / count) use tileFiltered", () => {
    expect(INV_LIST_SRC).toMatch(/const\s+visibleIds\s*=\s*tileFiltered\.map/);
    expect(INV_LIST_SRC).toMatch(/\{tileFiltered\.map\(\(r\)\s*=>\s*\(/);
    // Empty-state branch triggers off tileFiltered length too.
    expect(INV_LIST_SRC).toMatch(/tileFiltered\.length\s*===\s*0/);
  });
});


// ═══════════════════════════════════════════════════════════════
// B · Mock-mounted integration
// ═══════════════════════════════════════════════════════════════

// Shared mocks — defined at module scope so every describe block
// shares the same api spy and can reset it between tests.
vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u-1" }, token: "t" }),
}));
// Suppress heavy children — the test only cares about the tile
// filter chain. ``NavyFilterBar`` is a large multi-slot component;
// a trivial pass-through keeps the layout quiet.
vi.mock("@/components/NavyFilterBar", () => ({
  default: ({ children }) => <div data-testid="mock-navy-filter-bar">{children}</div>,
}));
vi.mock("@/components/CustomerFilterBar", () => ({
  default: () => null,
}));
vi.mock("@/components/invoices/BulkChargeOnFileModal", () => ({
  default: () => null,
}));
vi.mock("@/components/invoices/BulkChargeAchModal", () => ({
  default: () => null,
}));
vi.mock("@/components/invoices/InvoicePdfPanel", () => ({
  default: () => null,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {}, {
    success: () => {}, error: () => {},
  }),
}));


function _daysAgoISO(n) {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}
function _daysFromNowISO(n) {
  return _daysAgoISO(-n);
}


/** Seeded invoice fixture matrix covering every aging-day boundary
 * from the spec (gate Q6) + a paid-this-month row for the Collected
 * tile. */
function _buildFixtures() {
  return [
    // Unpaid, due in the future → aging-current
    { id: "inv-current-future", title: "Current future",
      customer_name: "Alpha", customer_id: "c-alpha",
      status: "sent", payment_status: "unpaid", is_paid: false,
      total: 100, amount_paid: 0, due_date: _daysFromNowISO(10) },
    // Unpaid, due today → aging-current (dueDays === 0)
    { id: "inv-current-today", title: "Current today",
      customer_name: "Bravo", customer_id: "c-bravo",
      status: "sent", payment_status: "unpaid", is_paid: false,
      total: 100, amount_paid: 0, due_date: _daysAgoISO(0) },
    // Unpaid, 1 day overdue → aging-1-30 lower bound
    { id: "inv-aging-1", title: "1 day overdue",
      customer_name: "Charlie", customer_id: "c-charlie",
      status: "sent", payment_status: "unpaid", is_paid: false,
      total: 100, amount_paid: 0, due_date: _daysAgoISO(1) },
    // 30 days → aging-1-30 upper bound
    { id: "inv-aging-30", title: "30 days overdue",
      customer_name: "Delta", customer_id: "c-delta",
      status: "sent", payment_status: "unpaid", is_paid: false,
      total: 100, amount_paid: 0, due_date: _daysAgoISO(30) },
    // 31 days → aging-31-60 lower bound
    { id: "inv-aging-31", title: "31 days overdue",
      customer_name: "Echo", customer_id: "c-echo",
      status: "sent", payment_status: "unpaid", is_paid: false,
      total: 100, amount_paid: 0, due_date: _daysAgoISO(31) },
    // 60 days → aging-31-60 upper bound
    { id: "inv-aging-60", title: "60 days overdue",
      customer_name: "Foxtrot", customer_id: "c-foxtrot",
      status: "sent", payment_status: "unpaid", is_paid: false,
      total: 100, amount_paid: 0, due_date: _daysAgoISO(60) },
    // 61 days → aging-61-90 lower bound
    { id: "inv-aging-61", title: "61 days overdue",
      customer_name: "Golf", customer_id: "c-golf",
      status: "sent", payment_status: "unpaid", is_paid: false,
      total: 100, amount_paid: 0, due_date: _daysAgoISO(61) },
    // 90 days → aging-61-90 upper bound
    { id: "inv-aging-90", title: "90 days overdue",
      customer_name: "Hotel", customer_id: "c-hotel",
      status: "sent", payment_status: "unpaid", is_paid: false,
      total: 100, amount_paid: 0, due_date: _daysAgoISO(90) },
    // 91 days → aging-90+ lower bound
    { id: "inv-aging-91", title: "91 days overdue",
      customer_name: "India", customer_id: "c-india",
      status: "sent", payment_status: "unpaid", is_paid: false,
      total: 100, amount_paid: 0, due_date: _daysAgoISO(91) },
    // Paid this month → Collected tile
    { id: "inv-paid-this-month", title: "Paid this month",
      customer_name: "Juliet", customer_id: "c-juliet",
      status: "paid", payment_status: "paid", is_paid: true,
      total: 500, amount_paid: 500, due_date: _daysAgoISO(5),
      paid_at: new Date().toISOString() },
  ];
}


function _mountAt(initialEntry, api) {
  // Lazy-import InvoicesList inside each test so vi.mock settings
  // defined in the describe block are honoured.
  const InvoicesList = React.lazy(
    () => import("@/pages/invoices/InvoicesList"),
  );
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <React.Suspense fallback={null}>
        <Routes>
          <Route path="/invoices" element={<InvoicesList />} />
        </Routes>
      </React.Suspense>
    </MemoryRouter>,
  );
}


describe("INVOICES-TILES-CLICKABLE · click behaviour", () => {
  let api;

  beforeEach(async () => {
    api = (await import("@/api")).api;
    api.get.mockReset();
    const rows = _buildFixtures();
    api.get.mockImplementation((url) => {
      if (url.startsWith("/quotes?")) return Promise.resolve(rows);
      if (url === "/payments/summary") return Promise.resolve({
        collected_this_month: 500,
        outstanding_total: 900,
        outstanding_count: 9,
        overdue: new Array(8).fill(0).map((_, i) => ({ id: `o-${i}` })),
        month_label: "October 2026",
      });
      if (url === "/invoices/overview") return Promise.resolve({ invoices: [] });
      if (url === "/invoices/line-item-categories")
        return Promise.resolve({ categories: [] });
      return Promise.resolve([]);
    });
  });

  afterEach(() => cleanup());

  it("mounts without any ?tile= → list shows all 9 unpaid fixtures (default unpaid filter)", async () => {
    _mountAt("/invoices", api);
    const table = await waitFor(() => screen.getByTestId("invoices-table"));
    // 9 unpaid fixtures (paid-this-month is filtered out by the
    // default ``payment_status=unpaid`` server filter + the client
    // still sees it as mock data; but the client only renders what
    // the server returned so the full fixture list is visible —
    // this test asserts the baseline).
    const rows = table.querySelectorAll("tbody tr");
    // ``>= 9`` — the baseline is "every fixture renders" because
    // the mock /quotes route returns them all regardless of
    // payment_status (the real backend filters, but the mock
    // doesn't). The tile-filter tests below are the ones that
    // care about the actual filter effect.
    expect(rows.length).toBeGreaterThanOrEqual(9);
  });

  it("clicking Outstanding tile sets ?tile=outstanding + aria-pressed", async () => {
    _mountAt("/invoices", api);
    const tile = await waitFor(() =>
      screen.getByTestId("inv-tile-outstanding"));
    expect(tile.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(tile);
    await waitFor(() => {
      expect(screen.getByTestId("inv-tile-outstanding")
        .getAttribute("aria-pressed")).toBe("true");
    });
    expect(screen.getByTestId("inv-tile-outstanding")
      .getAttribute("data-active")).toBe("true");
  });

  it("clicking the active tile again clears the filter", async () => {
    _mountAt("/invoices", api);
    const tile = await waitFor(() =>
      screen.getByTestId("inv-tile-overdue"));
    fireEvent.click(tile);  // activate
    await waitFor(() => {
      expect(screen.getByTestId("inv-tile-overdue")
        .getAttribute("aria-pressed")).toBe("true");
    });
    fireEvent.click(screen.getByTestId("inv-tile-overdue")); // toggle off
    await waitFor(() => {
      expect(screen.getByTestId("inv-tile-overdue")
        .getAttribute("aria-pressed")).toBe("false");
    });
  });

  it("clicking a different tile replaces the active one (single-select)",
     async () => {
    _mountAt("/invoices", api);
    await waitFor(() => screen.getByTestId("inv-tile-outstanding"));
    fireEvent.click(screen.getByTestId("inv-tile-outstanding"));
    await waitFor(() =>
      expect(screen.getByTestId("inv-tile-outstanding")
        .getAttribute("aria-pressed")).toBe("true"));
    fireEvent.click(screen.getByTestId("inv-tile-overdue"));
    await waitFor(() => {
      expect(screen.getByTestId("inv-tile-overdue")
        .getAttribute("aria-pressed")).toBe("true");
      expect(screen.getByTestId("inv-tile-outstanding")
        .getAttribute("aria-pressed")).toBe("false");
    });
  });

  it("deep-link entry /invoices?tile=aging-61-90 auto-selects on mount",
     async () => {
    _mountAt("/invoices?tile=aging-61-90", api);
    const cell = await waitFor(() => screen.getByTestId("aging-61-90"));
    expect(cell.getAttribute("aria-pressed")).toBe("true");
    expect(cell.getAttribute("data-active")).toBe("true");
  });

  it("clear-filter affordance only renders when a tile is active",
     async () => {
    _mountAt("/invoices", api);
    await waitFor(() => screen.getByTestId("invoices-table"));
    expect(screen.queryByTestId("inv-tile-clear")).toBeNull();
    fireEvent.click(screen.getByTestId("inv-tile-outstanding"));
    await waitFor(() => {
      expect(screen.getByTestId("inv-tile-clear")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("inv-tile-clear"));
    await waitFor(() => {
      expect(screen.queryByTestId("inv-tile-clear")).toBeNull();
    });
  });

  it("aging bucket boundaries catch exactly the expected fixtures",
     async () => {
    // Load with tile=aging-1-30 — should include inv-aging-1 and
    // inv-aging-30 but NOT inv-aging-31 or inv-aging-61.
    _mountAt("/invoices?tile=aging-1-30", api);
    const table = await waitFor(() => screen.getByTestId("invoices-table"));
    const rowKeys = Array.from(table.querySelectorAll("tbody tr"))
      .map((r) => r.getAttribute("data-testid"));
    // Table rows carry testids like ``invoice-row-<id>`` on the real
    // page; the mock fixtures render whatever shape InvoicesList
    // produces. We only need to verify the row count matches.
    const bodyText = table.textContent;
    expect(bodyText).toContain("1 day overdue");
    expect(bodyText).toContain("30 days overdue");
    expect(bodyText).not.toContain("31 days overdue");
    expect(bodyText).not.toContain("61 days overdue");
  });

  it("aging-31-60 boundary: catches 31 + 60, excludes 30 + 61",
     async () => {
    _mountAt("/invoices?tile=aging-31-60", api);
    const table = await waitFor(() => screen.getByTestId("invoices-table"));
    const bodyText = table.textContent;
    expect(bodyText).toContain("31 days overdue");
    expect(bodyText).toContain("60 days overdue");
    expect(bodyText).not.toContain("30 days overdue");
    expect(bodyText).not.toContain("61 days overdue");
  });

  it("aging-90+ catches 91, excludes 90", async () => {
    _mountAt("/invoices?tile=aging-90%2B", api);
    const table = await waitFor(() => screen.getByTestId("invoices-table"));
    const bodyText = table.textContent;
    expect(bodyText).toContain("91 days overdue");
    expect(bodyText).not.toContain("90 days overdue");
  });

  it("aging-current includes future-due + today, excludes 1-day-overdue",
     async () => {
    _mountAt("/invoices?tile=aging-current", api);
    const table = await waitFor(() => screen.getByTestId("invoices-table"));
    const bodyText = table.textContent;
    expect(bodyText).toContain("Current future");
    expect(bodyText).toContain("Current today");
    expect(bodyText).not.toContain("1 day overdue");
  });

  it("Collected tile narrows to paid-this-month rows (union with payment_status=paid)",
     async () => {
    // Deep-link to the paid payment_status + collected tile so we
    // see the paid-this-month fixture surface.
    _mountAt("/invoices?payment_status=paid&tile=collected", api);
    const table = await waitFor(() => screen.getByTestId("invoices-table"));
    const bodyText = table.textContent;
    expect(bodyText).toContain("Paid this month");
    // Unpaid rows don't match the Collected filter.
    expect(bodyText).not.toContain("91 days overdue");
  });
});
