/**
 * A1 · shared `viewAsCustomer` (src/lib/portalViewAsCustomer.ts), factored
 * verbatim out of PortalAccessPanel. Pure-function dependency/order checks;
 * the panel's rendered behaviour stays locked by td91-view-as-customer.
 */
import * as fs from "fs";
import * as path from "path";

const mockPost = jest.fn();
const mockOpenBrowser = jest.fn();
jest.mock("@/src/api", () => {
  class ApiError extends Error {
    status: number; detail: any;
    constructor(status: number, detail: any) { super(String(detail)); this.status = status; this.detail = detail; }
  }
  return { api: { post: (u: string, b?: any) => mockPost(u, b) }, ApiError };
});
jest.mock("expo-web-browser", () => ({ openBrowserAsync: (u: string) => mockOpenBrowser(u) }));

// eslint-disable-next-line import/first
import { Linking } from "react-native";
// eslint-disable-next-line import/first
import { ApiError } from "@/src/api";
// eslint-disable-next-line import/first
import { viewAsCustomer } from "@/src/lib/portalViewAsCustomer";

const AE: any = ApiError;
let openURLSpy: jest.SpyInstance;
const ENV0 = { web: process.env.EXPO_PUBLIC_WEB_URL, be: process.env.EXPO_PUBLIC_BACKEND_URL };

function deps() {
  const log: string[] = [];
  const setBusy = jest.fn((b: boolean) => { log.push(`busy:${b}`); });
  const showToast = jest.fn((m: string, v?: string) => { log.push(`toast:${v}:${m}`); });
  return { log, setBusy, showToast };
}

beforeEach(() => {
  mockPost.mockReset().mockImplementation(async () => { return { access_token: "tok.en/+=" }; });
  mockOpenBrowser.mockReset().mockResolvedValue({ type: "dismiss" });
  delete process.env.EXPO_PUBLIC_WEB_URL;
  process.env.EXPO_PUBLIC_BACKEND_URL = "https://api.example.com/api/";
  openURLSpy = jest.spyOn(Linking, "openURL").mockResolvedValue(true as any);
});
afterEach(() => {
  openURLSpy.mockRestore();
  if (ENV0.web === undefined) delete process.env.EXPO_PUBLIC_WEB_URL; else process.env.EXPO_PUBLIC_WEB_URL = ENV0.web;
  process.env.EXPO_PUBLIC_BACKEND_URL = ENV0.be;
});

describe("A1 · viewAsCustomer (shared lib)", () => {
  it("busy on → POST /admin/impersonate/{id} {} → browser at <origin>/portal/home?impersonation_token=<enc> → busy off", async () => {
    const d = deps();
    mockPost.mockImplementation(async () => { d.log.push("post"); return { access_token: "tok.en/+=" }; });
    mockOpenBrowser.mockImplementation(async (u: string) => { d.log.push(`open:${u}`); return { type: "dismiss" }; });
    await viewAsCustomer("cust-1", d);
    expect(mockPost).toHaveBeenCalledWith("/admin/impersonate/cust-1", {});
    expect(d.log).toEqual([
      "busy:true", "post",
      "open:https://api.example.com/portal/home?impersonation_token=tok.en%2F%2B%3D",
      "busy:false",
    ]);
    expect(d.showToast).not.toHaveBeenCalled();
    expect(openURLSpy).not.toHaveBeenCalled();
  });

  it("EXPO_PUBLIC_WEB_URL wins (trailing slashes trimmed)", async () => {
    process.env.EXPO_PUBLIC_WEB_URL = "https://web.example.com//";
    await viewAsCustomer("c2", deps());
    expect(mockOpenBrowser).toHaveBeenCalledWith("https://web.example.com/portal/home?impersonation_token=tok.en%2F%2B%3D");
  });

  it.each([
    [new AE(403, "Forbidden"), "Access denied — only admins can view the portal as a customer."],
    [new AE(400, "This customer has no login yet. Create a login for them first."), "This customer has no login yet. Create a login for them first."],
    // Same network-error shape as td91 (api wrapper tags transport failures kind: "network").
    [Object.assign(new Error("Network request failed"), { kind: "network" }), "Couldn't reach the server — check your connection and try again."],
  ])("POST failure %# → one error toast, no browser, busy still cleared", async (err, msg) => {
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    mockPost.mockRejectedValue(err);
    const d = deps();
    await viewAsCustomer("cust-1", d);
    expect(d.log).toEqual(["busy:true", `toast:error:${msg}`, "busy:false"]);
    expect(mockOpenBrowser).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("empty token → retry toast, no browser", async () => {
    mockPost.mockResolvedValue({});
    const d = deps();
    await viewAsCustomer("cust-1", d);
    expect(d.log).toEqual(["busy:true", "toast:error:Couldn't start the customer session — please try again.", "busy:false"]);
    expect(mockOpenBrowser).not.toHaveBeenCalled();
  });

  it("browser fails → Linking.openURL fallback; both fail → final toast", async () => {
    mockOpenBrowser.mockRejectedValue(new Error("no browser"));
    const a = deps();
    await viewAsCustomer("cust-1", a);
    expect(openURLSpy).toHaveBeenCalledWith("https://api.example.com/portal/home?impersonation_token=tok.en%2F%2B%3D");
    expect(a.showToast).not.toHaveBeenCalled();
    openURLSpy.mockRejectedValue(new Error("no handler"));
    const b = deps();
    await viewAsCustomer("cust-1", b);
    expect(b.log).toEqual(["busy:true", "toast:error:Couldn't open the browser — please try again.", "busy:false"]);
  });

  it("PortalAccessPanel calls the shared lib (no inline copy left)", () => {
    const src = fs.readFileSync(path.resolve(__dirname, "../src/components/customers/PortalAccessPanel.tsx"), "utf8");
    expect(src).toContain('import { viewAsCustomer as runViewAsCustomer } from "@/src/lib/portalViewAsCustomer";');
    expect(src).toContain('runViewAsCustomer(customerId, { setBusy: (on) => setBusy(on ? "view-as" : ""), showToast })');
    expect(src).not.toContain("/admin/impersonate/");
    expect(src).not.toContain("openBrowserAsync");
    expect(src).toContain("onPress={viewAsCustomer}");
  });
});
