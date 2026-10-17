/**
 * Feb-2026 · Pool Service Report drill-down phase.
 *
 * Vitest coverage for the three click surfaces (TC-A chip, TC-B
 * per-tech row, TC-C Auto-Friday delivery row) and the shared
 * modal. The modal fetches on open — tests seed per-URL mock
 * responses + assert the correct URL fires.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockGet = vi.fn();
const mockPost = vi.fn();
let _confirmResult = true;
const _toastSuccess = vi.fn();
const _toastError = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
  },
}));
vi.mock("@/components/ui/confirm-dialog", () => ({
  useConfirm: () => async () => _confirmResult,
  ConfirmProvider: ({ children }) => children,
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {}, {
    success: (...a) => _toastSuccess(...a),
    error: (...a) => _toastError(...a),
  }),
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u-1" } }),
}));

import PoolServiceReport from "@/pages/reports/PoolServiceReport";

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  _toastSuccess.mockReset();
  _toastError.mockReset();
  _confirmResult = true;
});

const _summary = {
  week_start: "2026-02-09", week_end: "2026-02-15",
  total_completed: 54,
  total_completed_all: 75,
  dropped_count: 0,
  total_skipped: 1,
  period: { start: "2026-02-09", end: "2026-02-15" },
  summary: { total_pool_visits: 75, maintenance_visits: 54,
              repair_visits: 0, other_visits: 21 },
  maintenance: [
    { technician_id: "ethan", technician_name: "Ethan Smith",
       technician_active: true,
       pools_serviced: 54, repairs_completed: 0,
       other: 21, skipped: 1,
       completed: 54, completed_all: 75 },
  ],
  repairs: [],
  other: [
    { technician_id: "ethan", technician_name: "Ethan Smith",
       technician_active: true,
       pools_serviced: 54, repairs_completed: 0,
       other: 21, skipped: 1,
       completed: 54, completed_all: 75 },
  ],
  visits: [],
  rows: [],
  totals: { pools_serviced: 54, repairs_completed: 0 },
  by_technician: [
    { technician_id: "ethan", technician_name: "Ethan Smith",
       pools_serviced: 54, repairs_completed: 0, other: 21,
       skipped: 1, completed: 54, completed_all: 75 },
  ],
  reconciliation: {
    matches: true, delta: 0,
    counted_total: 75, actual_total: 75, dropped_count: 0,
  },
  other_label: "Other job types",
  attribution_priority: [
    "technician_id", "technician_name",
    "crew_id→crews.tech_ids[0]", "Unassigned",
  ],
};


function _wire(extra = {}) {
  mockGet.mockImplementation((url) => {
    if (url.startsWith("/reports/pool-service?")) {
      return Promise.resolve(extra.summary || _summary);
    }
    if (url.startsWith("/reports/pool-service/email-history?")) {
      return Promise.resolve({
        items: extra.history || [], count: 0,
      });
    }
    if (url.startsWith("/reports/pool-service/jobs?")) {
      return Promise.resolve(extra.jobs || {
        items: [
          { job_id: "j-1", title: "Weekly Service",
             customer_id: "c-1", customer_name: "Alpha HOA",
             scheduled_date: "2026-02-10",
             technician_id: "ethan", technician_name: "Ethan Smith",
             status: "completed", work_class: "service",
             service_type: "weekly pool service" },
          { job_id: "j-2", title: "Pump inspection",
             customer_id: "c-2", customer_name: "Bravo Estates",
             scheduled_date: "2026-02-12",
             technician_id: "ethan", technician_name: "Ethan Smith",
             status: "completed", work_class: "service",
             service_type: "pool inspection" },
        ],
        count: 2,
        window: { start: "2026-02-09", end: "2026-02-15" },
        filter: { bucket: "maintenance", tech_id: null },
      });
    }
    if (url.includes("/reports/pool-service/email-history/")
        && url.endsWith("/contents")) {
      return Promise.resolve(extra.delivery || {
        delivery: { id: "d-1", week_start: "2026-02-09",
                      week_end: "2026-02-15", recipients: ["a@b.co"] },
        jobs: [], customers: [
          { customer_id: "c-1", customer_name: "Alpha HOA",
             jobs: [{ job_id: "j-1", title: "Weekly Service",
                       scheduled_date: "2026-02-10",
                       work_class: "service" }] },
        ],
        job_count: 1, customer_count: 1,
        window: { start: "2026-02-09", end: "2026-02-15" },
      });
    }
    return Promise.resolve({});
  });
}


describe("Pool Service Report · drill-down phase", () => {
  it("renders reconciliation banner when matches=false", async () => {
    _wire({
      summary: {
        ..._summary,
        reconciliation: {
          matches: false, delta: 5,
          counted_total: 70, actual_total: 75, dropped_count: 0,
        },
      },
    });
    render(<PoolServiceReport />);
    const banner = await screen.findByTestId("pool-report-reconciliation-banner");
    expect(banner).toBeInTheDocument();
    expect(screen.getByTestId("pool-report-reconciliation-counted").textContent)
      .toBe("70");
    expect(screen.getByTestId("pool-report-reconciliation-actual").textContent)
      .toBe("75");
    expect(screen.getByTestId("pool-report-reconciliation-delta").textContent)
      .toBe("5");
  });

  it("hides reconciliation banner when matches=true (happy path)", async () => {
    _wire();
    render(<PoolServiceReport />);
    // Wait for the summary strip to appear → page is hydrated.
    await screen.findByTestId("pool-service-summary");
    expect(screen.queryByTestId("pool-report-reconciliation-banner")).toBeNull();
  });

  it("renders the Other Job Types section with a tech row (not a silent chip)", async () => {
    _wire();
    render(<PoolServiceReport />);
    const section = await screen.findByTestId("pool-service-other-section");
    expect(section).toBeInTheDocument();
    // The seeded other row has 21 "other" jobs attributed to Ethan.
    const otherCount = screen.getByTestId("pool-report-tech-row-ethan-other");
    expect(otherCount.textContent).toBe("21");
  });

  it("TC-A — clicking the Service chip (TD-63 relabel) opens the bucket drill-down", async () => {
    _wire();
    const user = userEvent.setup();
    render(<PoolServiceReport />);
    const chip = await screen.findByTestId("pool-report-total-serviced");
    await user.click(chip);
    const modal = await screen.findByTestId("pool-service-drilldown-modal");
    expect(modal).toBeInTheDocument();
    // Fix 1 · Feb-2026 — the modal MUST pass ``status=completed``
    // so the row count matches the summary chip (prior behavior
    // returned completed + missed and the modal exceeded the chip).
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(
      expect.stringMatching(
        /^\/reports\/pool-service\/jobs\?date_from=2026-02-09&date_to=2026-02-15&bucket=maintenance&status=completed$/,
      ),
    ));
    // Table renders the mocked jobs.
    expect(await screen.findByTestId("pool-service-drilldown-row-j-1")).toBeInTheDocument();
    expect(screen.getByTestId("pool-service-drilldown-row-j-2")).toBeInTheDocument();
    // Customer link opens in a new tab + points at the customer profile.
    const custLink = screen.getByTestId("pool-service-drilldown-customer-j-1");
    expect(custLink).toHaveAttribute("href", "/customers/c-1");
    expect(custLink).toHaveAttribute("target", "_blank");
    // Job open link.
    const openLink = screen.getByTestId("pool-service-drilldown-open-j-1");
    expect(openLink).toHaveAttribute("href", "/jobs/j-1");
    expect(openLink).toHaveAttribute("target", "_blank");
  });

  it("TC-B — clicking a per-tech row opens the per-tech drill-down with tech_id", async () => {
    _wire();
    const user = userEvent.setup();
    render(<PoolServiceReport />);
    const techRow = await screen.findByTestId("pool-service-row-ethan-maintenance");
    await user.click(techRow);
    await screen.findByTestId("pool-service-drilldown-modal");
    // Fix 1 · tech variant also forwards ``status=completed``.
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(
      expect.stringMatching(
        /^\/reports\/pool-service\/jobs\?date_from=2026-02-09&date_to=2026-02-15&tech_id=ethan&status=completed$/,
      ),
    ));
    // Title mentions the tech's name.
    expect((await screen.findByTestId("pool-service-drilldown-title")).textContent)
      .toMatch(/Ethan Smith/);
  });

  it("TC-C — clicking an Auto-Friday delivery row opens the delivery contents modal", async () => {
    _wire({
      history: [{
        id: "d-1", week_start: "2026-02-09", week_end: "2026-02-15",
        recipients: ["admin@aquaterra.com"], total_completed: 54,
        total_skipped: 1, sent: true, mocked: false,
        sent_at: "2026-02-15T17:00:00+00:00",
      }],
    });
    const user = userEvent.setup();
    render(<PoolServiceReport />);
    const row = await screen.findByTestId("pool-service-email-history-row-d-1");
    await user.click(row);
    await screen.findByTestId("pool-service-drilldown-modal");
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(
      "/reports/pool-service/email-history/d-1/contents",
    ));
    // Delivery contents table renders.
    expect(await screen.findByTestId("pool-service-drilldown-delivery-table"))
      .toBeInTheDocument();
    const row1 = screen.getByTestId("pool-service-drilldown-delivery-row-c-1");
    expect(row1.textContent).toMatch(/Alpha HOA/);
  });

  it("close button dismisses the modal", async () => {
    _wire();
    const user = userEvent.setup();
    render(<PoolServiceReport />);
    const chip = await screen.findByTestId("pool-report-total-serviced");
    await user.click(chip);
    await screen.findByTestId("pool-service-drilldown-modal");
    await user.click(screen.getByTestId("pool-service-drilldown-close"));
    await waitFor(() =>
      expect(screen.queryByTestId("pool-service-drilldown-modal")).toBeNull(),
    );
  });

  it("renders an Unassigned chip when the backend reports an unassigned bucket", async () => {
    _wire({
      summary: {
        ..._summary,
        by_technician: [
          ..._summary.by_technician,
          { technician_id: null, technician_name: "Unassigned",
             pools_serviced: 0, repairs_completed: 0, other: 3,
             skipped: 0, completed: 0, completed_all: 3 },
        ],
      },
    });
    render(<PoolServiceReport />);
    const chip = await screen.findByTestId("pool-report-total-unassigned");
    expect(chip).toBeInTheDocument();
    expect(chip.textContent).toMatch(/3/);
  });

  it("Fix 2 — banner surfaces dropped_sample and expands/collapses on click", async () => {
    _wire({
      summary: {
        ..._summary,
        reconciliation: {
          matches: false, delta: 2,
          counted_total: 75, actual_total: 77, dropped_count: 2,
          dropped_sample: [
            { job_id: "drop-1", customer_name: "DropA",
               scheduled_date: "2026-02-10",
               status: "scheduled",
               reason: "non-terminal status: scheduled" },
            { job_id: "drop-2", customer_name: "DropB",
               scheduled_date: "2026-02-11",
               status: "in_progress",
               reason: "non-terminal status: in_progress" },
          ],
        },
      },
    });
    const user = userEvent.setup();
    render(<PoolServiceReport />);
    const banner = await screen.findByTestId("pool-report-reconciliation-banner");
    expect(banner).toBeInTheDocument();
    // Collapsed by default — sample list not visible.
    expect(screen.queryByTestId("pool-report-reconciliation-sample-list")).toBeNull();
    const toggle = screen.getByTestId("pool-report-reconciliation-toggle");
    await user.click(toggle);
    const list = await screen.findByTestId("pool-report-reconciliation-sample-list");
    expect(list).toBeInTheDocument();
    expect(screen.getByTestId("pool-report-reconciliation-sample-row-drop-1"))
      .toBeInTheDocument();
    expect(screen.getByTestId("pool-report-reconciliation-sample-row-drop-2"))
      .toBeInTheDocument();
    // Second click collapses again.
    await user.click(toggle);
    await waitFor(() => expect(
      screen.queryByTestId("pool-report-reconciliation-sample-list"),
    ).toBeNull());
  });

  it("Fix 2 — happy path with dropped_count=0 keeps the banner hidden", async () => {
    _wire({
      summary: {
        ..._summary,
        reconciliation: {
          matches: true, delta: 0,
          counted_total: 75, actual_total: 75, dropped_count: 0,
          dropped_sample: [],
        },
      },
    });
    render(<PoolServiceReport />);
    await screen.findByTestId("pool-service-summary");
    expect(screen.queryByTestId("pool-report-reconciliation-banner")).toBeNull();
  });

  it("Fix 2 — matches=false with dropped_count=0 still shows the banner but no toggle", async () => {
    _wire({
      summary: {
        ..._summary,
        reconciliation: {
          matches: false, delta: 1,
          counted_total: 74, actual_total: 75, dropped_count: 0,
          dropped_sample: [],
        },
      },
    });
    render(<PoolServiceReport />);
    const banner = await screen.findByTestId("pool-report-reconciliation-banner");
    expect(banner).toBeInTheDocument();
    expect(screen.queryByTestId("pool-report-reconciliation-toggle")).toBeNull();
  });

  it("Mini-fix A — row renders 'Unknown tech (short-id)' when backend returns the fallback label", async () => {
    _wire({
      summary: {
        ..._summary,
        maintenance: [
          { technician_id: "b8a68119-1234-abcd-5678-9876543210aa",
             technician_name: "Unknown tech (b8a68119)",
             technician_active: true,
             pools_serviced: 2, repairs_completed: 0,
             other: 0, skipped: 0, completed: 2, completed_all: 2 },
        ],
        by_technician: [
          { technician_id: "b8a68119-1234-abcd-5678-9876543210aa",
             technician_name: "Unknown tech (b8a68119)",
             pools_serviced: 2, repairs_completed: 0, other: 0,
             skipped: 0, completed: 2, completed_all: 2 },
        ],
      },
    });
    render(<PoolServiceReport />);
    const row = await screen.findByTestId(
      "pool-service-row-b8a68119-1234-abcd-5678-9876543210aa-maintenance",
    );
    // The row's visible text must carry the "Unknown tech" label
    // — never the raw UUID.
    expect(row.textContent).toMatch(/Unknown tech \(b8a68119\)/);
    expect(row.textContent).not.toMatch(
      /b8a68119-1234-abcd-5678-9876543210aa/,
    );
  });
});


// ───────── Mini-fix B · admin-triggered Send-now button ─────────

describe("Pool Service Report · Mini-fix B · Send now button", () => {
  it("opens the custom confirm dialog with dry_run DEFAULT CHECKED", async () => {
    mockGet.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?")) {
        return Promise.resolve(_summary);
      }
      if (url.startsWith("/reports/pool-service/email-history?")) {
        return Promise.resolve({ items: [], count: 0 });
      }
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    render(<PoolServiceReport />);
    const btn = await screen.findByTestId("pool-service-send-now");
    await user.click(btn);
    // The dialog appears with the dry-run checkbox CHECKED by
    // default so an accidental Enter cannot blast real emails.
    const toggle = await screen.findByTestId(
      "pool-service-send-dry-run-toggle",
    );
    expect(toggle).toBeChecked();
    // Confirm CTA shows the dry-run copy, not the loud one.
    expect((await screen.findByTestId("pool-service-send-confirm"))
      .textContent).toMatch(/Run dry run/);
    // The loud ⚠ warning is NOT visible while dry_run is true.
    expect(screen.queryByTestId("pool-service-send-real-warning")).toBeNull();
  });

  it("fires POST with dry_run=true (default) and shows a success toast", async () => {
    mockPost.mockResolvedValue({
      delivery_id: "d-new-1", sent: false, mocked: true,
      recipient_count: 11, week_start: "2026-02-09",
      week_end: "2026-02-15",
      dry_run: true, dry_run_forced_by_env: false,
      reason: "admin_dry_run",
    });
    mockGet.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?")) {
        return Promise.resolve(_summary);
      }
      if (url.startsWith("/reports/pool-service/email-history?")) {
        return Promise.resolve({ items: [], count: 0 });
      }
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    render(<PoolServiceReport />);
    await user.click(await screen.findByTestId("pool-service-send-now"));
    await user.click(await screen.findByTestId("pool-service-send-confirm"));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/reports/pool-service/email-history/run-now",
      expect.objectContaining({ dry_run: true, week_ref: expect.any(String) }),
    ));
    await waitFor(() => expect(_toastSuccess).toHaveBeenCalled());
    // Success toast copy mentions "Dry run".
    expect(_toastSuccess.mock.calls[0][0]).toMatch(/Dry run/);
  });

  it("unchecking dry_run reveals the loud ⚠ warning and switches CTA copy", async () => {
    mockGet.mockImplementation(() => Promise.resolve(_summary));
    const user = userEvent.setup();
    render(<PoolServiceReport />);
    await user.click(await screen.findByTestId("pool-service-send-now"));
    const toggle = await screen.findByTestId(
      "pool-service-send-dry-run-toggle",
    );
    await user.click(toggle);
    expect(toggle).not.toBeChecked();
    // Loud warning appears.
    expect(await screen.findByTestId("pool-service-send-real-warning"))
      .toBeInTheDocument();
    // CTA copy flipped.
    expect((screen.getByTestId("pool-service-send-confirm")).textContent)
      .toMatch(/Send REAL emails/);
  });

  it("firing POST after unchecking dry_run sends dry_run: false in the body", async () => {
    mockPost.mockResolvedValue({
      delivery_id: "d-new-2", sent: true, mocked: false,
      recipient_count: 11, week_start: "2026-02-09",
      week_end: "2026-02-15",
      dry_run: false, dry_run_forced_by_env: false,
    });
    mockGet.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?")) {
        return Promise.resolve(_summary);
      }
      if (url.startsWith("/reports/pool-service/email-history?")) {
        return Promise.resolve({ items: [], count: 0 });
      }
      return Promise.resolve({});
    });
    const user = userEvent.setup();
    render(<PoolServiceReport />);
    await user.click(await screen.findByTestId("pool-service-send-now"));
    await user.click(
      await screen.findByTestId("pool-service-send-dry-run-toggle"),
    );
    await user.click(screen.getByTestId("pool-service-send-confirm"));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/reports/pool-service/email-history/run-now",
      expect.objectContaining({ dry_run: false }),
    ));
  });

  it("Cancel dismisses the dialog without firing POST", async () => {
    mockGet.mockImplementation(() => Promise.resolve(_summary));
    const user = userEvent.setup();
    render(<PoolServiceReport />);
    await user.click(await screen.findByTestId("pool-service-send-now"));
    await user.click(await screen.findByTestId("pool-service-send-cancel"));
    await waitFor(() =>
      expect(screen.queryByTestId("pool-service-send-dialog")).toBeNull(),
    );
    expect(mockPost).not.toHaveBeenCalled();
  });
});
