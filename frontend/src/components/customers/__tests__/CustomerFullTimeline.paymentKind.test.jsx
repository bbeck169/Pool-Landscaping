/**
 * TD-98-be-sources-payment-kind · frontend regression suite for the
 * ``payment`` kind reclassification.
 *
 * Scope lock per operator approval:
 *   - ``_KIND_META.payment`` renders CreditCard icon + green-tinted
 *     palette (bg=#D1FAE5, fg=#065F46) + "Payment" label.
 *   - ``_BASE_CHIPS`` includes ``payment`` — visible to portal + admin
 *     (NOT in ``_ADMIN_ONLY_CHIPS``).
 *   - Clicking the payment chip triggers a ``?kind=payment`` fetch.
 *   - ``DefaultRow`` renders ``$X.XX`` money chip when BE emits
 *     ``total > 0`` on a kind=payment row.
 *   - Regression: existing base chips (email, sms, invoice, estimate)
 *     still visible to all roles; admin-only chips (call, note) still
 *     admin-gated.
 *
 * Companion to ``CustomerFullTimeline.super.test.jsx`` which locks the
 * pre-reclassification chip set; this file locks the post-
 * reclassification additive ``payment`` chip + wire-through.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { getSpy, useAuthSpy } = vi.hoisted(() => ({
  getSpy:     vi.fn(),
  useAuthSpy: vi.fn(),
}));

vi.mock("@/api",   () => ({ api:      { get: (...a) => getSpy(...a) } }));
vi.mock("@/auth",  () => ({ useAuth:  () => useAuthSpy() }));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f8fafc", border: "#e5e7eb",
    onSurface: "#111827", muted: "#6b7280",
    brand: "#0284c7", onBrand: "#fff",
  },
}));


import CustomerFullTimeline
  from "@/components/customers/CustomerFullTimeline";


function _wrap(ui) { return <MemoryRouter>{ui}</MemoryRouter>; }


beforeEach(() => {
  getSpy.mockReset();
  useAuthSpy.mockReset();
});


// ═══════════════════════════════════════════════════════════════════
// §1 · _KIND_META.payment entry + KindPill render
// ═══════════════════════════════════════════════════════════════════
describe("TD-98-be-sources-payment-kind · KindPill rendering", () => {
  it("renders a Payment pill with the correct testid when a kind=payment row is present", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [{
        id: "aud-pk-1", kind: "payment",
        subject: "Invoice auto-charged",
        body: "System charged $123.45 USD to card on file · pi_…234567",
        created_at: "2026-10-21T10:00:00+00:00",
        occurred_at: "2026-10-21T10:00:00+00:00",
        source_type: "payment",
        delivery_status: "logged",
        total: 123.45,
        ref_type: "audit_event", ref_id: "aud-pk-1",
        url: "",
      }],
      page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const pill = await screen.findByTestId("timeline-pill-payment");
    expect(pill).toBeTruthy();
    expect(pill.textContent).toContain("Payment");
  });
});


// ═══════════════════════════════════════════════════════════════════
// §2 · _BASE_CHIPS includes payment — visible to admin AND portal
// ═══════════════════════════════════════════════════════════════════
describe("TD-98-be-sources-payment-kind · payment chip visibility", () => {
  it("admin session sees the payment chip in the filter row", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(screen.getByTestId("timeline-filter-payment")).toBeTruthy();
  });

  it("portal (customer) session sees the payment chip in the filter row (BE §4.d portal-visible)", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "customer" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="portal" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(screen.getByTestId("timeline-filter-payment")).toBeTruthy();
    // Regression lock: admin-only chips still hidden from portal.
    expect(screen.queryByTestId("timeline-filter-call")).toBeNull();
    expect(screen.queryByTestId("timeline-filter-note")).toBeNull();
  });

  it("technician session sees the payment chip (base chip, not admin-only)", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "technician" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(screen.getByTestId("timeline-filter-payment")).toBeTruthy();
  });
});


// ═══════════════════════════════════════════════════════════════════
// §3 · Clicking payment chip triggers ?kind=payment fetch
// ═══════════════════════════════════════════════════════════════════
describe("TD-98-be-sources-payment-kind · chip filter wire-through", () => {
  it("clicking the payment chip adds ?kind=payment to the fetch URL", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const initialCalls = getSpy.mock.calls.length;

    fireEvent.click(screen.getByTestId("timeline-filter-payment"));

    await waitFor(() =>
      expect(getSpy.mock.calls.length).toBeGreaterThan(initialCalls));
    const path = getSpy.mock.calls[getSpy.mock.calls.length - 1][0];
    expect(path).toContain("kind=payment");
  });
});


// ═══════════════════════════════════════════════════════════════════
// §4 · DefaultRow money chip wire-through — $X.XX surfaces when total>0
// ═══════════════════════════════════════════════════════════════════
describe("TD-98-be-sources-payment-kind · DefaultRow money display", () => {
  it("renders the $X.XX money chip on a kind=payment row when total > 0", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [{
        id: "aud-pk-money", kind: "payment",
        subject: "Invoice auto-charged",
        body: "System charged $42.00 USD to card on file · pi_…abcdef",
        created_at: "2026-10-21T10:00:00+00:00",
        occurred_at: "2026-10-21T10:00:00+00:00",
        source_type: "payment",
        delivery_status: "logged",
        total: 42,
        ref_type: "audit_event", ref_id: "aud-pk-money",
        url: "",
      }],
      page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const subject = await screen.findByTestId("timeline-subject-0");
    expect(subject.textContent).toContain("Invoice auto-charged");
    // The DefaultRow money chip renders "$42.00" (toFixed(2)) when
    // total is numeric and > 0. We assert on the rendered text in
    // the subject row's parent container.
    const row = subject.closest("div.flex-1") || subject.parentElement;
    expect(row?.textContent).toContain("$42.00");
  });

  it("does NOT render the money chip when total is 0 or missing", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [{
        id: "aud-pk-zero", kind: "payment",
        subject: "Invoice auto-charged (no amount)",
        body: "System charged $0.00 USD to card on file · pi_…",
        created_at: "2026-10-21T10:00:00+00:00",
        occurred_at: "2026-10-21T10:00:00+00:00",
        source_type: "payment",
        delivery_status: "logged",
        total: 0,
        ref_type: "audit_event", ref_id: "aud-pk-zero",
        url: "",
      }],
      page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const subject = await screen.findByTestId("timeline-subject-0");
    const row = subject.closest("div.flex-1") || subject.parentElement;
    // Subject body contains "$0.00" from the backend-composed body,
    // but the standalone money chip rendered by DefaultRow should NOT
    // emit when total ≤ 0. We assert via regex to catch the chip
    // (which would appear separately from the body string). The
    // body string containing "$0.00" is in a different element.
    const moneyChipMatches = row?.querySelectorAll("span.text-xs.font-semibold");
    const hasMoneyChip = Array.from(moneyChipMatches || []).some(
      el => /^\$\d/.test(el.textContent.trim()));
    expect(hasMoneyChip).toBe(false);
  });
});


// ═══════════════════════════════════════════════════════════════════
// §5 · Regression — existing base chips still visible to all roles
// ═══════════════════════════════════════════════════════════════════
describe("TD-98-be-sources-payment-kind · regression on existing chips", () => {
  it("admin session still sees all pre-payment base chips + admin chips", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    for (const k of ["all", "email", "sms", "invoice", "estimate",
                       "payment", "call", "note"]) {
      expect(screen.getByTestId(`timeline-filter-${k}`)).toBeTruthy();
    }
  });

  it("portal session still hides admin-only chips (call + note)", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "customer" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="portal" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    // All base chips (including new payment) visible.
    for (const k of ["all", "email", "sms", "invoice", "estimate", "payment"]) {
      expect(screen.getByTestId(`timeline-filter-${k}`)).toBeTruthy();
    }
    // Admin-only chips hidden.
    expect(screen.queryByTestId("timeline-filter-call")).toBeNull();
    expect(screen.queryByTestId("timeline-filter-note")).toBeNull();
  });
});
