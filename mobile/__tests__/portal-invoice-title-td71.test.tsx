/**
 * TD-71 (web 5baf91f86) + TD-72b (web 106153aa2) — portal invoice /
 * estimate list titles + Created line. TD-77 (web f4e4fa85c) no-op guard:
 * mobile invoices never had the "Total outstanding" tile.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

import {
  isImportedPlaceholderTitle, resolvePortalInvoiceTitle, formatInvoiceCreatedDate,
} from "@/src/lib/portalInvoiceTitle";
import { api } from "@/src/api";
import PortalInvoices from "@/app/portal/invoices";
import PortalEstimates from "@/app/portal/estimates";

jest.mock("@/src/api", () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock("expo-router", () => {
  const React = jest.requireActual("react");
  return {
    useFocusEffect: (cb: any) => React.useEffect(cb, [cb]),
    useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  };
});
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));

describe("isImportedPlaceholderTitle", () => {
  it("matches Import #<n> + whitespace/case variants", () => {
    for (const t of ["Import #259", "  Import #  259  ", "Import#259", "import #7"]) {
      expect(isImportedPlaceholderTitle({ title: t })).toBe(true);
    }
  });
  it("does NOT match legit titles containing 'Import'", () => {
    for (const t of ["Import fee", "Imported pump #2", "Import #259 pool", "Pool service"]) {
      expect(isImportedPlaceholderTitle({ title: t })).toBe(false);
    }
  });
  it("null-safe", () => {
    expect(isImportedPlaceholderTitle(null)).toBe(false);
    expect(isImportedPlaceholderTitle({})).toBe(false);
  });
});

describe("resolvePortalInvoiceTitle — 4-branch chain", () => {
  const imp = { title: "Import #259" };
  it("1 service_description (1b service_summary)", () => {
    expect(resolvePortalInvoiceTitle({ ...imp, service_description: " Weekly pool ", line_items: [{ title: "x" }] }))
      .toBe("Weekly pool");
    expect(resolvePortalInvoiceTitle({ ...imp, service_summary: "Spring cleanup" })).toBe("Spring cleanup");
  });
  it("2 line_items[0].title (2b .description)", () => {
    expect(resolvePortalInvoiceTitle({ ...imp, line_items: [{ title: "Filter clean" }] })).toBe("Filter clean");
    expect(resolvePortalInvoiceTitle({ ...imp, line_items: [{ description: "Acid wash" }] })).toBe("Acid wash");
  });
  it("3 notes trimmed; >80 chars truncated with …", () => {
    expect(resolvePortalInvoiceTitle({ ...imp, notes: "  Gate code 1234  " })).toBe("Gate code 1234");
    const long = "a".repeat(100);
    expect(resolvePortalInvoiceTitle({ ...imp, notes: long })).toBe("a".repeat(80) + "…");
  });
  it("4 neutral 'Invoice' — never the import number", () => {
    expect(resolvePortalInvoiceTitle(imp)).toBe("Invoice");
  });
  it("non-imported titles pass through; null/missing → 'Invoice'", () => {
    expect(resolvePortalInvoiceTitle({ title: "Monthly Pool Service", service_description: "x" }))
      .toBe("Monthly Pool Service");
    expect(resolvePortalInvoiceTitle(null)).toBe("Invoice");
    expect(resolvePortalInvoiceTitle({})).toBe("Invoice");
  });
});

describe("formatInvoiceCreatedDate", () => {
  it("Created MM/DD/YYYY, zero-padded, local tz", () => {
    expect(formatInvoiceCreatedDate({ created_at: "2025-03-04T12:00:00" })).toBe("Created 03/04/2025");
  });
  it("invoice_date fallback; created_at preferred", () => {
    expect(formatInvoiceCreatedDate({ invoice_date: "2025-11-20T12:00:00" })).toBe("Created 11/20/2025");
    expect(formatInvoiceCreatedDate({ created_at: "2025-01-02T12:00:00", invoice_date: "2025-11-20T12:00:00" }))
      .toBe("Created 01/02/2025");
  });
  it("'' when missing / unparseable / null", () => {
    expect(formatInvoiceCreatedDate({})).toBe("");
    expect(formatInvoiceCreatedDate({ created_at: "not-a-date" })).toBe("");
    expect(formatInvoiceCreatedDate(null)).toBe("");
  });
});

beforeEach(() => (api.get as jest.Mock).mockReset());

it("Invoices list: Import #<n> rewritten + Created line; no Total outstanding tile (TD-77)", async () => {
  (api.get as jest.Mock).mockResolvedValue([
    { id: "i1", title: "Import #259", service_description: "Weekly Pool Service", total: 120,
      payment_status: "unpaid", created_at: "2025-03-14T12:00:00" },
    { id: "i2", title: "Monthly Pool Service", total: 80, payment_status: "paid" },
  ]);
  const q = render(<PortalInvoices />);
  await waitFor(() => q.getByTestId("portal-invoice-title-i1"));
  expect(q.getByTestId("portal-invoice-title-i1").props.children).toBe("Weekly Pool Service");
  expect(q.getByTestId("portal-invoice-created-i1").props.children).toBe("Created 03/14/2025");
  expect(q.getByTestId("portal-invoice-title-i2").props.children).toBe("Monthly Pool Service");
  expect(q.queryByTestId("portal-invoice-created-i2")).toBeNull();
  expect(q.queryByText(/Import #/)).toBeNull();
  expect(q.queryByText(/Total outstanding/i)).toBeNull();
});

it("Estimates list: Import #<n> rewritten via the same resolver", async () => {
  (api.get as jest.Mock).mockResolvedValue([
    { id: "e1", title: "Import #31", line_items: [{ title: "Pump replacement" }], total: 900, status: "sent" },
  ]);
  const q = render(<PortalEstimates />);
  await waitFor(() => q.getByTestId("portal-estimate-title-e1"));
  expect(q.getByTestId("portal-estimate-title-e1").props.children).toBe("Pump replacement");
  expect(q.queryByText(/Import #/)).toBeNull();
});
