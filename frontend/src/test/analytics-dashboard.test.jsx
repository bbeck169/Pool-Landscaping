/**
 * Phase H6 · Feb-2026 — Monthly Analytics Dashboard tests.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mockGet = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => mockGet(...a), post: vi.fn(),
          patch: vi.fn(), put: vi.fn(), del: vi.fn() },
}));

import AnalyticsMonthlyPage from "@/pages/admin/AnalyticsMonthlyPage";


const SAMPLE = {
  tenant_id: "aquaterra",
  month: "2026-02",
  month_start: "2026-02-01T00:00:00+00:00",
  month_end: "2026-03-01T00:00:00+00:00",
  soshie_moderation: {
    calls_total: 42,
    cost_estimate_usd: 1.23,
    decisions: { approve: 30, flag: 10, block: 2 },
    cache_hit_rate: 0.4,
    avg_cost_per_call_usd: 0.03,
  },
  charge_templates: {
    total_templates: 8,
    total_applies: 21,
    top_templates: [
      { template_id: "tpl-a", name: "Weekly service",
        apply_count: 12, revenue_contribution_usd: 4800.00 },
      { template_id: "tpl-b", name: "Chemical add-on",
        apply_count: 6, revenue_contribution_usd: 900.00 },
    ],
    unused_templates: [
      { template_id: "tpl-x", name: "Legacy",
        days_since_created: 120 },
    ],
  },
  drift_alerts: {
    dispatches_total: 5,
    clean_heartbeats: 23,
    dispatch_success_rate: 0.83,
    days_with_drift: 5,
    worst_day: { date: "2026-02-15", dangling_refs_total: 42 },
  },
  soshie_manual_conversion: {
    posts_generated_total: 20,
    posts_marked_posted_total: 13,
    conversion_rate: 0.65,
    by_platform: [
      { platform: "facebook", generated: 10,
        marked_posted: 8, conversion_rate: 0.8 },
      { platform: "instagram", generated: 5,
        marked_posted: 3, conversion_rate: 0.6 },
      { platform: "linkedin", generated: 5,
        marked_posted: 2, conversion_rate: 0.4 },
    ],
  },
};


const renderPage = () =>
  render(<MemoryRouter><AnalyticsMonthlyPage /></MemoryRouter>);


beforeEach(() => {
  mockGet.mockReset();
});


describe("AnalyticsMonthlyPage · H6", () => {
  it("renders the 4 rollup cards with correct headers + numbers",
     async () => {
    mockGet.mockResolvedValue(SAMPLE);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("analytics-card-soshie"))
        .toBeInTheDocument(),
    );
    expect(screen.getByTestId("analytics-card-templates")).toBeInTheDocument();
    expect(screen.getByTestId("analytics-card-drift")).toBeInTheDocument();
    expect(screen.getByTestId("analytics-card-manual")).toBeInTheDocument();
    // Soshie: 42 calls + $1.23
    expect(screen.getByTestId("soshie-calls-total").textContent)
      .toMatch(/42/);
    expect(screen.getByTestId("soshie-cost-total").textContent)
      .toMatch(/\$1\.23/);
    // Cache-hit pill
    expect(screen.getByTestId("soshie-cache-pill").textContent)
      .toMatch(/40\.0%/);
    // Templates: top row values
    expect(screen.getByTestId("templates-applies-total").textContent)
      .toMatch(/21/);
    expect(screen.getByTestId("templates-top-tpl-a").textContent)
      .toMatch(/Weekly service/);
    expect(screen.getByTestId("templates-top-tpl-a").textContent)
      .toMatch(/\$4,800\.00/);
    // Drift badges + worst day
    expect(screen.getByTestId("drift-dispatches").textContent)
      .toMatch(/5/);
    expect(screen.getByTestId("drift-days-badge").textContent)
      .toMatch(/5 day\(s\) with drift/i);
    expect(screen.getByTestId("drift-worst-day").textContent)
      .toMatch(/2026-02-15/);
    // Manual conversion: overall + per-platform rows sorted DESC
    expect(screen.getByTestId("manual-rate").textContent)
      .toMatch(/65\.0%/);
    const facebookRow = screen.getByTestId("manual-row-facebook");
    expect(facebookRow.textContent).toMatch(/80\.0%/);
  });

  it("mount call hits /admin/analytics/monthly?month=<current-month>",
     async () => {
    mockGet.mockResolvedValue(SAMPLE);
    renderPage();
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    const [url] = mockGet.mock.calls[0];
    expect(url).toMatch(/^\/admin\/analytics\/monthly\?month=\d{4}-\d{2}$/);
  });

  it("month picker triggers refetch with the selected month",
     async () => {
    mockGet.mockResolvedValueOnce(SAMPLE);   // mount
    mockGet.mockResolvedValueOnce({          // month-change
      ...SAMPLE,
      month: "2025-12",
      soshie_moderation: {
        ...SAMPLE.soshie_moderation, calls_total: 999,
      },
    });
    renderPage();
    const picker = await screen.findByTestId("analytics-month-picker");
    // Any historical month option should exist in the dropdown.
    const opt = picker.querySelector('option[value="2025-12"]');
    expect(opt).not.toBeNull();
    fireEvent.change(picker, { target: { value: "2025-12" } });
    await waitFor(() =>
      expect(screen.getByTestId("soshie-calls-total").textContent)
        .toMatch(/999/),
    );
    const lastCall = mockGet.mock.calls.at(-1);
    expect(lastCall[0]).toBe(
      "/admin/analytics/monthly?month=2025-12",
    );
  });

  it("shows loading skeletons on initial mount before data arrives",
     async () => {
    let resolve;
    mockGet.mockReturnValue(new Promise((r) => { resolve = r; }));
    renderPage();
    // Four skeleton placeholders render immediately.
    const skels = screen.getAllByTestId("analytics-card-skeleton");
    expect(skels.length).toBeGreaterThanOrEqual(4);
    // Unstick the effect so React doesn't warn on unmount.
    resolve(SAMPLE);
  });

  it("renders empty-state cells when a stream has no data",
     async () => {
    mockGet.mockResolvedValue({
      tenant_id: "t", month: "2026-02",
      soshie_moderation: {
        calls_total: 0, cost_estimate_usd: 0,
        decisions: {}, cache_hit_rate: 0, avg_cost_per_call_usd: 0,
      },
      charge_templates: {
        total_templates: 0, total_applies: 0,
        top_templates: [], unused_templates: [],
      },
      drift_alerts: {
        dispatches_total: 0, clean_heartbeats: 0,
        dispatch_success_rate: 0, days_with_drift: 0,
        worst_day: null,
      },
      soshie_manual_conversion: {
        posts_generated_total: 0, posts_marked_posted_total: 0,
        conversion_rate: 0, by_platform: [],
      },
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("soshie-empty")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("templates-empty")).toBeInTheDocument();
    expect(screen.getByTestId("manual-empty")).toBeInTheDocument();
    // Drift renders an "All clean" badge instead of a red one.
    expect(screen.getByTestId("drift-days-badge").textContent)
      .toMatch(/all clean/i);
  });
});
