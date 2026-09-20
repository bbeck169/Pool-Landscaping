/**
 * Phase A3 · Feb-2026 — Proactive Intelligence · IntelligenceAlerts
 * page: churn-risk row rendering (both signals) + CTA deep-links +
 * summary chips + Churn Risk category chip filter.
 *
 * Strategy — ``vi.mock`` on api + useNavigate.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";


const getMock  = vi.fn();
const postMock = vi.fn();
const navigateMock = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get:  (...args) => getMock(...args),
    post: (...args) => postMock(...args),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff",
    surfaceSecondary: "#F4F4F5",
    border: "#E4E4E7",
    muted: "#71717A",
    onSurface: "#09090B",
    brand: "#0284C7",
    onBrand: "#FFFFFF",
    onBrandPrimary: "#FFFFFF",
  },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});


import IntelligenceAlerts from "@/pages/admin/IntelligenceAlerts";


const _CHURN_MISSED_PAYMENTS = {
  id:           "alert-churn-mp-1",
  severity:     "urgent",
  category:     "churn_risk",
  title:        "Payment risk: Robert Blake (2 unpaid invoices)",
  body:         "2 invoices past due totaling $350.00. Recommend collections outreach.",
  customer_id:  "cust-42",
  job_id:       null,
  created_at:   new Date().toISOString(),
  read_at:      null,
  dismissed_at: null,
  actor_context: {
    signal:              "missed_payments",
    invoice_count:       2,
    total_amount_cents:  35000,
    oldest_days_overdue: 45,
    invoice_ids:         ["inv-1", "inv-2"],
  },
};
const _CHURN_RECURRING_CANCELLED = {
  id:           "alert-churn-rc-1",
  severity:     "recommended",
  category:     "churn_risk",
  title:        "Churn risk: Priya Patel cancelled recurring service",
  body:         "Weekly Pool Cleaning recurring series cancelled on 2026-02-14. Recommend save-the-account outreach.",
  customer_id:  "cust-9",
  job_id:       "job-77",
  created_at:   new Date().toISOString(),
  read_at:      null,
  dismissed_at: null,
  actor_context: {
    signal:              "recurring_cancelled",
    job_id:              "job-77",
    service_type:        "Weekly Pool Cleaning",
    cancelled_at_short:  "2026-02-14",
    cancellation_reason: "Customer moved",
  },
};
const _MISSED_ALERT = {
  id:            "alert-missed-1",
  severity:      "urgent",
  category:      "missed_service",
  title:         "Missed service · Sunbelt Pools",
  body:          "Route T-3 skipped yesterday.",
  customer_id:   "cust-9",
  job_id:        "job-11",
  created_at:    new Date().toISOString(),
  read_at:       null,
  dismissed_at:  null,
  actor_context: {},
};


function _mkResponse(items, unread = items.length) {
  return { items, limit: 25, unread_count: unread, next_before: null };
}
function _render() {
  return render(
    <MemoryRouter>
      <IntelligenceAlerts />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  navigateMock.mockReset();
});

afterEach(() => cleanup());


describe("IntelligenceAlerts · A3 churn-risk · missed_payments row", () => {
  it("renders the 'View invoices' CTA", async () => {
    getMock.mockResolvedValue(_mkResponse([_CHURN_MISSED_PAYMENTS]));
    _render();
    const cta = await screen.findByTestId("intelligence-alerts-churn-cta-0");
    expect(cta).toBeInTheDocument();
    expect(cta.getAttribute("data-signal")).toBe("missed_payments");
    expect(cta.textContent).toContain("View invoices");
  });

  it("navigates to /customers/{cid}?tab=invoices&status=past_due,overdue on click", async () => {
    getMock.mockResolvedValue(_mkResponse([_CHURN_MISSED_PAYMENTS]));
    _render();
    const cta = await screen.findByTestId("intelligence-alerts-churn-cta-0");
    fireEvent.click(cta);
    expect(navigateMock).toHaveBeenCalledTimes(1);
    const url = navigateMock.mock.calls[0][0];
    expect(url.startsWith(`/customers/${_CHURN_MISSED_PAYMENTS.customer_id}?`))
      .toBe(true);
    const qs = new URLSearchParams(url.split("?")[1]);
    expect(qs.get("tab")).toBe("invoices");
    expect(qs.get("status")).toBe("past_due,overdue");
    expect(qs.get("source")).toBe("intelligence_alert");
    expect(qs.get("alert_id")).toBe(_CHURN_MISSED_PAYMENTS.id);
  });

  it("renders the summary chip with total, count, and days-overdue", async () => {
    getMock.mockResolvedValue(_mkResponse([_CHURN_MISSED_PAYMENTS]));
    _render();
    await screen.findByTestId("churn-risk-summary-missed-payments");
    expect(screen.getByTestId("churn-risk-total").textContent).toBe("$350.00");
    expect(screen.getByTestId("churn-risk-count").textContent).toBe("2 invoices");
    expect(screen.getByTestId("churn-risk-oldest").textContent)
      .toBe("oldest 45d overdue");
  });
});


describe("IntelligenceAlerts · A3 churn-risk · recurring_cancelled row", () => {
  it("renders the 'Contact customer' CTA", async () => {
    getMock.mockResolvedValue(_mkResponse([_CHURN_RECURRING_CANCELLED]));
    _render();
    const cta = await screen.findByTestId("intelligence-alerts-churn-cta-0");
    expect(cta.getAttribute("data-signal")).toBe("recurring_cancelled");
    expect(cta.textContent).toContain("Contact customer");
  });

  it("navigates to the customer page with compose=email + subject prefill", async () => {
    getMock.mockResolvedValue(_mkResponse([_CHURN_RECURRING_CANCELLED]));
    _render();
    const cta = await screen.findByTestId("intelligence-alerts-churn-cta-0");
    fireEvent.click(cta);
    const url = navigateMock.mock.calls[0][0];
    expect(url.startsWith(`/customers/${_CHURN_RECURRING_CANCELLED.customer_id}?`))
      .toBe(true);
    const qs = new URLSearchParams(url.split("?")[1]);
    expect(qs.get("compose")).toBe("email");
    expect(qs.get("subject")).toBe(
      "We noticed you cancelled — how can we help?");
    expect(qs.get("source")).toBe("intelligence_alert");
    expect(qs.get("alert_id")).toBe(_CHURN_RECURRING_CANCELLED.id);
  });

  it("renders the summary chip with service_type + cancelled date", async () => {
    getMock.mockResolvedValue(_mkResponse([_CHURN_RECURRING_CANCELLED]));
    _render();
    await screen.findByTestId("churn-risk-summary-recurring-cancelled");
    expect(screen.getByTestId("churn-risk-service").textContent)
      .toBe("Weekly Pool Cleaning");
    expect(screen.getByTestId("churn-risk-when").textContent)
      .toContain("2026-02-14");
  });
});


describe("IntelligenceAlerts · A3 churn-risk · category filter", () => {
  it("clicking the Churn Risk chip issues ?category=churn_risk", async () => {
    getMock.mockResolvedValue(_mkResponse([
      _CHURN_MISSED_PAYMENTS, _MISSED_ALERT]));
    _render();
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId(
      "intelligence-alerts-cat-churn_risk"));
    await waitFor(() => {
      const call = getMock.mock.calls.find(
        (c) => c[0].includes("category=churn_risk"));
      expect(call).toBeDefined();
    });
  });

  it("renders only churn rows when the API returns that filter", async () => {
    getMock.mockResolvedValueOnce(_mkResponse([
      _CHURN_MISSED_PAYMENTS, _MISSED_ALERT]));
    getMock.mockResolvedValue(_mkResponse([
      _CHURN_MISSED_PAYMENTS, _CHURN_RECURRING_CANCELLED]));
    _render();
    await screen.findByTestId("intelligence-alerts-row-0");
    fireEvent.click(screen.getByTestId(
      "intelligence-alerts-cat-churn_risk"));
    await waitFor(() => {
      const rows = [
        screen.queryByTestId("intelligence-alerts-row-0"),
        screen.queryByTestId("intelligence-alerts-row-1"),
      ];
      expect(rows[0]).not.toBeNull();
      expect(rows[1]).not.toBeNull();
      expect(rows[0].getAttribute("data-category")).toBe("churn_risk");
      expect(rows[1].getAttribute("data-category")).toBe("churn_risk");
    });
  });

  it("does NOT render churn CTA or summary on non-churn rows", async () => {
    getMock.mockResolvedValue(_mkResponse([_MISSED_ALERT]));
    _render();
    await screen.findByTestId("intelligence-alerts-row-0");
    expect(screen.queryByTestId("intelligence-alerts-churn-cta-0")).toBeNull();
    expect(screen.queryByTestId(
      "churn-risk-summary-missed-payments")).toBeNull();
    expect(screen.queryByTestId(
      "churn-risk-summary-recurring-cancelled")).toBeNull();
  });
});
