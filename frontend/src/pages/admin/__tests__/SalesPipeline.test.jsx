/**
 * Phase C · Feb-2026 · Sales Pipeline Kanban — vitest suite.
 *
 * Scope
 * -----
 * 1. Renders 5 column headers with correct labels.
 * 2. Column dollar totals formatted as ``$1,234.56``.
 * 3. Card click navigates to the correct detail page by source.
 * 4. Risk swimlane renders when non-empty; hidden empty-state
 *    message shows when swimlane is empty.
 * 5. Risk card click navigates to
 *    ``/admin/intelligence/alerts?category=…&highlight=…``.
 * 6. Filter bar changes trigger a refetch with correct query params.
 * 7. Skeleton pulse renders before data lands.
 * 8. Empty state per column when count is 0.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";


const getMock       = vi.fn();
const navigateMock  = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get:  (...args) => getMock(...args),
    post: () => Promise.resolve({}),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff",
    surfaceSecondary: "#F4F4F5",
    border: "#E4E4E7",
    borderStrong: "#D4D4D8",
    muted: "#71717A",
    onSurface: "#09090B",
    onSurfaceSecondary: "#52525B",
    brand: "#0284C7",
    error: "#DC2626",
    warning: "#CA8A04",
  },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});


import SalesPipeline from "@/pages/admin/SalesPipeline";


function _mkColumn(key, label, cards = [], total = 0, currency = "USD") {
  return {
    key,
    label,
    total_amount_cents: total,
    total_currency: currency,
    count: cards.length,
    cards,
  };
}


function _mkCard(source, id, overrides = {}) {
  return {
    id,
    source,
    customer_id: `cust-${id}`,
    customer_name: `Cust ${id}`,
    title: `Card ${id}`,
    amount_cents: 12345,
    currency: "USD",
    assigned_to_display_name: null,
    status: source === "lead" ? "new" : "sent",
    occurred_at: new Date().toISOString(),
    risk_alert_id: null,
    risk_category: null,
    risk_severity: null,
    ...overrides,
  };
}


function _mkResponse({ columns = null, swim = [] } = {}) {
  const cols = columns || [
    _mkColumn("leads",     "Leads",     [], 0),
    _mkColumn("quoted",    "Quoted",    [], 0),
    _mkColumn("scheduled", "Scheduled", [], 0),
    _mkColumn("completed", "Completed", [], 0),
    _mkColumn("follow_up", "Follow-up", [], 0),
  ];
  return {
    columns: cols,
    risk_swimlane: swim,
    generated_at: new Date().toISOString(),
  };
}


function _render() {
  return render(
    <MemoryRouter>
      <SalesPipeline />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  getMock.mockReset();
  navigateMock.mockReset();
  // Default: /technicians returns empty list; /pipeline/kanban returns
  // an empty payload unless the test override arrives first.
  getMock.mockImplementation((url) => {
    if (String(url).startsWith("/technicians")) return Promise.resolve([]);
    if (String(url).startsWith("/pipeline/kanban")) {
      return Promise.resolve(_mkResponse());
    }
    return Promise.resolve({});
  });
});

afterEach(() => cleanup());


describe("SalesPipeline · column headers", () => {
  it("renders 5 column headers with correct labels", async () => {
    _render();
    await waitFor(() => {
      for (const k of ["leads", "quoted", "scheduled",
                        "completed", "follow_up"]) {
        expect(screen.getByTestId(
          `pipeline-column-header-${k}`)).toBeInTheDocument();
      }
    });
    expect(screen.getByTestId(
      "pipeline-column-header-leads").textContent).toContain("Leads");
    expect(screen.getByTestId(
      "pipeline-column-header-quoted").textContent).toContain("Quoted");
    expect(screen.getByTestId(
      "pipeline-column-header-scheduled").textContent).toContain("Scheduled");
    expect(screen.getByTestId(
      "pipeline-column-header-completed").textContent).toContain("Completed");
    expect(screen.getByTestId(
      "pipeline-column-header-follow_up").textContent).toContain("Follow-up");
  });

  it("formats the column dollar totals as $1,234.56", async () => {
    getMock.mockImplementation((url) => {
      if (String(url).startsWith("/technicians")) return Promise.resolve([]);
      if (String(url).startsWith("/pipeline/kanban")) {
        return Promise.resolve(_mkResponse({
          columns: [
            _mkColumn("leads", "Leads", [_mkCard("lead", "L1")], 123456),
            _mkColumn("quoted", "Quoted", [], 0),
            _mkColumn("scheduled", "Scheduled", [], 0),
            _mkColumn("completed", "Completed", [], 0),
            _mkColumn("follow_up", "Follow-up", [], 0),
          ],
        }));
      }
      return Promise.resolve({});
    });
    _render();
    const total = await screen.findByTestId("pipeline-column-total-leads");
    expect(total.textContent).toMatch(/1,234\.56/);
    expect(total.textContent).toMatch(/\$/);
  });
});


describe("SalesPipeline · card click routing", () => {
  const cases = [
    ["lead",  "L1", "/leads/L1"],
    ["quote", "Q1", "/quotes/Q1"],
    ["job",   "J1", "/jobs/J1"],
  ];
  it.each(cases)("card source=%s navigates to %s", async (src, id, href) => {
    getMock.mockImplementation((url) => {
      if (String(url).startsWith("/technicians")) return Promise.resolve([]);
      if (String(url).startsWith("/pipeline/kanban")) {
        return Promise.resolve(_mkResponse({
          columns: [
            _mkColumn("leads",     "Leads",
                        src === "lead"  ? [_mkCard("lead",  id)] : [], 0),
            _mkColumn("quoted",    "Quoted",
                        src === "quote" ? [_mkCard("quote", id)] : [], 0),
            _mkColumn("scheduled", "Scheduled",
                        src === "job"   ? [_mkCard("job",   id)] : [], 0),
            _mkColumn("completed", "Completed", [], 0),
            _mkColumn("follow_up", "Follow-up", [], 0),
          ],
        }));
      }
      return Promise.resolve({});
    });
    _render();
    const card = await screen.findByTestId(`pipeline-card-${src}-${id}`);
    fireEvent.click(card);
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock.mock.calls[0][0]).toBe(href);
  });
});


describe("SalesPipeline · risk swimlane", () => {
  it("renders swimlane when non-empty and hides empty-state msg", async () => {
    const swimCard = _mkCard("alert", "A1", {
      risk_alert_id: "A1",
      risk_category: "churn_risk",
      risk_severity: "recommended",
    });
    getMock.mockImplementation((url) => {
      if (String(url).startsWith("/technicians")) return Promise.resolve([]);
      if (String(url).startsWith("/pipeline/kanban")) {
        return Promise.resolve(_mkResponse({ swim: [swimCard] }));
      }
      return Promise.resolve({});
    });
    _render();
    await waitFor(() => {
      expect(screen.getByTestId(
        "pipeline-risk-swimlane")).toBeInTheDocument();
    });
    expect(screen.queryByTestId(
      "pipeline-risk-swimlane-empty")).toBeNull();
    // Card exists in swimlane.
    expect(screen.getByTestId(
      "pipeline-risk-card-A1")).toBeInTheDocument();
  });

  it("renders the empty-state msg when swimlane is empty", async () => {
    _render();
    await waitFor(() => {
      expect(screen.getByTestId(
        "pipeline-risk-swimlane-empty")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("pipeline-risk-swimlane")).toBeNull();
  });

  it("risk card click navigates with correct query params", async () => {
    const swimCard = _mkCard("alert", "A1", {
      risk_alert_id: "A1",
      risk_category: "churn_risk",
      risk_severity: "urgent",
    });
    getMock.mockImplementation((url) => {
      if (String(url).startsWith("/technicians")) return Promise.resolve([]);
      if (String(url).startsWith("/pipeline/kanban")) {
        return Promise.resolve(_mkResponse({ swim: [swimCard] }));
      }
      return Promise.resolve({});
    });
    _render();
    const card = await screen.findByTestId("pipeline-risk-card-A1");
    fireEvent.click(card);
    expect(navigateMock).toHaveBeenCalledTimes(1);
    const url = navigateMock.mock.calls[0][0];
    expect(url).toMatch(/^\/admin\/intelligence\/alerts\?/);
    const qs = new URLSearchParams(url.split("?")[1]);
    expect(qs.get("category")).toBe("churn_risk");
    expect(qs.get("highlight")).toBe("A1");
  });
});


describe("SalesPipeline · filter bar", () => {
  it("changing date_from triggers a refetch with date_from in query", async () => {
    _render();
    // Wait for first fetch.
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    const input = screen.getByTestId("pipeline-filter-date-from");
    fireEvent.change(input, { target: { value: "2026-01-15" } });
    await waitFor(() => {
      const call = getMock.mock.calls.find((c) =>
        String(c[0]).includes("date_from=2026-01-15"));
      expect(call).toBeDefined();
    });
  });

  it("changing owner triggers a refetch with owner_id in query", async () => {
    getMock.mockImplementation((url) => {
      if (String(url).startsWith("/technicians")) {
        return Promise.resolve([{ id: "u1", technician_id: "t1",
                                     name: "Terry Tech" }]);
      }
      if (String(url).startsWith("/pipeline/kanban")) {
        return Promise.resolve(_mkResponse());
      }
      return Promise.resolve({});
    });
    _render();
    await waitFor(() => {
      expect(screen.getByTestId("pipeline-filter-owner")).toBeInTheDocument();
    });
    const select = screen.getByTestId("pipeline-filter-owner");
    fireEvent.change(select, { target: { value: "t1" } });
    await waitFor(() => {
      const call = getMock.mock.calls.find((c) =>
        String(c[0]).includes("owner_id=t1"));
      expect(call).toBeDefined();
    });
  });
});


describe("SalesPipeline · loading + empty states", () => {
  it("renders the column skeleton before data lands", async () => {
    // Never resolve to keep the loading state visible.
    let resolve = null;
    getMock.mockImplementation((url) => {
      if (String(url).startsWith("/technicians")) return Promise.resolve([]);
      if (String(url).startsWith("/pipeline/kanban")) {
        return new Promise((r) => { resolve = r; });
      }
      return Promise.resolve({});
    });
    _render();
    // At least one skeleton container renders.
    const skels = await screen.findAllByTestId("pipeline-column-skeleton");
    expect(skels.length).toBeGreaterThan(0);
    // Unblock so the test cleanup doesn't hang.
    resolve?.(_mkResponse());
  });

  it("renders the empty-state per column when count is 0", async () => {
    _render();
    for (const k of ["leads", "quoted", "scheduled",
                       "completed", "follow_up"]) {
      const empty = await screen.findByTestId(`pipeline-column-empty-${k}`);
      expect(empty).toBeInTheDocument();
    }
  });
});
