/**
 * Phase 1 (mobile) — owner access to Marketing Forms + submissions inbox ONLY.
 *
 * - The 4 Marketing Forms screens gate on MARKETING_FORMS_ROLES (admin, super_admin, owner).
 * - Email Builder / comms templates keep COMMS_ADMIN_ROLES (admin, super_admin) → owner STILL blocked.
 * - Owners do NOT get the admin drawer; More shows a single OWNER_NAV group holding
 *   only entries that explicitly list "owner" (Marketing Forms). Templates Library stays hidden.
 */
import React from "react";
import { render, act, fireEvent } from "@testing-library/react-native";

const mockGet = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockGet(...a), post: jest.fn(), patch: jest.fn() } }));
let mockRole = "owner";
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: mockRole, name: "Olive Owner", email: "o@x.com" }, logout: jest.fn() }),
}));
let mockParams: any = {};
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => mockParams,
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, [cb]),
  Redirect: () => null,
}));
jest.mock("@/src/components/widgets", () => {
  const RN = require("react-native");
  return { Header: (p: any) => <RN.View><RN.Text>{p.title}</RN.Text>{p.right}</RN.View> };
});
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("expo-clipboard", () => ({ setStringAsync: jest.fn() }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("react-native-webview", () => ({ WebView: () => null }));
const mockComms = jest.fn().mockResolvedValue([]);
jest.mock("@/src/api/comms", () => ({
  listEmailTemplates: (...a: any[]) => mockComms(...a),
  listSmsTemplates: (...a: any[]) => mockComms(...a),
  getEmailTemplate: (...a: any[]) => mockComms(...a),
  getSmsTemplate: (...a: any[]) => mockComms(...a),
  previewEmailTemplate: (...a: any[]) => mockComms(...a),
  previewSmsTemplate: (...a: any[]) => mockComms(...a),
}));
// more.tsx side-effect imports
jest.mock("@/src/services/pushNotifications", () => ({ registerForPushNotifications: jest.fn(), deregisterPushToken: jest.fn() }));
jest.mock("@/src/components/sync/ManualSyncButton", () => ({ ManualSyncButton: () => null }));
jest.mock("@/src/utils/diagnostics", () => ({ getDiagnostics: () => [], formatDiagnostics: () => "", clearDiagnostics: jest.fn() }));
jest.mock("@/src/components/fleet/FleetPauseToggle", () => () => null);
jest.mock("@/src/components/marco/MarcoVoiceSettings", () => () => null);
jest.mock("@/src/hooks/useIndustries", () => ({ useIndustries: () => ({ industries: [] }) }));
jest.mock("expo-image", () => ({ Image: () => null }));

import MarketingFormsScreen from "@/app/admin/marketing/forms/index";
import MarketingFormDetailScreen from "@/app/admin/marketing/forms/[id]";
import FormSubmissionsScreen from "@/app/admin/marketing/forms/submissions/index";
import FormSubmissionDetailScreen from "@/app/admin/marketing/forms/submissions/[sid]";
import CommsTemplatesListScreen from "@/app/(app)/comms/templates/index";
import CommsTemplateDetailScreen from "@/app/(app)/comms/templates/[code]";
import More from "@/app/(app)/more";
import { isCommsAdmin, MARKETING_FORMS_ROLES } from "@/src/components/comms/CommsAdminGate";
import { ADMIN_NAV, OWNER_NAV, canSeeEntry } from "@/src/nav/adminNav";

const FORM = { id: "f1", name: "Quote request", slug: "quote", active: true, submission_count: 1, submit_button_label: "Send",
  fields: [{ id: "a", name: "service", label: "Service", type: "text", order: 0 }] };
const SUB = { id: "s1", form_id: "f1", form_name: "Quote request", created_at: new Date().toISOString(), answers: { service: "Pool" }, customer_id: "c9" };

beforeEach(() => {
  mockRole = "owner";
  mockParams = {};
  mockComms.mockClear();
  mockGet.mockReset().mockImplementation(async (url: string) => {
    if (url === "/admin/forms") return [FORM];
    if (url === "/admin/forms/f1") return FORM;
    if (url === "/admin/forms/f1/versions") return { versions: [{ id: "v1", version: 1, action: "create", at: "2026-10-01T10:00:00Z" }] };
    if (url.startsWith("/admin/forms/f1/submissions")) return [SUB];
    throw new Error(url);
  });
});

const entry = (route: string) => ADMIN_NAV.flatMap((g) => g.entries).find((e) => e.route === route)!;
const flush = () => act(async () => {});

describe("owner → Marketing Forms + submissions admitted", () => {
  it("forms list", async () => {
    const q = render(<MarketingFormsScreen />);
    await flush();
    expect(q.queryByTestId("comms-admin-gate-denied")).toBeNull();
    expect(q.getByTestId("marketing-form-row-f1")).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith("/admin/forms");
  });

  it("form detail: preview, versions, settings", async () => {
    mockParams = { id: "f1" };
    const q = render(<MarketingFormDetailScreen />);
    await flush();
    expect(q.getByTestId("form-preview")).toBeTruthy();
    fireEvent.press(q.getByTestId("marketing-form-tab-versions"));
    await flush();
    expect(q.getByTestId("form-version-1")).toBeTruthy();
    fireEvent.press(q.getByTestId("marketing-form-tab-settings"));
    expect(q.getByTestId("form-settings")).toBeTruthy();
  });

  it("submissions inbox + submission detail", async () => {
    const q = render(<FormSubmissionsScreen />);
    await flush();
    expect(q.getByTestId("form-sub-row-s1")).toBeTruthy();
    mockParams = { sid: "s1", fid: "f1" };
    const d = render(<FormSubmissionDetailScreen />);
    await flush();
    expect(d.queryByTestId("comms-admin-gate-denied")).toBeNull();
    expect(d.getByText("Pool")).toBeTruthy();
  });
});

describe("REGRESSION — owner stays blocked elsewhere", () => {
  it("Email Builder list + detail denied, no comms fetch", async () => {
    mockParams = { code: "system.appointment_reminder", channel: "email" };
    const a = render(<CommsTemplatesListScreen />);
    const b = render(<CommsTemplateDetailScreen />);
    await flush();
    expect(a.getByTestId("comms-admin-gate-denied")).toBeTruthy();
    expect(b.getByTestId("comms-admin-gate-denied")).toBeTruthy();
    expect(mockComms).not.toHaveBeenCalled();
    expect(isCommsAdmin("owner")).toBe(false);
    expect(canSeeEntry("owner", entry("/admin/comms/email"))).toBe(false);
    expect(canSeeEntry("owner", entry("/admin/comms/templates"))).toBe(false);
  });

  it("Templates Library not reachable from owner nav", () => {
    expect(canSeeEntry("owner", entry("/(app)/templates"))).toBe(false);
    expect(OWNER_NAV.entries.map((e) => e.route)).toEqual(["/admin/marketing/forms"]);
  });

  it("More as owner: only the Marketing Forms group, no admin drawer", () => {
    const q = render(<More />);
    expect(q.getByTestId("drawer-group-owner_marketing")).toBeTruthy();
    expect(q.getByTestId("drawer-nav-marketing-forms")).toBeTruthy();
    for (const id of ["drawer-nav-comms-email", "drawer-nav-comms-templates", "drawer-nav-os-templates-library", "drawer-group-quick_access"]) {
      expect(q.queryByTestId(id)).toBeNull();
    }
  });
});

describe("other roles unchanged", () => {
  it.each(["admin", "super_admin"])("%s: admitted on all 4 screens; More shows admin drawer, no owner group", async (role) => {
    mockRole = role;
    mockParams = { id: "f1", sid: "s1", fid: "f1" };
    for (const S of [MarketingFormsScreen, MarketingFormDetailScreen, FormSubmissionsScreen, FormSubmissionDetailScreen]) {
      const q = render(<S />);
      await flush();
      expect(q.queryByTestId("comms-admin-gate-denied")).toBeNull();
    }
    const m = render(<More />);
    expect(m.getByTestId("drawer-nav-marketing-forms")).toBeTruthy();
    expect(m.getByTestId("drawer-nav-comms-email")).toBeTruthy();
    expect(m.queryByTestId("drawer-group-owner_marketing")).toBeNull();
  });

  it.each(["manager", "technician"])("%s: denied on all 4 screens, no fetch, no Marketing Forms entry", async (role) => {
    mockRole = role;
    mockParams = { id: "f1", sid: "s1", fid: "f1" };
    for (const S of [MarketingFormsScreen, MarketingFormDetailScreen, FormSubmissionsScreen, FormSubmissionDetailScreen]) {
      const q = render(<S />);
      await flush();
      expect(q.getByTestId("comms-admin-gate-denied")).toBeTruthy();
    }
    expect(mockGet).not.toHaveBeenCalled();
    const m = render(<More />);
    expect(m.queryByTestId("drawer-nav-marketing-forms")).toBeNull();
    expect(m.queryByTestId("drawer-group-owner_marketing")).toBeNull();
    expect(canSeeEntry(role, entry("/admin/marketing/forms"))).toBe(false);
  });

  it("role sets", () => {
    expect([...MARKETING_FORMS_ROLES]).toEqual(["admin", "super_admin", "owner"]);
    expect(isCommsAdmin("admin") && isCommsAdmin("super_admin")).toBe(true);
  });
});
