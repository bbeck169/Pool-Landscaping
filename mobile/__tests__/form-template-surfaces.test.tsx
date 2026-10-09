/**
 * Phase 7D · Form Template Runtime (mobile) — real render surfaces.
 *  • Service report sections honour template styles; isEmpty → hardcoded.
 *  • Invoice line-item cards honour `line_items_table` (billable unlock);
 *    late-fee highlight still wins. Estimate wiring = source contract
 *    (its full render harness `parity-phase-a` is a pre-existing failure).
 */
import * as fs from "fs";
import * as path from "path";
import React from "react";
import { StyleSheet } from "react-native";
import { render, waitFor } from "@testing-library/react-native";

let mockTpl: any = null; // null → isEmpty
const mockSeen: string[] = [];
jest.mock("@/src/hooks/useFormTemplateRuntime", () => ({
  useFormTemplateRuntime: (ft: string) => {
    if (ft) mockSeen.push(ft);
    return mockTpl
      ? { fieldsById: mockTpl, fieldsOrdered: Object.values(mockTpl), isLoading: false, error: null, isEmpty: false, version: 1 }
      : { fieldsById: {}, fieldsOrdered: [], isLoading: false, error: "http_403", isEmpty: true, version: null };
  },
}));
const mockReport = { template: "pool", submitted_at: null, photos: [], job: { id: "j1" }, readings: [], chemicals_added: [], checklist: [], notes: "" };
const mockInvoice = {
  company: { name: "AquaTerra" }, bill_to: { name: "Jo" }, property_address: "1 Main", header: { invoice_number: "INV-1" },
  line_items: [{ description: "Pool clean", qty_hr: 1, cost_rate: 90, total: 90 }, { description: "Late fee", qty_hr: 1, cost_rate: 10, total: 10, is_late_fee: true }],
  totals: { subtotal: 100, this_invoice: 100, amount_paid: 0, total_due: 100 }, notes: "", is_due_on_receipt: false, payment_status: "unpaid",
};
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: "j1" }),
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, []),
}));
jest.mock("@/src/api", () => ({
  api: { get: jest.fn(async () => mockReport), post: jest.fn(async () => ({})), patch: jest.fn(async () => ({})) },
  api_base: () => "http://test/api", getAuthToken: async () => "tok",
}));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: "customer", name: "C", email: "c@x" } }) }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }), SafeAreaView: ({ children }: any) => children }));
jest.mock("react-native-webview", () => ({ WebView: () => null }));
jest.mock("expo-image", () => ({ Image: "Image" }));
jest.mock("expo-image-picker", () => ({}));
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));
jest.mock("@/src/services/readCache", () => ({ writeCache: async () => {}, readCache: async () => null }));
jest.mock("@/src/services/sync/photoWorker", () => ({ capturePhoto: jest.fn(), getPhotosForEntity: async () => [] }));
jest.mock("@/src/api/invoices", () => ({ getInvoiceFull: jest.fn(async () => mockInvoice), getInvoiceMagic: jest.fn(async () => mockInvoice) }));
jest.mock("@/src/components/invoices/InvoiceViewHistory", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/api/payments", () => ({ createPaymentIntent: jest.fn() }));
jest.mock("@/src/config/stripe", () => ({ useStripeConfig: () => ({ pk: "pk", loading: false }) }));
jest.mock("@/src/components/files", () => ({ InvoiceAttachments: () => null }));
jest.mock("@/src/components/files/AuthedImage", () => ({ AuthedImage: () => null }));
jest.mock("@/src/components/files/FileList", () => ({ FileList: () => null }));
jest.mock("@/src/components/files/FileUpload", () => ({ FileUpload: () => null }));
jest.mock("@/src/api/files", () => ({ humanBytes: (n: number) => `${n} B`, buildAuthedDownloadUrl: () => "" }));

import ServiceReport from "@/app/(app)/service-report/[id]";
import InvoiceDetail from "@/app/invoice/[id]";

const st = (el: any) => StyleSheet.flatten(el.props.style);
const S = (bg: string, fg = "#FFFFFF") => ({ style: { bg_color: bg, bg_alpha: 1, text_color: fg, border_color: "#000000", width_cols: 12, padding_y: 4 } });

beforeEach(() => { mockTpl = null; mockSeen.length = 0; });

describe("Service report", () => {
  it("template present → sections take template bg/border/padding; pool → pool_service_report", async () => {
    mockTpl = { photos: { field_id: "photos", ...S("#112233") }, notes: { field_id: "notes", ...S("#445566") }, checklist_section: { field_id: "checklist_section", ...S("#778899") } };
    const r = render(<ServiceReport />);
    const photos = await r.findByTestId("svc-report-photos");
    expect(st(photos)).toMatchObject({ backgroundColor: "rgba(17, 34, 51, 1)", borderColor: "#000000", paddingVertical: 16 });
    expect(st(r.getByTestId("svc-report-notes")).backgroundColor).toBe("rgba(68, 85, 102, 1)");
    expect(st(r.getByTestId("svc-report-checklist")).backgroundColor).toBe("rgba(119, 136, 153, 1)");
    expect(st(r.getByText("Notes")).color).toBe("#FFFFFF");
    expect(mockSeen).toContain("pool_service_report");
  });
  it("isEmpty (403 / no template) → hardcoded card styles untouched", async () => {
    const r = render(<ServiceReport />);
    const photos = await r.findByTestId("svc-report-photos");
    const base = st(photos);
    expect(base.backgroundColor).not.toMatch(/^rgba/);
    expect(base.paddingVertical).toBeUndefined();
    expect(st(r.getByTestId("svc-report-notes")).backgroundColor).toBe(base.backgroundColor);
  });
});

describe("Invoice line items (billable unlock)", () => {
  it("template → line cards use line_items_table bg/border + text colour; late fee keeps its highlight", async () => {
    mockTpl = { line_items_table: { field_id: "line_items_table", ...S("#0F172A", "#F8FAFC") } };
    const r = render(<InvoiceDetail />);
    const row = await waitFor(() => r.getByTestId("invoice-line-item-0"));
    expect(st(row)).toMatchObject({ backgroundColor: "rgba(15, 23, 42, 1)", borderColor: "#000000" });
    expect(st(r.getByTestId("invoice-line-item-total-0")).color).toBe("#F8FAFC");
    expect(st(r.getByTestId("invoice-line-item-1")).backgroundColor).toBe("#FFF7ED");
    expect(mockSeen).toContain("invoice");
  });
  it("isEmpty → hardcoded #F8FAFC card", async () => {
    const r = render(<InvoiceDetail />);
    const row = await waitFor(() => r.getByTestId("invoice-line-item-0"));
    expect(st(row).backgroundColor).toBe("#F8FAFC");
  });
});

describe("Estimate line items (source contract)", () => {
  const SRC = fs.readFileSync(path.resolve(__dirname, "../app/estimate-view/[id].tsx"), "utf-8");
  it("reads the estimate template and layers it under the declined state", () => {
    expect(SRC).toContain('useFormTemplateRuntime("estimate")');
    expect(SRC).toContain("liTplRuntime.fieldsById?.line_items_table");
    expect(SRC).toContain("style={[s.lineCard, liCardTpl, isDeclined && s.lineCardDeclined]}");
    expect(SRC).toContain("[s.lineTotal, liTextTpl, isDeclined && s.lineDeclinedText]");
    expect(SRC.indexOf('useFormTemplateRuntime("estimate")')).toBeLessThan(SRC.indexOf("  if (loading) {"));
  });
});
