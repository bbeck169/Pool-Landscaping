/**
 * TD-91 · Portal Access "View as customer" → customer portal in the
 * in-app browser (web `cd-impersonate` parity). The header button is
 * the distinct "Switch to customer view" (in-app session swap).
 */
import React from "react";
import * as fs from "fs";
import * as path from "path";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockToast = jest.fn();
const mockOpenBrowser = jest.fn();
const mockStartImpersonation = jest.fn();
const mockSecureSet = jest.fn();
let mockStatus: any = { has_login: true, active: true, email: "c@x.com" };

jest.mock("@/src/api", () => {
  class ApiError extends Error {
    status: number; detail: any;
    constructor(status: number, detail: any) { super(String(detail)); this.status = status; this.detail = detail; }
  }
  return { api: { get: (u: string) => mockGet(u), post: (u: string, b?: any) => mockPost(u, b) }, ApiError };
});
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));
jest.mock("expo-web-browser", () => ({ openBrowserAsync: (u: string) => mockOpenBrowser(u) }));
jest.mock("expo-clipboard", () => ({ setStringAsync: jest.fn() }));
// Session store sentinels: the new button must never call either.
jest.mock("@/src/auth", () => ({ useAuth: () => ({ startImpersonation: mockStartImpersonation }) }));
jest.mock("@/src/utils/storage", () => ({ storage: { secureSet: mockSecureSet, setItem: jest.fn(), getItem: jest.fn() } }));

import { Linking } from "react-native";
import { ApiError } from "@/src/api";
import PortalAccessPanel from "@/src/components/customers/PortalAccessPanel";

const ENV0 = { web: process.env.EXPO_PUBLIC_WEB_URL, be: process.env.EXPO_PUBLIC_BACKEND_URL };
let openURLSpy: jest.SpyInstance;

beforeEach(() => {
  mockGet.mockReset().mockImplementation(async (u: string) => (u.includes("portal-status") ? mockStatus : { events: [] }));
  mockPost.mockReset().mockResolvedValue({ access_token: "tok.en/+=", impersonator_name: "Alex Admin" });
  mockToast.mockClear(); mockOpenBrowser.mockReset().mockResolvedValue({ type: "dismiss" });
  mockStartImpersonation.mockClear(); mockSecureSet.mockClear();
  mockStatus = { has_login: true, active: true, email: "c@x.com" };
  delete process.env.EXPO_PUBLIC_WEB_URL;
  process.env.EXPO_PUBLIC_BACKEND_URL = "https://api.example.com";
  openURLSpy = jest.spyOn(Linking, "openURL").mockResolvedValue(true as any);
});
afterEach(() => {
  openURLSpy.mockRestore();
  if (ENV0.web === undefined) delete process.env.EXPO_PUBLIC_WEB_URL; else process.env.EXPO_PUBLIC_WEB_URL = ENV0.web;
  process.env.EXPO_PUBLIC_BACKEND_URL = ENV0.be;
});

const mount = async (role = "admin") => {
  const q = render(<PortalAccessPanel customerId="cust-1" customerEmail="c@x.com" customerName="Cora" hasLogin userRole={role} onRefresh={jest.fn()} />);
  await waitFor(() => q.getByTestId("portal-actions-row"));
  return q;
};
const tap = async (q: any) => { await act(async () => { fireEvent.press(q.getByTestId("portal-view-as-customer-btn")); }); };

describe("visibility + state", () => {
  it.each([["admin", true], ["super_admin", true], ["owner", false], ["manager", false], ["technician", false]])(
    "%s → visible=%s (hidden entirely, not disabled)", async (role, visible) => {
      const q = await mount(role as string);
      expect(!!q.queryByTestId("portal-view-as-customer-btn")).toBe(visible);
    });

  it("placed right after Reset password, same ActionButton style as its siblings", async () => {
    const q = await mount();
    const ids = q.UNSAFE_root.findAll((n: any) => typeof n.type === "string" && /^portal-.*-btn$/.test(String(n.props?.testID)))
      .map((n: any) => n.props.testID).filter((v: string, i: number, a: string[]) => a.indexOf(v) === i);
    expect(ids.indexOf("portal-view-as-customer-btn")).toBe(ids.indexOf("portal-reset-password-btn") + 1);
    const flat = (id: string) => Object.assign({}, ...[].concat(q.getByTestId(id).props.style).flat().filter(Boolean));
    const a = flat("portal-view-as-customer-btn"), b = flat("portal-reset-password-btn");
    for (const k of ["backgroundColor", "borderRadius", "paddingHorizontal", "flexDirection", "alignItems"]) expect([k, a[k]]).toEqual([k, b[k]]);
    expect(q.getByText("View as customer")).toBeTruthy();
  });

  it("disabled when the portal login is inactive", async () => {
    mockStatus = { has_login: true, active: false, email: "c@x.com" };
    const q = await mount();
    await waitFor(() => expect(q.getByTestId("portal-view-as-customer-btn").props.accessibilityState?.disabled).toBe(true));
  });

  it("disabled while busy (in flight) — second tap does not re-post", async () => {
    let release: (v: any) => void = () => {};
    mockPost.mockImplementationOnce(() => new Promise((r) => { release = r; }));
    const q = await mount();
    await tap(q);
    expect(q.getByTestId("portal-view-as-customer-btn").props.accessibilityState?.disabled).toBe(true);
    await tap(q);
    expect(mockPost).toHaveBeenCalledTimes(1);
    await act(async () => { release({ access_token: "t" }); });
  });
});

describe("tap flow", () => {
  it("POST /admin/impersonate/{id} → in-app browser at <backend origin>/portal/home?impersonation_token=<encoded>; admin session untouched", async () => {
    const q = await mount();
    await tap(q);
    expect(mockPost).toHaveBeenCalledWith("/admin/impersonate/cust-1", {});
    expect(mockOpenBrowser).toHaveBeenCalledWith("https://api.example.com/portal/home?impersonation_token=tok.en%2F%2B%3D");
    expect(mockStartImpersonation).not.toHaveBeenCalled();
    expect(mockSecureSet).not.toHaveBeenCalled();
    expect(openURLSpy).not.toHaveBeenCalled();
    expect(mockToast).not.toHaveBeenCalled();
  });

  it("EXPO_PUBLIC_WEB_URL set → used (trailing slash trimmed); backend fallback strips a trailing /api", async () => {
    process.env.EXPO_PUBLIC_WEB_URL = "https://app.example.com/";
    const q = await mount();
    await tap(q);
    expect(mockOpenBrowser.mock.calls[0][0]).toBe("https://app.example.com/portal/home?impersonation_token=tok.en%2F%2B%3D");
    delete process.env.EXPO_PUBLIC_WEB_URL;
    process.env.EXPO_PUBLIC_BACKEND_URL = "https://api.example.com/api/";
    await tap(q);
    expect(mockOpenBrowser.mock.calls[1][0]).toBe("https://api.example.com/portal/home?impersonation_token=tok.en%2F%2B%3D");
  });
});

describe("errors", () => {
  it("BE 400 (no login) → toast with the BE message; browser not opened", async () => {
    mockPost.mockRejectedValueOnce(new (ApiError as any)(400, "This customer has no login yet. Create a login for them first."));
    const q = await mount();
    await tap(q);
    expect(mockToast).toHaveBeenCalledWith("This customer has no login yet. Create a login for them first.", "error");
    expect(mockOpenBrowser).not.toHaveBeenCalled();
  });

  it("BE 403 → access-denied toast (+ console.warn log)", async () => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    mockPost.mockRejectedValueOnce(new (ApiError as any)(403, "Admin access required"));
    const q = await mount();
    await tap(q);
    expect(mockToast).toHaveBeenCalledWith("Access denied — only admins can view the portal as a customer.", "error");
    expect(warn).toHaveBeenCalledWith("[portal] view-as-customer forbidden", 403);
    expect(mockOpenBrowser).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("network failure → retriable toast", async () => {
    mockPost.mockRejectedValueOnce(Object.assign(new Error("Network request failed"), { kind: "network" }));
    const q = await mount();
    await tap(q);
    expect(mockToast).toHaveBeenCalledWith("Couldn't reach the server — check your connection and try again.", "error");
  });

  it("in-app browser fails → Linking.openURL fallback; both fail → final toast", async () => {
    mockOpenBrowser.mockRejectedValue(new Error("no browser"));
    const q = await mount();
    await tap(q);
    expect(openURLSpy).toHaveBeenCalledWith("https://api.example.com/portal/home?impersonation_token=tok.en%2F%2B%3D");
    expect(mockToast).not.toHaveBeenCalled();
    openURLSpy.mockRejectedValueOnce(new Error("no handler"));
    await tap(q);
    expect(mockToast).toHaveBeenCalledWith("Couldn't open the browser — please try again.", "error");
  });
});

it("header in-app swap is relabelled 'Switch to customer view' (button + confirm sheet), behaviour unchanged", () => {
  const src = fs.readFileSync(path.resolve(__dirname, "../app/customer/[id].tsx"), "utf8");
  expect(src).toMatch(/impersonating \? "Switching…" : "Switch to customer view"/);
  expect(src).toMatch(/title="Switch to customer view" testID="impersonate-confirm-sheet"/);
  expect(src).toMatch(/<PrimaryButton title="Switch to customer view"[^>]*onPress=\{doImpersonate\}/);
  expect(src).not.toMatch(/"View as customer"/);
  expect(src).toMatch(/await startImpersonation\(id as string\)/);
});
