/**
 * CUSTOMER-DETAIL-NEXT-SERVICE · Feb-2026 — Vitest coverage for the
 * ``NextServiceTile`` inline component mounted on CustomerDetail
 * between the Phase 27 KPI tile grid and the Phase 27 Quick
 * Actions tile grid.
 *
 * 3 cases:
 *   (i)   Renders with an upcoming job — date/service_type/tech
 *         fields visible + ``<StatusPill>`` present; whole card
 *         click → navigate(`/jobs/${job.id}`).
 *   (ii)  Renders empty state + "Schedule a job" CTA when the
 *         endpoint returns ``{next_service: null}``.
 *   (iii) Empty-state CTA click → navigate(`/jobs/new?customer_id=<id>`).
 *
 * Pattern follows ``archive-category-count-link.test.jsx`` +
 * ``manageAutomationsTab.test.jsx``: ``vi.hoisted`` spies for
 * ``api.get`` + ``useNavigate`` mock.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";

const mockGet = vi.fn();
const mockNavigate = vi.fn();

vi.mock("@/api", () => ({
  api: { get: (...a) => mockGet(...a) },
}));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});
// CustomerDetail.jsx transitively uses the dynamic breadcrumb
// context + ``useAuth``.  Neither is exercised by the isolated
// ``<NextServiceTile>`` mount, but their module-load must not
// throw.  The real exports work in the vitest JSDOM environment,
// so no additional mocks are needed beyond the two above.

import { NextServiceTile } from "@/pages/customers/CustomerDetail";

beforeEach(() => {
  mockGet.mockReset();
  mockNavigate.mockReset();
  cleanup();
});

describe("NextServiceTile · CUSTOMER-DETAIL-NEXT-SERVICE", () => {
  it("case (i) · renders upcoming job fields + click navigates to /jobs/:id", async () => {
    // Pin a near-future scheduled_start so the formatted
    // date/time string is deterministic across timezones; we
    // assert on structural testids, not the formatted text.
    const futureIso = new Date(
      Date.now() + 24 * 60 * 60 * 1000,
    ).toISOString();
    mockGet.mockImplementation((url) => {
      if (url === "/customers/cust-abc/next-service") {
        return Promise.resolve({
          next_service: {
            id: "job-xyz",
            tenant_id: "t-1",
            customer_id: "cust-abc",
            status: "scheduled",
            service_type: "Pool cleaning",
            title: "Weekly maintenance visit",
            technician_name: "Mike Rowe",
            scheduled_start: futureIso,
            scheduled_date: futureIso.slice(0, 10),
          },
        });
      }
      return Promise.resolve({});
    });

    render(<NextServiceTile customerId="cust-abc" />);

    // Wait for the fetch to resolve + the has-job branch to render.
    // The tile's testid is shared across loading/empty/has-job
    // branches, so re-query inside waitFor to see the flipped
    // ``data-state`` attribute.
    await waitFor(() => {
      const t = screen.getByTestId("cd-next-service-tile");
      expect(t.getAttribute("data-state")).toBe("has-job");
    });
    const tile = screen.getByTestId("cd-next-service-tile");

    // All four field testids must be present on the has-job
    // branch.  Service type / tech values locked verbatim; date
    // is locale-formatted so we just assert non-empty.
    const dateEl = screen.getByTestId("cd-next-service-date");
    expect(dateEl.textContent.trim().length).toBeGreaterThan(0);
    expect(dateEl.textContent.trim()).not.toBe("—");

    expect(
      screen.getByTestId("cd-next-service-service-type").textContent,
    ).toContain("Pool cleaning");
    expect(
      screen.getByTestId("cd-next-service-tech").textContent,
    ).toContain("Mike Rowe");

    // StatusPill wrapper is present — the pill itself is the
    // real @/components/ui-kit export, so we assert the wrapper
    // exists; content assertions on the pill are owned by the
    // ui-kit's own test suite.
    expect(
      screen.getByTestId("cd-next-service-status-pill"),
    ).toBeTruthy();

    // Whole card is a <button>; clicking it navigates to the
    // canonical schedule-row destination.
    fireEvent.click(tile);
    expect(mockNavigate).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith("/jobs/job-xyz");
  });

  it("case (ii) · renders empty state + CTA when next_service is null", async () => {
    mockGet.mockImplementation((url) => {
      if (url === "/customers/cust-empty/next-service") {
        return Promise.resolve({ next_service: null });
      }
      return Promise.resolve({});
    });

    render(<NextServiceTile customerId="cust-empty" />);

    await waitFor(() => {
      const t = screen.getByTestId("cd-next-service-tile");
      expect(t.getAttribute("data-state")).toBe("empty");
    });

    expect(
      screen.getByTestId("cd-next-service-empty").textContent,
    ).toContain("No upcoming services");
    expect(
      screen.getByTestId("cd-next-service-schedule-cta"),
    ).toBeTruthy();

    // Empty-state tile must NOT render the has-job sub-elements.
    expect(screen.queryByTestId("cd-next-service-date")).toBeNull();
    expect(screen.queryByTestId("cd-next-service-tech")).toBeNull();
  });

  it("case (iii) · CTA click navigates to /jobs/new with customer prefilled", async () => {
    mockGet.mockImplementation(() =>
      Promise.resolve({ next_service: null }),
    );

    render(<NextServiceTile customerId="cust-999" />);

    const cta = await screen.findByTestId(
      "cd-next-service-schedule-cta",
    );
    fireEvent.click(cta);

    expect(mockNavigate).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith(
      "/jobs/new?customer_id=cust-999",
    );
  });
});
