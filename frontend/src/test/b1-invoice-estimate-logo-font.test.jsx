/**
 * Task B1 · Feb-2026 — Logo 3x + body-copy +2px on invoice + estimate templates.
 *
 * Locks the CSS sizing bumps applied in:
 *   • frontend/src/components/InvoiceView.css
 *   • frontend/src/components/EstimateView.css
 *
 * Approach — hybrid source-lint + render:
 *   Per Task B1 ruling, JSDOM does NOT resolve stylesheet-declared
 *   rules (only inline ``style`` attributes), so ``getComputedStyle``
 *   would report ``""`` for every ``.iv-*`` / ``.ev-*`` class in a
 *   render-level test. To lock the CSS contract without a flaky
 *   snapshot, we read the two CSS files directly via ``fs`` and
 *   regex-assert the exact rule bodies. One render-level test
 *   confirms that <InvoiceView> + <EstimateView> still bind the
 *   ``iv-brand-logo`` class to their logo <img> (guards the JSX
 *   contract that the CSS rule targets).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, waitFor, cleanup,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const INVOICE_CSS = readFileSync(
  resolve(__dirname, "../components/InvoiceView.css"),
  "utf-8",
);
const ESTIMATE_CSS = readFileSync(
  resolve(__dirname, "../components/EstimateView.css"),
  "utf-8",
);


// ── Helpers ─────────────────────────────────────────────────────
// Extract the body of a CSS selector's first rule so per-property
// regexes don't accidentally match a property that lives inside a
// media query or a different selector with the same class prefix.
function _ruleBody(css, selector) {
  const rx = new RegExp(
    // Escape any regex metacharacters in the selector; then match
    // the FIRST occurrence at the start of a line (post-newline
    // whitespace tolerated) followed by ``{ ... }``. Non-greedy on
    // the body so we bail at the first ``}``.
    `(?:^|\\n)\\s*${
      selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    }\\s*\\{([^}]*)\\}`,
    "m",
  );
  const match = css.match(rx);
  return match ? match[1] : null;
}


// ═══════════════════════════════════════════════════════════════
// R7-2 · .iv-brand-logo — 3x sizing bump.
// ═══════════════════════════════════════════════════════════════
describe("Task B1 · .iv-brand-logo — 3x sizing", () => {
  it("declares max-height: 216px (3x of 72px)", () => {
    const body = _ruleBody(INVOICE_CSS, ".iv-brand-logo");
    expect(body).not.toBeNull();
    expect(body).toMatch(/max-height:\s*216px/);
  });

  it("declares max-width: min(660px, 100%) — width guard against narrow viewports",
      () => {
    const body = _ruleBody(INVOICE_CSS, ".iv-brand-logo");
    expect(body).not.toBeNull();
    // Whitespace tolerance inside the min() argument list.
    expect(body).toMatch(/max-width:\s*min\(\s*660px\s*,\s*100%\s*\)/);
  });

  it("preserves the object-fit / auto sizing contract", () => {
    const body = _ruleBody(INVOICE_CSS, ".iv-brand-logo");
    expect(body).toMatch(/width:\s*auto/);
    expect(body).toMatch(/height:\s*auto/);
    expect(body).toMatch(/object-fit:\s*contain/);
    expect(body).toMatch(/display:\s*block/);
  });

  it("no legacy 72px / 220px values remain on the rule", () => {
    const body = _ruleBody(INVOICE_CSS, ".iv-brand-logo");
    expect(body).not.toMatch(/max-height:\s*72px/);
    expect(body).not.toMatch(/max-width:\s*220px/);
  });
});


// ═══════════════════════════════════════════════════════════════
// R7-4 · InvoiceView.css — 9 body-copy +2px bumps.
// ═══════════════════════════════════════════════════════════════

// (selector, expected px value after +2px bump).
const _INVOICE_BUMPS = [
  [".iv-header-left",   "15px"],   // 13 → 15
  [".iv-kv",            "14px"],   // 12 → 14
  [".iv-bill-to",       "15px"],   // 13 → 15
  [".iv-prop-addr",     "15px"],   // 13 → 15
  [".iv-lines",         "14.5px"], // 12.5 → 14.5
  [".iv-notes",         "14.5px"], // 12.5 → 14.5
  [".iv-totals",        "14.5px"], // 12.5 → 14.5
  [".iv-total-due td",  "16px"],   // 14 → 16
  [".iv-stub-cols",     "14px"],   // 12 → 14
];

describe("Task B1 · InvoiceView.css body-copy +2px bumps", () => {
  for (const [selector, expected] of _INVOICE_BUMPS) {
    it(`${selector} carries font-size: ${expected}`, () => {
      const body = _ruleBody(INVOICE_CSS, selector);
      expect(body).not.toBeNull();
      const rx = new RegExp(
        `font-size:\\s*${expected.replace(".", "\\.")}(?![0-9])`,
      );
      expect(body).toMatch(rx);
    });
  }

  it("no legacy 12.5px value survives on the three .iv-lines / .iv-notes / .iv-totals rules",
      () => {
    for (const sel of [".iv-lines", ".iv-notes", ".iv-totals"]) {
      const body = _ruleBody(INVOICE_CSS, sel);
      expect(body).not.toBeNull();
      expect(body).not.toMatch(/font-size:\s*12\.5px/);
    }
  });

  it("leave-alone display / heading / label rules keep their original values",
      () => {
    // Sanity — the "explicitly leave alone" list from the recon.
    expect(INVOICE_CSS).toMatch(/\.iv-title\b[\s\S]*?font-size:\s*40px/);
    expect(INVOICE_CSS).toMatch(
      /\.iv-company-name[\s\S]*?font-size:\s*15px/,
    );
    expect(INVOICE_CSS).toMatch(
      /\.iv-bill-name\s*\{[^}]*font-size:\s*15px/,
    );
    // .iv-lines thead th — column labels stay 11px.
    expect(INVOICE_CSS).toMatch(
      /\.iv-lines\s+thead\s+th[\s\S]*?font-size:\s*11px/,
    );
    // .iv-due-marker — 15px callout stays put.
    expect(INVOICE_CSS).toMatch(
      /\.iv-due-marker[\s\S]*?font-size:\s*15px/,
    );
    // .iv-btn — toolbar chrome (outside doc body).
    expect(INVOICE_CSS).toMatch(/\.iv-btn\s*\{[^}]*font-size:\s*13px/);
  });
});


// ═══════════════════════════════════════════════════════════════
// R7-4 · EstimateView.css — 4 body-copy +2px bumps.
// ═══════════════════════════════════════════════════════════════

const _ESTIMATE_BUMPS = [
  [".ev-totals",             "14.5px"], // 12.5 → 14.5
  [".ev-total-highlight td", "16px"],   // 14 → 16
  [".ev-group-desc",         "14px"],   // 12 → 14
  [".ev-line-card-desc",     "16px"],   // 14 → 16
];

describe("Task B1 · EstimateView.css body-copy +2px bumps", () => {
  for (const [selector, expected] of _ESTIMATE_BUMPS) {
    it(`${selector} carries font-size: ${expected}`, () => {
      const body = _ruleBody(ESTIMATE_CSS, selector);
      expect(body).not.toBeNull();
      const rx = new RegExp(
        `font-size:\\s*${expected.replace(".", "\\.")}(?![0-9])`,
      );
      expect(body).toMatch(rx);
    });
  }

  it("leave-alone rules keep their original values", () => {
    // .ev-title — display headline.
    expect(ESTIMATE_CSS).toMatch(/\.ev-title[\s\S]*?font-size:\s*48px/);
    // .ev-est-title — heading.
    expect(ESTIMATE_CSS).toMatch(
      /\.ev-est-title[\s\S]*?font-size:\s*16px/,
    );
    // .ev-disclaimer — fine-print by design (11px).
    expect(ESTIMATE_CSS).toMatch(
      /\.ev-disclaimer[\s\S]*?font-size:\s*11px/,
    );
    // .ev-line-card-label / .ev-line-card-value — labels + numeric
    // display stay put.
    expect(ESTIMATE_CSS).toMatch(
      /\.ev-line-card-label[\s\S]*?font-size:\s*11px/,
    );
    expect(ESTIMATE_CSS).toMatch(
      /\.ev-line-card-value[\s\S]*?font-size:\s*15px/,
    );
  });
});


// ═══════════════════════════════════════════════════════════════
// Render-level — <InvoiceView> + <EstimateView> still bind the
// ``iv-brand-logo`` class to their logo <img>. Guards the JSX
// contract that the CSS rule targets. Without this, someone could
// rename the class in JSX and the CSS bumps would silently orphan.
// ═══════════════════════════════════════════════════════════════

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u-1" }, token: "t" }),
}));

// Import after vi.mock has been hoisted so the mocked ``api``
// module is used by the components.
const { api } = await import("@/api");
const InvoiceView = (await import("@/components/InvoiceView")).default;
const EstimateView = (await import("@/components/EstimateView")).default;
const { DEFAULT_LOGO_URL } = await import("@/lib/tenantLogo");


const _COMPANY = {
  name: "Pool & Landscaping of Vistancia",
  address: "12 Vistancia Blvd, Peoria, AZ",
  phone: "555-0100",
  website: "www.plofv.com",
  email: "hello@plofv.com",
  logo_url: DEFAULT_LOGO_URL,
};

const _INVOICE_PAYLOAD = {
  company: _COMPANY,
  bill_to: { name: "Jane Doe", address: "1 Main St" },
  property_address: null,
  header: {
    invoice_number: "INV-0001",
    invoice_date: "2026-09-09",
    credit_available: 0,
    outstanding_balance: 250,
  },
  line_items: [
    { description: "Service", cost_rate: 100, qty_hr: 1, percent: 0, total: 100 },
  ],
  totals: { subtotal: 100, this_invoice: 100, amount_paid: 0, total_due: 100 },
  notes: "Thanks!",
  is_due_on_receipt: false,
  payment_status: "unpaid",
};

const _ESTIMATE_PAYLOAD = {
  estimate_id: "est-1",
  status: "sent",
  decision: null,
  accepted_at: null, declined_at: null, decline_reason: null,
  sent_at: "2026-09-09T20:00:00+00:00",
  sent_via: "email", expires_at: null,
  company: _COMPANY,
  bill_to: { name: "Jane Doe", address: "1 Main St" },
  property_address: null,
  header: {
    customer_number: "c-1",
    estimate_number: "EST-0001",
    estimate_date: "2026-09-09",
  },
  title: "Quote",
  line_items: [
    { description: "Service", quantity: 1, total: 100,
      customer_status: "pending", retail_price_snapshot: 100 },
  ],
  totals: { subtotal: 100, taxes: 0, amount_paid: 0, total_estimated_cost: 100 },
  notes: null,
  as_customer: true,
  customer_view: { customer_group_display: false, groups: [] },
};


describe("Task B1 · render-level — .iv-brand-logo class binding", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
  });

  afterEach(() => cleanup());

  it("<InvoiceView> renders its logo <img> with class 'iv-brand-logo'",
      async () => {
    api.get.mockResolvedValue(_INVOICE_PAYLOAD);
    render(
      <MemoryRouter>
        <InvoiceView invoiceId="inv-1" />
      </MemoryRouter>,
    );
    const logo = await waitFor(() => screen.getByTestId("doc-header-logo"));
    expect(logo.tagName).toBe("IMG");
    expect(logo.className).toContain("iv-brand-logo");
    expect(logo.getAttribute("data-surface")).toBe("invoice");
  });

  it("<EstimateView> renders its logo <img> with class 'iv-brand-logo'",
      async () => {
    api.get.mockResolvedValue(_ESTIMATE_PAYLOAD);
    render(
      <MemoryRouter>
        <EstimateView estimateId="est-1" isAdmin />
      </MemoryRouter>,
    );
    const logo = await waitFor(() => screen.getByTestId("doc-header-logo"));
    expect(logo.tagName).toBe("IMG");
    expect(logo.className).toContain("iv-brand-logo");
    expect(logo.getAttribute("data-surface")).toBe("estimate");
  });
});
