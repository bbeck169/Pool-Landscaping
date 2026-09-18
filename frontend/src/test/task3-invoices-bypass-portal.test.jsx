/**
 * Feb-2026 · Task 3 · Invoices bypass portal — Vitest coverage.
 *
 * 1. `/i/:token` decodes the JWT payload → renders `InvoiceView`
 *    with the extracted `invoice_id` + `magicToken` props.
 * 2. Invalid/malformed token → `public-invoice-magic-invalid-token`.
 * 3. Portal invoice detail: customer role auto-redirects to
 *    `/i/:token` via `GET /invoices/:id/magic-link`.
 * 4. Portal invoice detail: staff role (admin) stays put — no redirect.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";

const { getSpy, postSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(), postSpy: vi.fn(), patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
    del: vi.fn(),
  },
}));

vi.mock("@/components/InvoiceView", () => ({
  __esModule: true,
  default: ({ invoiceId, magicToken, magicSrc, printable }) => (
    <div
      data-testid="mocked-invoice-view"
      data-invoice-id={invoiceId || ""}
      data-magic-token={magicToken || ""}
      data-magic-src={magicSrc || ""}
      data-printable={printable ? "1" : "0"}
    >
      Mocked InvoiceView
    </div>
  ),
}));

let _currentRole = "customer";
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { role: _currentRole, customer_id: "cust-1", tenant_id: "t1" },
  }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

// The portal file pulls many heavy components — mock the shell down.
vi.mock("@/components/PaymentForm", () => ({
  __esModule: true,
  default: () => <div data-testid="mocked-payment-form" />,
}));

import PublicInvoiceMagic from "@/pages/public/PublicInvoiceMagic";
import { PortalInvoiceDetail } from "@/pages/portal/PortalPages";


/** Build a fake HS256 JWT with the given payload — signature is bogus. */
function makeToken(payload) {
  const b64 = (obj) =>
    Buffer.from(JSON.stringify(obj), "utf-8")
      .toString("base64")
      .replace(/=/g, "")
      .replace(/\+/g, "-")
      .replace(/\//g, "_");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(payload)}.abc`;
}

function LocationSpy() {
  const loc = useLocation();
  return <div data-testid="loc-pathname">{loc.pathname}</div>;
}


describe("PublicInvoiceMagic (`/i/:token`)", () => {
  beforeEach(() => {
    getSpy.mockReset();
    // Sprint 3a · Feb 2026 — the component's useEffect fires
    // ``api.get(url).then(...)`` on mount. ``vi.fn()`` returns
    // ``undefined`` by default which crashes ``.then``. Set a
    // no-op resolved Promise so the token-decode test (which
    // doesn't otherwise care about the /full-magic GET) doesn't
    // blow up on the effect. Individual tests can still override
    // this via ``getSpy.mockImplementation(...)`` when they need
    // specific responses.
    getSpy.mockResolvedValue({});
    _currentRole = "customer";
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("decodes token → passes invoice_id + magicToken to InvoiceView", async () => {
    const token = makeToken({
      sub: "invoice_pay",
      invoice_id: "inv-777",
      tenant_id: "t1",
    });
    render(
      <MemoryRouter initialEntries={[`/i/${token}`]}>
        <Routes>
          <Route path="/i/:token" element={<PublicInvoiceMagic />} />
        </Routes>
      </MemoryRouter>,
    );
    const root = await screen.findByTestId("public-invoice-magic-root");
    expect(root).toBeInTheDocument();
    const view = screen.getByTestId("mocked-invoice-view");
    expect(view.dataset.invoiceId).toBe("inv-777");
    expect(view.dataset.magicToken).toBe(token);
    expect(view.dataset.magicSrc).toBe("link");
  });

  it("shows invalid-token banner for malformed JWT", async () => {
    render(
      <MemoryRouter initialEntries={["/i/not-a-jwt"]}>
        <Routes>
          <Route path="/i/:token" element={<PublicInvoiceMagic />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(
      await screen.findByTestId("public-invoice-magic-invalid-token"),
    ).toBeInTheDocument();
  });
});


describe("PortalInvoiceDetail (Task 3 — customer bypass)", () => {
  beforeEach(() => {
    getSpy.mockReset();
    // Sprint 3a · Feb 2026 — same default as the sibling describe
    // block; component effects call ``api.get`` on mount and
    // ``vi.fn()`` returning ``undefined`` breaks ``.then``.
    getSpy.mockResolvedValue({});
    _currentRole = "customer";
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("customer role redirects to /i/:token on mount", async () => {
    _currentRole = "customer";
    const token = makeToken({
      sub: "invoice_pay", invoice_id: "inv-42", tenant_id: "t1",
    });
    getSpy.mockImplementation((url) => {
      if (url === "/invoices/inv-42/magic-link") {
        return Promise.resolve({
          invoice_id: "inv-42", token, url: `/i/${token}`, days_valid: 30,
        });
      }
      return Promise.resolve({});
    });

    render(
      <MemoryRouter initialEntries={["/portal/invoices/inv-42"]}>
        <Routes>
          <Route path="/portal/invoices/:id" element={<PortalInvoiceDetail />} />
          <Route path="/i/:token" element={<LocationSpy />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(getSpy).toHaveBeenCalledWith("/invoices/inv-42/magic-link");
    });
    // Router landed on /i/:token.
    await waitFor(() => {
      const el = screen.queryByTestId("loc-pathname");
      expect(el).not.toBeNull();
      expect(el.textContent).toBe(`/i/${token}`);
    });
  });

  it("admin role does NOT redirect — renders the portal InvoiceView", async () => {
    _currentRole = "admin";
    getSpy.mockImplementation(() => Promise.resolve({}));

    render(
      <MemoryRouter initialEntries={["/portal/invoices/inv-99"]}>
        <Routes>
          <Route path="/portal/invoices/:id" element={<PortalInvoiceDetail />} />
          <Route path="/i/:token" element={<LocationSpy />} />
        </Routes>
      </MemoryRouter>,
    );

    // InvoiceView renders (mocked).
    await waitFor(() =>
      expect(screen.getByTestId("mocked-invoice-view")).toBeInTheDocument(),
    );
    // magic-link fetch was NEVER attempted.
    const magicCalls = getSpy.mock.calls.filter(
      ([url]) => typeof url === "string" && url.endsWith("/magic-link"),
    );
    expect(magicCalls.length).toBe(0);
  });
});
