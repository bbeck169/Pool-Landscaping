/**
 * Phase R1.c · Feb-2026 — Financial-tab panels expose a
 * "Download PDF" button that calls into
 * ``downloadServerPdf`` with the metric's PDF endpoint. We stub
 * the helper (it needs a real ``fetch``/``URL.createObjectURL``
 * chain that JSDOM doesn't provide) and assert every panel's
 * button hits the right path with the right filename.
 */
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
}));
vi.mock("react-apexcharts", () => ({
  __esModule: true, default: () => <div data-testid="apex-stub" />,
}));
vi.mock("@/components/reports/downloadServerPdf", () => ({
  downloadServerPdf: vi.fn().mockResolvedValue(new Blob(["fake"])),
}));
vi.mock("@/components/ui/confirm-dialog", () => ({
  useConfirm: () => async () => true,
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { api } from "@/api";
import { downloadServerPdf } from "@/components/reports/downloadServerPdf";

import PnlPanel from "@/components/reports/PnlPanel";
import CashFlowPanel from "@/components/reports/CashFlowPanel";
import ArAgingPanel from "@/components/reports/ArAgingPanel";
import RevenueByServiceTypePanel from "@/components/reports/RevenueByServiceTypePanel";
import UnpaidInvoicesPanel from "@/components/reports/UnpaidInvoicesPanel";

const wrap = (ui) => <MemoryRouter>{ui}</MemoryRouter>;

const OK_ROWS = (extra = {}) => ({ rows: [], total: 0, ...extra });

describe("Financial tab · R1.c Download PDF buttons", () => {
  beforeEach(() => {
    api.get.mockReset();
    downloadServerPdf.mockReset();
    downloadServerPdf.mockResolvedValue(new Blob(["fake"]));
    api.get.mockResolvedValue({});
  });

  const cases = [
    {
      name: "PnlPanel", tid: "pnl-panel", filter: { period: "mtd" },
      Component: PnlPanel, wrapper: false,
      resolve: (url) => {
        if (url.includes("pnl_by_period")) return { value: 100 };
        return { rows: [] };
      },
      wantPath: "/reports/kpi/pnl_line_items/export.pdf?",
      wantFile: /^pnl-mtd\.pdf$/,
    },
    {
      name: "CashFlowPanel", tid: "cash-flow-panel", filter: { period: "ytd" },
      Component: CashFlowPanel, wrapper: false,
      resolve: () => OK_ROWS({ summary: {} }),
      wantPath: "/reports/kpi/cashflow_by_period/export.pdf?",
      wantFile: /^cash-flow-ytd\.pdf$/,
    },
    {
      name: "ArAgingPanel", tid: "ar-aging-panel", filter: { period: "mtd" },
      Component: ArAgingPanel, wrapper: false,
      extraProps: { onCustomerFocus: () => {} },
      resolve: () => OK_ROWS({ net_terms_days: 30 }),
      wantPath: "/reports/kpi/ar_aging_by_customer/export.pdf?",
      wantFile: /^ar-aging-mtd\.pdf$/,
    },
    {
      name: "RevenueByServiceTypePanel", tid: "rev-svc-panel",
      filter: { period: "mtd", lens: "invoiced" },
      Component: RevenueByServiceTypePanel, wrapper: false,
      resolve: () => OK_ROWS({ lens: "invoiced", row_count: 0 }),
      wantPath: "/reports/kpi/revenue_by_service_type/export.pdf?",
      wantFile: /^revenue-by-service-type-mtd-invoiced\.pdf$/,
    },
    {
      name: "UnpaidInvoicesPanel", tid: "unpaid-invoices-panel",
      filter: { period: "mtd" },
      Component: UnpaidInvoicesPanel, wrapper: true,
      resolve: () => OK_ROWS(),
      wantPath: "/reports/kpi/unpaid_invoices/export.pdf?",
      wantFile: /^unpaid-invoices-mtd\.pdf$/,
    },
  ];

  cases.forEach((c) => {
    it(`${c.name} — Download PDF hits ${c.wantPath}…`, async () => {
      api.get.mockImplementation((url) => Promise.resolve(c.resolve(url)));
      const tree = <c.Component filters={c.filter} {...(c.extraProps || {})} />;
      render(c.wrapper ? wrap(tree) : tree);
      const btn = await screen.findByTestId(`${c.tid}-export-pdf`);
      fireEvent.click(btn);
      await waitFor(() => expect(downloadServerPdf).toHaveBeenCalledTimes(1));
      const [path, filename] = downloadServerPdf.mock.calls[0];
      expect(path.startsWith(c.wantPath)).toBe(true);
      expect(filename).toMatch(c.wantFile);
    });
  });
});
