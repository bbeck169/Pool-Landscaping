/**
 * INVOICE-STATUS-STAMP · Feb-2026 — Vitest coverage for the shared
 * PAID / PAST DUE rubber-stamp overlay.
 *
 * Scope
 * -----
 *  1. ``<InvoiceStatusStamp>`` standalone — null / paid / past-due.
 *  2. ``deriveInvoiceStampStatus`` — maps the ``/invoices/{id}/full``
 *     payload shape to the stamp status.
 *  3. CSS source — ``invoice-status-stamp.css`` ships
 *     ``print-color-adjust: exact``, the ``-webkit-*`` alias,
 *     ``pointer-events: none`` on ``.invoice-stamp``, and an
 *     ``@media print`` block that keeps the red forced.
 *  4. ``<DocDesktopShell>`` — the new ``headerOverlay`` slot renders
 *     INSIDE ``.iv-header`` as the first child so the stamp's
 *     ``position: absolute`` resolves against the header, not the
 *     page.
 *  5. ``.iv-header`` carries ``position: relative`` (InvoiceView.css
 *     source assertion).
 *  6. Host-surface integration — ``<InvoiceView>`` mounted with a
 *     paid payload surfaces ``invoice-stamp-paid``; with a past-due
 *     payload surfaces ``invoice-stamp-past-due``; with neither,
 *     neither stamp appears.
 *  7. Public surfaces — ``<PublicInvoicePay>`` + ``<PublicInvoiceMagic>``
 *     mount ``<InvoiceView>`` under their own wrappers; the stamp
 *     reaches the DOM through them.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";


// Static-source reads for the CSS + wiring contracts.
const COMP_DIR = path.resolve(__dirname, "../components");
const STAMP_CSS = fs.readFileSync(
  path.join(COMP_DIR, "invoice-status-stamp.css"), "utf8",
);
const SHELL_SRC = fs.readFileSync(
  path.join(COMP_DIR, "documents/DocDesktopShell.jsx"), "utf8",
);
const IV_CSS = fs.readFileSync(
  path.join(COMP_DIR, "InvoiceView.css"), "utf8",
);


// ═══════════════════════════════════════════════════════════════
// 1 · Standalone <InvoiceStatusStamp> render matrix
// ═══════════════════════════════════════════════════════════════
describe("<InvoiceStatusStamp> standalone", () => {
  afterEach(() => cleanup());

  it("renders nothing when status is null", async () => {
    const { default: InvoiceStatusStamp } =
      await import("@/components/InvoiceStatusStamp");
    const { container } = render(<InvoiceStatusStamp status={null} />);
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("invoice-stamp-paid")).toBeNull();
    expect(screen.queryByTestId("invoice-stamp-past-due")).toBeNull();
  });

  it("renders nothing on unknown status strings", async () => {
    const { default: InvoiceStatusStamp } =
      await import("@/components/InvoiceStatusStamp");
    const { container } = render(<InvoiceStatusStamp status="draft" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders PAID stamp with testid + copy when status='paid'",
     async () => {
    const { default: InvoiceStatusStamp } =
      await import("@/components/InvoiceStatusStamp");
    render(<InvoiceStatusStamp status="paid" />);
    const stamp = screen.getByTestId("invoice-stamp-paid");
    expect(stamp.className).toContain("invoice-stamp");
    expect(stamp.className).toContain("invoice-stamp--paid");
    expect(stamp.getAttribute("aria-hidden")).toBe("true");
    expect(stamp.textContent).toMatch(/Paid/i);
    expect(stamp.textContent).toMatch(/Invoice/i);
    // Grunge filter defs are mounted as a sibling.
    expect(screen.getByTestId("invoice-stamp-filter-defs")).toBeTruthy();
  });

  it("renders PAST DUE stamp with testid + copy when status='past-due'",
     async () => {
    const { default: InvoiceStatusStamp } =
      await import("@/components/InvoiceStatusStamp");
    render(<InvoiceStatusStamp status="past-due" />);
    const stamp = screen.getByTestId("invoice-stamp-past-due");
    expect(stamp.className).toContain("invoice-stamp");
    expect(stamp.className).toContain("invoice-stamp--past-due");
    expect(stamp.getAttribute("aria-hidden")).toBe("true");
    expect(stamp.textContent).toMatch(/Past Due/i);
    expect(stamp.textContent).toMatch(/Please Remit Payment/i);
  });
});


// ═══════════════════════════════════════════════════════════════
// 2 · deriveInvoiceStampStatus — payload → status mapping
// ═══════════════════════════════════════════════════════════════
describe("deriveInvoiceStampStatus", () => {
  const _today = new Date();
  const _yesterday = new Date(_today.getTime() - 24 * 60 * 60 * 1000)
    .toISOString().slice(0, 10);
  const _tomorrow = new Date(_today.getTime() + 24 * 60 * 60 * 1000)
    .toISOString().slice(0, 10);

  it("returns null for null / non-object inputs", async () => {
    const { deriveInvoiceStampStatus } =
      await import("@/components/InvoiceStatusStamp");
    expect(deriveInvoiceStampStatus(null)).toBeNull();
    expect(deriveInvoiceStampStatus(undefined)).toBeNull();
    expect(deriveInvoiceStampStatus(42)).toBeNull();
    expect(deriveInvoiceStampStatus("whatever")).toBeNull();
  });

  it("returns 'paid' when payment_status is 'paid' (case insensitive)",
     async () => {
    const { deriveInvoiceStampStatus } =
      await import("@/components/InvoiceStatusStamp");
    expect(deriveInvoiceStampStatus({
      payment_status: "paid",
      header: { due_date: _yesterday },
    })).toBe("paid");
    expect(deriveInvoiceStampStatus({ payment_status: "PAID" })).toBe("paid");
    expect(deriveInvoiceStampStatus({ payment_status: "Paid" })).toBe("paid");
  });

  it("PAID wins over PAST DUE when both triggers would fire", async () => {
    const { deriveInvoiceStampStatus } =
      await import("@/components/InvoiceStatusStamp");
    expect(deriveInvoiceStampStatus({
      payment_status: "paid",
      header: { due_date: _yesterday },
    })).toBe("paid");
  });

  it("returns 'past-due' when unpaid + due_date strictly before today",
     async () => {
    const { deriveInvoiceStampStatus } =
      await import("@/components/InvoiceStatusStamp");
    expect(deriveInvoiceStampStatus({
      payment_status: "unpaid",
      header: { due_date: _yesterday },
    })).toBe("past-due");
  });

  it("returns null when unpaid + due_date is today or future", async () => {
    const { deriveInvoiceStampStatus } =
      await import("@/components/InvoiceStatusStamp");
    const todayISO = new Date().toISOString().slice(0, 10);
    expect(deriveInvoiceStampStatus({
      payment_status: "unpaid",
      header: { due_date: todayISO },
    })).toBeNull();
    expect(deriveInvoiceStampStatus({
      payment_status: "unpaid",
      header: { due_date: _tomorrow },
    })).toBeNull();
  });

  it("returns null when due_date is missing or unparseable", async () => {
    const { deriveInvoiceStampStatus } =
      await import("@/components/InvoiceStatusStamp");
    expect(deriveInvoiceStampStatus({ payment_status: "unpaid" })).toBeNull();
    expect(deriveInvoiceStampStatus({
      payment_status: "unpaid", header: {},
    })).toBeNull();
    expect(deriveInvoiceStampStatus({
      payment_status: "unpaid", header: { due_date: "" },
    })).toBeNull();
    expect(deriveInvoiceStampStatus({
      payment_status: "unpaid", header: { due_date: "not-a-date" },
    })).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════
// 3 · CSS source — print-color-adjust + pointer-events + @media print
// ═══════════════════════════════════════════════════════════════
describe("invoice-status-stamp.css shape", () => {
  it("declares pointer-events: none on .invoice-stamp", () => {
    expect(STAMP_CSS).toMatch(
      /\.invoice-stamp\b[\s\S]*?pointer-events\s*:\s*none/,
    );
  });

  it("declares both print-color-adjust and -webkit-print-color-adjust",
     () => {
    expect(STAMP_CSS).toMatch(/print-color-adjust\s*:\s*exact/);
    expect(STAMP_CSS).toMatch(/-webkit-print-color-adjust\s*:\s*exact/);
  });

  it("has an @media print block that keeps the stamp red", () => {
    expect(STAMP_CSS).toMatch(
      /@media\s*print\s*\{[\s\S]*?\.invoice-stamp\b[\s\S]*?color\s*:\s*#c0272d/,
    );
  });

  it("rotation applied to each stamp variant", () => {
    // PAST DUE ~ -10/-12deg, PAID ~ +8/+10deg per spec. TD-70 ·
    // Feb-2026 — the ``transform`` now carries a
    // ``translate(-50%, 0)`` prefix (top-center placement — see
    // the "TD-70 · stamp is top-center on the invoice body" test
    // below) in front of the rotation. Regex tolerates both the
    // pre-TD-70 bare-rotate shape and the TD-70+ translate-then-
    // rotate shape so a future refactor can collapse back to a
    // simpler transform without breaking the lock.
    expect(STAMP_CSS).toMatch(
      /\.invoice-stamp--past-due[\s\S]*?transform\s*:\s*(?:translate\([^)]+\)\s+)?rotate\(-?\d+deg\)/,
    );
    expect(STAMP_CSS).toMatch(
      /\.invoice-stamp--paid[\s\S]*?transform\s*:\s*(?:translate\([^)]+\)\s+)?rotate\(-?\d+deg\)/,
    );
  });

  // ═══════════════════════════════════════════════════════════════
  // TD-70 · Feb-2026 — stamp is top-center on the invoice body
  // (operator-ruled move from the pre-TD-70 top-right anchor
  // which overlapped the invoice #, date, credit available, and
  // outstanding balance fields on the top-right header block,
  // making them unreadable on every paid invoice).
  // ═══════════════════════════════════════════════════════════════
  it("TD-70 · stamp is top-center (left: 50% + translate(-50%, 0))", () => {
    // Base ``.invoice-stamp`` anchors horizontally via left: 50%.
    expect(STAMP_CSS).toMatch(
      /\.invoice-stamp\b[\s\S]*?left\s*:\s*50%/,
    );
    // Each variant's transform carries the ``translate(-50%, 0)``
    // centering prefix (combined with the per-variant rotate).
    expect(STAMP_CSS).toMatch(
      /\.invoice-stamp--paid[\s\S]*?transform\s*:\s*translate\(-50%,\s*0\)\s+rotate\(/,
    );
    expect(STAMP_CSS).toMatch(
      /\.invoice-stamp--past-due[\s\S]*?transform\s*:\s*translate\(-50%,\s*0\)\s+rotate\(/,
    );
    // Negative lock — the pre-TD-70 ``right: 24px`` / ``right: 8px``
    // anchor is gone from the base block + the mobile block (both
    // overlapped the top-right header fields).
    expect(STAMP_CSS).not.toMatch(
      /\.invoice-stamp\s*\{[\s\S]*?right\s*:\s*2\d+px[\s\S]*?\}/,
    );
  });

  it("stamps carry the SVG grunge filter via filter: url(#...)", () => {
    expect(STAMP_CSS).toMatch(
      /filter\s*:\s*url\(#invoice-stamp-grunge\)/,
    );
  });

  it("mobile media query scales the stamps down", () => {
    expect(STAMP_CSS).toMatch(
      /@media\s*\(max-width:\s*480px\)/,
    );
  });

  it("background is transparent — invoice content stays visible", () => {
    expect(STAMP_CSS).toMatch(/\.invoice-stamp\b[\s\S]*?background\s*:\s*transparent/);
    // No solid fill on either variant.
    expect(STAMP_CSS).not.toMatch(/\.invoice-stamp--(paid|past-due)[\s\S]*?background-color\s*:\s*#[0-9a-f]{3,6}/i);
  });
});


// ═══════════════════════════════════════════════════════════════
// 4 · DocDesktopShell — headerOverlay slot wiring
// ═══════════════════════════════════════════════════════════════
describe("DocDesktopShell headerOverlay slot", () => {
  afterEach(() => cleanup());

  it("accepts a ``headerOverlay`` prop", () => {
    expect(SHELL_SRC).toMatch(/headerOverlay\s*=\s*null/);
  });

  it("renders ``headerOverlay`` as the FIRST child of ``.iv-header``",
     () => {
    // Source-level: ``{headerOverlay}`` must appear BEFORE
    // ``<div className="iv-header-left">`` inside the ``.iv-header`` block.
    const headerOpenIdx = SHELL_SRC.indexOf('className="iv-header"');
    const overlayIdx = SHELL_SRC.indexOf("{headerOverlay}", headerOpenIdx);
    const leftIdx = SHELL_SRC.indexOf(
      'className="iv-header-left"', headerOpenIdx,
    );
    expect(headerOpenIdx).toBeGreaterThan(-1);
    expect(overlayIdx).toBeGreaterThan(headerOpenIdx);
    expect(overlayIdx).toBeLessThan(leftIdx);
  });

  it("mounts rendered overlay JSX inside the header wrapper",
     async () => {
    const DocDesktopShell = (await import(
      "@/components/documents/DocDesktopShell"
    )).default;
    render(
      <DocDesktopShell
        docType="invoice"
        headerOverlay={<div data-testid="t-stamp-sentinel">S</div>}
        lines={null}
      />,
    );
    const header = screen.getByTestId("doc-desktop-shell-header");
    const sentinel = screen.getByTestId("t-stamp-sentinel");
    expect(header.contains(sentinel)).toBe(true);
  });
});


// ═══════════════════════════════════════════════════════════════
// 5 · InvoiceView.css — .iv-header gets position: relative
// ═══════════════════════════════════════════════════════════════
describe("InvoiceView.css .iv-header anchor", () => {
  it(".iv-header carries position: relative so overlay works", () => {
    expect(IV_CSS).toMatch(
      /\.iv-header\s*\{[\s\S]*?position\s*:\s*relative/,
    );
  });
});


// ═══════════════════════════════════════════════════════════════
// 6 · Host-surface integration — <InvoiceView> + public pages
// ═══════════════════════════════════════════════════════════════

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
  TOKEN_KEY: "token",
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u-1" }, token: "t" }),
}));
// PaymentForm is unused in these tests; mock to avoid pulling in
// Stripe deps at module eval.
vi.mock("@/components/PaymentForm", () => ({
  default: () => null,
}));

const _COMPANY = {
  name: "Pool & Landscaping of Vistancia",
  address: "12 Vistancia Blvd, Peoria, AZ",
  phone: "555-0100",
  website: "www.plofv.com",
  email: "hello@plofv.com",
  logo_url: null,
};

function _basePayload({ paymentStatus = "unpaid", dueDate = null } = {}) {
  return {
    company: _COMPANY,
    bill_to: { name: "Jane Doe", address: "1 Main St" },
    property_address: null,
    header: {
      invoice_number: "INV-0001",
      invoice_date: "2026-09-09",
      credit_available: 0,
      outstanding_balance: 250,
      due_date: dueDate,
    },
    line_items: [
      { description: "Service", cost_rate: 100, qty_hr: 1, percent: 0, total: 100 },
    ],
    totals: { subtotal: 100, this_invoice: 100, amount_paid: 0, total_due: 100 },
    notes: "Thanks!",
    is_due_on_receipt: false,
    payment_status: paymentStatus,
  };
}

describe("<InvoiceView> integration · PAID / PAST DUE / no-stamp",
   () => {
  let api;
  let InvoiceView;

  beforeEach(async () => {
    api = (await import("@/api")).api;
    InvoiceView = (await import("@/components/InvoiceView")).default;
    api.get.mockReset();
  });

  afterEach(() => cleanup());

  it("renders PAID stamp when payment_status='paid'", async () => {
    api.get.mockResolvedValue(_basePayload({ paymentStatus: "paid" }));
    render(
      <MemoryRouter>
        <InvoiceView invoiceId="inv-1" />
      </MemoryRouter>,
    );
    const stamp = await waitFor(() =>
      screen.getByTestId("invoice-stamp-paid"),
    );
    expect(stamp).toBeTruthy();
    // Lives inside the invoice header wrapper, not elsewhere.
    const header = screen.getByTestId("doc-desktop-shell-header");
    expect(header.contains(stamp)).toBe(true);
    // past-due variant NOT rendered simultaneously.
    expect(screen.queryByTestId("invoice-stamp-past-due")).toBeNull();
  });

  it("renders PAST DUE stamp when unpaid + due_date in the past",
     async () => {
    const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000)
      .toISOString().slice(0, 10);
    api.get.mockResolvedValue(_basePayload({
      paymentStatus: "unpaid",
      dueDate: yesterday,
    }));
    render(
      <MemoryRouter>
        <InvoiceView invoiceId="inv-1" />
      </MemoryRouter>,
    );
    const stamp = await waitFor(() =>
      screen.getByTestId("invoice-stamp-past-due"),
    );
    expect(stamp).toBeTruthy();
    const header = screen.getByTestId("doc-desktop-shell-header");
    expect(header.contains(stamp)).toBe(true);
    expect(screen.queryByTestId("invoice-stamp-paid")).toBeNull();
  });

  it("renders NO stamp when unpaid + no due_date", async () => {
    api.get.mockResolvedValue(_basePayload({ paymentStatus: "unpaid" }));
    render(
      <MemoryRouter>
        <InvoiceView invoiceId="inv-1" />
      </MemoryRouter>,
    );
    // Wait for the invoice header to render so the loading spinner
    // has already resolved.
    await waitFor(() => screen.getByTestId("doc-desktop-shell-header"));
    expect(screen.queryByTestId("invoice-stamp-paid")).toBeNull();
    expect(screen.queryByTestId("invoice-stamp-past-due")).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════
// 7 · Public surfaces inherit via <InvoiceView>
// ═══════════════════════════════════════════════════════════════
describe("Public invoice surfaces inherit the stamp via <InvoiceView>",
   () => {
  let api;

  beforeEach(async () => {
    api = (await import("@/api")).api;
    api.get.mockReset();
  });

  afterEach(() => cleanup());

  it("PublicInvoicePay — paid payload surfaces PAID stamp", async () => {
    const PublicInvoicePay = (await import(
      "@/pages/public/PublicInvoicePay"
    )).default;
    api.get.mockResolvedValue(_basePayload({ paymentStatus: "paid" }));
    render(
      <MemoryRouter
        initialEntries={["/pay/invoice/inv-1?token=tok&src=link"]}
      >
        <Routes>
          <Route path="/pay/invoice/:id" element={<PublicInvoicePay />} />
        </Routes>
      </MemoryRouter>,
    );
    const stamp = await waitFor(() =>
      screen.getByTestId("invoice-stamp-paid"),
    );
    expect(stamp).toBeTruthy();
  });

  it("PublicInvoiceMagic — past-due payload surfaces PAST DUE stamp",
     async () => {
    const PublicInvoiceMagic = (await import(
      "@/pages/public/PublicInvoiceMagic"
    )).default;
    // Craft a minimal JWT (header.payload.signature, base64url)
    // whose payload has ``invoice_id`` so the component resolves
    // the mount. Signature is irrelevant — the backend verifies,
    // we're just driving the client-side route.
    const payload = { invoice_id: "inv-1" };
    const b64u = (obj) =>
      Buffer.from(JSON.stringify(obj)).toString("base64")
        .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const fakeJwt = `${b64u({ alg: "none" })}.${b64u(payload)}.sig`;
    const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000)
      .toISOString().slice(0, 10);
    api.get.mockResolvedValue(_basePayload({
      paymentStatus: "unpaid", dueDate: yesterday,
    }));
    render(
      <MemoryRouter initialEntries={[`/i/${fakeJwt}`]}>
        <Routes>
          <Route path="/i/:token" element={<PublicInvoiceMagic />} />
        </Routes>
      </MemoryRouter>,
    );
    const stamp = await waitFor(() =>
      screen.getByTestId("invoice-stamp-past-due"),
    );
    expect(stamp).toBeTruthy();
  });
});
