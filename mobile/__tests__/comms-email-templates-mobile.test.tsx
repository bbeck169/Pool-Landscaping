/**
 * P2 #11 mobile parity — Email Builder (web 965fb3c69 + d34aec4e5),
 * Commit 1: drawer wiring + admin gate + list fields + WebView preview.
 *
 *  A. drawer: "Email Builder" + "Templates" → t1, admin/super_admin only
 *     (managers hidden); sibling Communications rows untouched
 *  B. /admin/comms/{email,templates} stubs → Redirect to /comms/templates
 *  C. list: subject + customer-facing badge; non-admin never fetches
 *  D. detail: rendered WebView preview, loading + in-modal error/retry,
 *     non-admin never fetches
 */
import React from "react";
import { render, fireEvent, act } from "@testing-library/react-native";

/* ── mocks ─────────────────────────────────────────────────────── */
let mockRole = "admin";
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: mockRole, email: "admin@aquaterra.com", name: "Admin" } }),
}));

const mockListEmail = jest.fn();
const mockListSms = jest.fn();
const mockGetEmail = jest.fn();
const mockPreviewEmail = jest.fn();
jest.mock("@/src/api/comms", () => ({
  listEmailTemplates: (...a: any[]) => mockListEmail(...a),
  listSmsTemplates: (...a: any[]) => mockListSms(...a),
  getEmailTemplate: (...a: any[]) => mockGetEmail(...a),
  getSmsTemplate: jest.fn(),
  previewEmailTemplate: (...a: any[]) => mockPreviewEmail(...a),
  previewSmsTemplate: jest.fn(),
}));

const mockRedirect = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ code: "system.appointment_reminder", channel: "email" }),
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, [cb]),
  Redirect: (p: any) => { mockRedirect(p.href); return null; },
}));
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("@/src/components/widgets", () => {
  const RN = require("react-native");
  return { Header: (p: any) => <RN.View><RN.Text>{p.title}</RN.Text>{p.right}</RN.View> };
});
const mockWebViewProps: any[] = [];
jest.mock("react-native-webview", () => ({
  WebView: (p: any) => {
    mockWebViewProps.push(p);
    const RN = require("react-native");
    return <RN.View testID={p.testID} />;
  },
}));

import { ADMIN_NAV, canSeeEntry } from "@/src/nav/adminNav";
import AdminCommsEmailRoute from "@/app/admin/comms/email";
import AdminCommsTemplatesRoute from "@/app/admin/comms/templates";
import CommsTemplatesListScreen from "@/app/(app)/comms/templates/index";
import CommsTemplateDetailScreen from "@/app/(app)/comms/templates/[code]";
import { isCommsAdmin } from "@/src/components/comms/CommsAdminGate";
import { isInlineDocUrl } from "@/src/components/comms/EmailPreviewWebView";

const TEMPLATES = [
  { code: "system.appointment_reminder", name: "Appointment reminder", subject: "Your visit is tomorrow", is_customer_facing: true, is_system: true, updated_at: "2026-10-01" },
  { code: "custom.internal_alert", name: "Internal alert", subject: "Ops alert", is_customer_facing: false, is_system: false, updated_at: "2026-10-02" },
];
const TPL = { ...TEMPLATES[0], blocks_json: [{ type: "heading", text: "Hi" }] };
const PREVIEW = { subject: "Your visit is tomorrow", html: "<!doctype html><html><body><h1>Hi Jane</h1></body></html>", tokens_resolved: {} };

beforeEach(() => {
  mockRole = "admin";
  mockListEmail.mockReset().mockResolvedValue(TEMPLATES);
  mockListSms.mockReset().mockResolvedValue([]);
  mockGetEmail.mockReset().mockResolvedValue(TPL);
  mockPreviewEmail.mockReset().mockResolvedValue(PREVIEW);
  mockRedirect.mockReset();
  mockWebViewProps.length = 0;
});

/* ── A. drawer ─────────────────────────────────────────────────── */
const entry = (route: string) =>
  ADMIN_NAV.flatMap((g) => g.entries.map((e) => ({ g, e }))).find((x) => x.e.route === route)!;

describe("drawer · Communications entries", () => {
  it.each([
    ["/admin/comms/email", "Email Builder", "drawer-nav-comms-email"],
    ["/admin/comms/templates", "Templates", "drawer-nav-comms-templates"],
  ])("%s → t1, admin + super_admin only", (route, label, testID) => {
    const { g, e } = entry(route);
    expect(g.key).toBe("communications");
    expect(e.label).toBe(label);
    expect(e.testID).toBe(testID);
    expect(e.tier).toBe("t1");
    for (const r of ["admin", "super_admin"]) expect(canSeeEntry(r, e)).toBe(true);
    for (const r of ["manager", "owner", "dispatcher", "technician", "customer", undefined]) {
      expect(canSeeEntry(r as any, e)).toBe(false);
    }
  });

  it("sibling Communications rows are untouched (manager still sees SMS / Automations / Sends)", () => {
    for (const route of ["/admin/comms/sms", "/admin/comms/automations", "/admin/comms/sends"]) {
      const { e } = entry(route);
      expect(e.tier).toBe("t2");
      expect(e.roles).toBeUndefined();
      expect(canSeeEntry("manager", e)).toBe(true);
    }
  });

  it("isCommsAdmin mirrors backend _require_admin", () => {
    expect(isCommsAdmin("admin")).toBe(true);
    expect(isCommsAdmin("super_admin")).toBe(true);
    for (const r of ["owner", "manager", "technician", "", null, undefined]) expect(isCommsAdmin(r)).toBe(false);
  });
});

/* ── B. stub routes ────────────────────────────────────────────── */
describe("admin/comms stub routes", () => {
  it("email + templates redirect to the native library", () => {
    render(<AdminCommsEmailRoute />);
    render(<AdminCommsTemplatesRoute />);
    expect(mockRedirect.mock.calls).toEqual([["/comms/templates"], ["/comms/templates"]]);
  });
});

/* ── C. list ───────────────────────────────────────────────────── */
describe("templates list", () => {
  it("admin: renders subject + customer-facing badge only where flagged", async () => {
    const { findByTestId, getByTestId, queryByTestId, getByText } = render(<CommsTemplatesListScreen />);
    await findByTestId("comms-template-row-system.appointment_reminder");
    expect(getByText("Your visit is tomorrow")).toBeTruthy();
    expect(getByTestId("comms-template-subject-custom.internal_alert")).toBeTruthy();
    expect(getByTestId("comms-template-customer-facing-system.appointment_reminder")).toBeTruthy();
    expect(queryByTestId("comms-template-customer-facing-custom.internal_alert")).toBeNull();
    expect(mockListEmail).toHaveBeenCalledTimes(1);
  });

  it.each(["manager", "owner", "technician"])("%s: gate denied, no list request", async (role) => {
    mockRole = role;
    const { getByTestId, getByText } = render(<CommsTemplatesListScreen />);
    expect(getByTestId("comms-admin-gate-denied")).toBeTruthy();
    expect(getByText("Admin access required")).toBeTruthy();
    await act(async () => {});
    expect(mockListEmail).not.toHaveBeenCalled();
  });
});

/* ── D. detail + preview ───────────────────────────────────────── */
describe("template detail · rendered preview", () => {
  it("Preview → loader → sandboxed WebView with the server HTML", async () => {
    let resolve: (v: any) => void = () => {};
    mockPreviewEmail.mockImplementation(() => new Promise((r) => { resolve = r; }));
    const { findByTestId, getByTestId, queryByTestId } = render(<CommsTemplateDetailScreen />);
    fireEvent.press(await findByTestId("comms-template-preview-btn"));
    expect(getByTestId("comms-preview-loader")).toBeTruthy();
    expect(mockPreviewEmail).toHaveBeenCalledWith("system.appointment_reminder");

    await act(async () => { resolve(PREVIEW); });
    expect(queryByTestId("comms-preview-loader")).toBeNull();
    expect(getByTestId("comms-email-preview-webview")).toBeTruthy();
    const wv = mockWebViewProps[mockWebViewProps.length - 1];
    expect(wv.source).toEqual({ html: PREVIEW.html });
    expect(wv.javaScriptEnabled).toBe(false);
    expect(getByTestId("comms-preview-subject").props.children).toBe("Your visit is tomorrow");
  });

  it("preview failure stays inside the modal with Retry (screen not replaced)", async () => {
    mockPreviewEmail.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(PREVIEW);
    const { findByTestId, getByTestId } = render(<CommsTemplateDetailScreen />);
    fireEvent.press(await findByTestId("comms-template-preview-btn"));
    await findByTestId("comms-preview-error");
    expect(getByTestId("comms-template-detail")).toBeTruthy();

    fireEvent.press(getByTestId("comms-preview-retry"));
    await findByTestId("comms-email-preview-webview");
    expect(mockPreviewEmail).toHaveBeenCalledTimes(2);
  });

  it("WebView link taps open externally; only the inline doc loads in-frame", () => {
    expect(isInlineDocUrl("about:blank")).toBe(true);
    expect(isInlineDocUrl(undefined)).toBe(true);
    expect(isInlineDocUrl("data:text/html,x")).toBe(true);
    expect(isInlineDocUrl("https://example.com")).toBe(false);
  });

  it("manager: gate denied, no template/preview requests", async () => {
    mockRole = "manager";
    const { getByTestId } = render(<CommsTemplateDetailScreen />);
    expect(getByTestId("comms-admin-gate-denied")).toBeTruthy();
    await act(async () => {});
    expect(mockGetEmail).not.toHaveBeenCalled();
  });
});

