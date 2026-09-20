/**
 * Phase A4 · Feb-2026 — Proactive Intelligence · IntelligenceAlerts
 * page: renewal_due row rendering (manual + auto-renew) + View
 * agreement / Resend renewal email CTAs + Renewal Due chip filter.
 *
 * Strategy — ``vi.mock`` on api + useNavigate + sonner.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";


const getMock  = vi.fn();
const postMock = vi.fn();
const navigateMock = vi.fn();
const toastSuccess = vi.fn();
const toastError   = vi.fn();

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

vi.mock("sonner", () => ({
  toast: { success: (...a) => toastSuccess(...a),
             error:   (...a) => toastError(...a) },
}));


import IntelligenceAlerts from "@/pages/admin/IntelligenceAlerts";


const _RENEWAL_MANUAL = {
  id:           "alert-renew-manual-1",
  severity:     "recommended",
  category:     "renewal_due",
  title:        "Renewal due: Priya Patel — Weekly Pool Cleaning",
  body:         "Agreement expires 2026-03-14 (30 days). Renewal proposal emailed.",
  customer_id:  "cust-42",
  job_id:       null,
  created_at:   new Date().toISOString(),
  read_at:      null,
  dismissed_at: null,
  actor_context: {
    agreement_id:          "agr-1",
    plan_id:               "plan-1",
    plan_name:             "Weekly Pool Cleaning",
    plan_kind:             "maintenance_contract",
    monthly_amount_cents:  8900,
    expires_at:            "2026-03-14",
    expires_at_short:      "2026-03-14",
    days_left:             30,
    auto_renew:            false,
    email_sent_to:         "priya@example.test",
  },
};
const _RENEWAL_AUTO = {
  ..._RENEWAL_MANUAL,
  id:           "alert-renew-auto-1",
  title:        "Renewal due: Alex Adams — Monthly Service Membership (auto-renew)",
  body:         "Auto-renews on 2026-03-14. Confirmation will be sent.",
  actor_context: {
    ..._RENEWAL_MANUAL.actor_context,
    agreement_id:          "agr-auto-1",
    plan_id:               "plan-2",
    plan_name:             "Monthly Service Membership",
    monthly_amount_cents:  7900,
    auto_renew:            true,
    email_sent_to:         null,
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
  toastSuccess.mockReset();
  toastError.mockReset();
});

afterEach(() => cleanup());


describe("IntelligenceAlerts · A4 renewal_due · manual row", () => {
  it("renders 'View agreement' + 'Resend renewal email' buttons", async () => {
    getMock.mockResolvedValue(_mkResponse([_RENEWAL_MANUAL]));
    _render();
    expect(await screen.findByTestId("intelligence-alerts-renewal-view-0"))
      .toBeInTheDocument();
    expect(screen.getByTestId("intelligence-alerts-renewal-resend-0"))
      .toBeInTheDocument();
  });

  it("View agreement navigates to /customers/{cid}?tab=warranties&highlight=…", async () => {
    getMock.mockResolvedValue(_mkResponse([_RENEWAL_MANUAL]));
    _render();
    fireEvent.click(await screen.findByTestId(
      "intelligence-alerts-renewal-view-0"));
    expect(navigateMock).toHaveBeenCalledTimes(1);
    const url = navigateMock.mock.calls[0][0];
    expect(url.startsWith(`/customers/${_RENEWAL_MANUAL.customer_id}?`))
      .toBe(true);
    const qs = new URLSearchParams(url.split("?")[1]);
    expect(qs.get("tab")).toBe("warranties");
    expect(qs.get("highlight")).toBe(
      _RENEWAL_MANUAL.actor_context.agreement_id);
    expect(qs.get("source")).toBe("intelligence_alert");
    expect(qs.get("alert_id")).toBe(_RENEWAL_MANUAL.id);
  });

  it("renders summary chip with plan, monthly amount, and expires date", async () => {
    getMock.mockResolvedValue(_mkResponse([_RENEWAL_MANUAL]));
    _render();
    await screen.findByTestId("renewal-due-summary");
    expect(screen.getByTestId("renewal-plan").textContent)
      .toBe("Weekly Pool Cleaning");
    expect(screen.getByTestId("renewal-price").textContent)
      .toBe("$89.00/mo");
    expect(screen.getByTestId("renewal-when").textContent)
      .toContain("2026-03-14");
    // Manual renewal ⇒ NO auto-renew badge.
    expect(screen.queryByTestId("renewal-auto-badge")).toBeNull();
  });
});


describe("IntelligenceAlerts · A4 renewal_due · auto-renew row", () => {
  it("shows AUTO-RENEW badge instead of 'expires' prefix", async () => {
    getMock.mockResolvedValue(_mkResponse([_RENEWAL_AUTO]));
    _render();
    await screen.findByTestId("renewal-due-summary");
    const badge = screen.getByTestId("renewal-auto-badge");
    expect(badge.textContent).toBe("AUTO-RENEW");
    expect(screen.getByTestId("renewal-plan").textContent)
      .toBe("Monthly Service Membership");
    expect(screen.getByTestId("renewal-price").textContent)
      .toBe("$79.00/mo");
    expect(screen.getByTestId("renewal-when").textContent)
      .toContain("2026-03-14");
  });
});


describe("IntelligenceAlerts · A4 renewal_due · Resend action", () => {
  it("Resend button POSTs to /agreements/{id}/resend-renewal-email and toasts success", async () => {
    getMock.mockResolvedValue(_mkResponse([_RENEWAL_MANUAL]));
    postMock.mockResolvedValue({ ok: true,
                                    sent_to: "priya@example.test",
                                    auto_renew: false });
    _render();
    fireEvent.click(await screen.findByTestId(
      "intelligence-alerts-renewal-resend-0"));
    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith(
        `/agreements/${_RENEWAL_MANUAL.actor_context.agreement_id}/resend-renewal-email`,
      );
    });
    await waitFor(() => {
      expect(toastSuccess).toHaveBeenCalled();
    });
    const msg = toastSuccess.mock.calls[0][0];
    expect(String(msg)).toContain("priya@example.test");
  });

  it("Resend surface toasts an error when the API returns ok=false", async () => {
    getMock.mockResolvedValue(_mkResponse([_RENEWAL_MANUAL]));
    postMock.mockResolvedValue({ ok: false, reason: "contract_inactive" });
    _render();
    fireEvent.click(await screen.findByTestId(
      "intelligence-alerts-renewal-resend-0"));
    await waitFor(() => {
      expect(toastError).toHaveBeenCalled();
    });
    expect(String(toastError.mock.calls[0][0])).toContain("contract_inactive");
  });
});


describe("IntelligenceAlerts · A4 renewal_due · category filter", () => {
  it("clicking Renewal Due chip issues ?category=renewal_due", async () => {
    getMock.mockResolvedValue(_mkResponse([
      _RENEWAL_MANUAL, _MISSED_ALERT]));
    _render();
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId(
      "intelligence-alerts-cat-renewal_due"));
    await waitFor(() => {
      const call = getMock.mock.calls.find(
        (c) => c[0].includes("category=renewal_due"));
      expect(call).toBeDefined();
    });
  });

  it("does NOT render renewal CTAs / summary on non-renewal rows", async () => {
    getMock.mockResolvedValue(_mkResponse([_MISSED_ALERT]));
    _render();
    await screen.findByTestId("intelligence-alerts-row-0");
    expect(screen.queryByTestId("intelligence-alerts-renewal-view-0")).toBeNull();
    expect(screen.queryByTestId("intelligence-alerts-renewal-resend-0")).toBeNull();
    expect(screen.queryByTestId("renewal-due-summary")).toBeNull();
    expect(screen.queryByTestId("renewal-auto-badge")).toBeNull();
  });
});
