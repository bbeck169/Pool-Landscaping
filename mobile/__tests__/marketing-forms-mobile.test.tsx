/**
 * Form Builder Phases 1+2 — mobile parity C1 (read-only):
 * forms list + preview (ported show_if) + version history + settings.
 */
import * as fs from "fs";
import * as path from "path";
import React from "react";
import { render, fireEvent, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockGet(...a), post: (...a: any[]) => mockPost(...a), patch: (...a: any[]) => mockPost(...a) } }));
let mockRole = "admin";
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: mockRole } }) }));
const mockPush = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn() }),
  useLocalSearchParams: () => ({ id: "f1" }),
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, [cb]),
}));
jest.mock("@/src/components/widgets", () => {
  const RN = require("react-native");
  return { Header: (p: any) => <RN.View><RN.Text>{p.title}</RN.Text>{p.right}</RN.View> };
});
const mockToast = jest.fn();
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));
const mockCopy = jest.fn().mockResolvedValue(true);
jest.mock("expo-clipboard", () => ({ setStringAsync: (...a: any[]) => mockCopy(...a) }));

import * as MobileShowIf from "@/src/utils/formShowIf";
import FormSchemaPreview from "@/src/components/forms/FormSchemaPreview";
import MarketingFormsScreen from "@/app/admin/marketing/forms/index";
import MarketingFormDetailScreen from "@/app/admin/marketing/forms/[id]";
import { ADMIN_NAV, canSeeEntry } from "@/src/nav/adminNav";

/* Load the REAL web evaluator (ESM → CJS-ish) to prove algorithm parity. */
const WEB_SRC = fs.readFileSync(path.resolve(__dirname, "../../frontend/src/lib/formShowIf.js"), "utf-8");
// eslint-disable-next-line no-new-func
const Web = new Function(`${WEB_SRC.replace(/export function/g, "function")}; return { coerceForCompare, isFieldVisible, stripHiddenAnswers };`)();

const SVC = { id: "a", name: "service", type: "dropdown", label: "Service", options: ["Pool", "Landscape", "Both"], order: 0 };
const POOL_SIZE = { id: "b", name: "pool_size", type: "text", label: "Pool size", order: 1, show_if: { field_id: "a", operator: "eq", value: "Pool" } };
const NOTES = { id: "c", name: "notes", type: "textarea", label: "Notes", order: 2 };
const FORM = { id: "f1", name: "Quote request", slug: "quote", active: true, submission_count: 4, fields: [NOTES, POOL_SIZE, SVC], submit_button_label: "Send" };

beforeEach(() => {
  mockRole = "admin";
  mockGet.mockReset().mockImplementation(async (url: string) => {
    if (url === "/admin/forms") return [FORM, { id: "f2", name: "Newsletter", slug: "news", active: false, fields: [] }];
    if (url === "/admin/forms/f1") return FORM;
    if (url === "/admin/forms/f1/versions") return { versions: [
      { id: "v1", version: 1, action: "create", at: "2026-10-01T10:00:00Z" },
      { id: "v3", version: 3, action: "revert", at: "2026-10-03T10:00:00Z" },
      { id: "v2", version: 2, action: "update", at: "2026-10-02T10:00:00Z" },
    ] };
    throw new Error(`unexpected ${url}`);
  });
  mockPost.mockReset();
  mockPush.mockReset();
  mockCopy.mockClear();
});

describe("formShowIf — ported 1:1 from web formShowIf.js", () => {
  const byId = { a: SVC, x: { id: "x", name: "tags" }, y: { id: "y" } } as any;
  const CASES: [any, any][] = [
    [null, {}], [{ id: "n" }, {}], [{ show_if: "bad" }, {}],
    [{ show_if: { field_id: "missing", operator: "eq", value: "Pool" } }, {}], // fail-open
    [POOL_SIZE, { service: "Pool" }], [POOL_SIZE, { service: " Pool " }], [POOL_SIZE, { service: "Both" }], [POOL_SIZE, {}],
    [POOL_SIZE, { a: "Pool" }], // falls back to field_id key
    [{ show_if: { field_id: "a", operator: "neq", value: "Pool" } }, { service: "Pool" }],
    [{ show_if: { field_id: "a", operator: "eq", value: "" } }, { service: "" }], // "" → null both sides
    [{ show_if: { field_id: "x", operator: "contains", value: "Salt" } }, { tags: ["Salt", "Algae"] }],
    [{ show_if: { field_id: "x", operator: "contains", value: "alt" } }, { tags: "Salty" }],
    [{ show_if: { field_id: "x", operator: "contains", value: 5 } }, { tags: 55 }],
    [{ show_if: { field_id: "y", operator: "eq", value: "1" } }, { y: "1" }],
    [{ show_if: { field_id: "a", operator: "gt", value: 1 } }, { service: 2 }], // unknown op → visible
  ];
  it("isFieldVisible matches web on every branch", () => {
    for (const [field, answers] of CASES) {
      expect([field, answers, MobileShowIf.isFieldVisible(field, answers, byId)]).toEqual([field, answers, Web.isFieldVisible(field, answers, byId)]);
    }
  });
  it("coerceForCompare + stripHiddenAnswers match web", () => {
    for (const v of [null, undefined, "", "  x ", 0, false, ["a"]]) expect(MobileShowIf.coerceForCompare(v)).toEqual(Web.coerceForCompare(v));
    const fields = [SVC, POOL_SIZE, NOTES];
    for (const ans of [{ service: "Both", pool_size: "20k", b: 1 }, { service: "Pool", pool_size: "20k" }, {}]) {
      expect(MobileShowIf.stripHiddenAnswers(fields, ans)).toEqual(Web.stripHiddenAnswers(fields, ans));
    }
    expect(MobileShowIf.stripHiddenAnswers([], { k: 1 })).toEqual(Web.stripHiddenAnswers([], { k: 1 }));
  });
});

describe("forms list", () => {
  it("renders name, slug, status, submission count; tap → detail", async () => {
    const q = render(<MarketingFormsScreen />);
    await act(async () => {});
    expect(q.getByText("Quote request")).toBeTruthy();
    expect(q.getByText("/quote")).toBeTruthy();
    expect(q.getByTestId("marketing-form-status-f1")).toBeTruthy();
    expect(q.getByText("Inactive")).toBeTruthy();
    expect(q.getByTestId("marketing-form-subs-f1").props.children).toEqual([4, " submissions"]);
    fireEvent.press(q.getByTestId("marketing-form-row-f1"));
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/admin/marketing/forms/[id]", params: { id: "f1" } });
  });

  it.each(["manager", "owner", "technician"])("role gate: %s → denied, no fetch", async (role) => {
    mockRole = role;
    const q = render(<MarketingFormsScreen />);
    await act(async () => {});
    expect(q.getByTestId("comms-admin-gate-denied")).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it("drawer entry is admin + super_admin only", () => {
    const e = ADMIN_NAV.flatMap((g) => g.entries).find((x) => x.route === "/admin/marketing/forms")!;
    expect(e.roles).toEqual(["super_admin", "admin"]);
    expect(canSeeEntry("admin", e) && canSeeEntry("super_admin", e)).toBe(true);
    expect(canSeeEntry("manager", e) || canSeeEntry("owner", e) || canSeeEntry("technician", e)).toBe(false);
  });
});

describe("preview · show_if live", () => {
  it("conditional field hidden until parent answer matches; order respected", () => {
    const q = render(<FormSchemaPreview fields={FORM.fields as any} />);
    expect(q.queryByTestId("form-preview-field-pool_size")).toBeNull();
    expect(q.getByTestId("form-preview-hidden-count").props.children).toEqual([1, " field", "", " hidden by conditional logic"]);
    const order = q.toJSON() ? JSON.stringify(q.toJSON()) : "";
    expect(order.indexOf("Service")).toBeLessThan(order.indexOf("Notes"));
    fireEvent.press(q.getByTestId("form-preview-opt-service-Pool"));
    expect(q.getByTestId("form-preview-field-pool_size")).toBeTruthy();
    expect(q.getByTestId("form-preview-conditional-pool_size")).toBeTruthy();
    fireEvent.press(q.getByTestId("form-preview-opt-service-Landscape"));
    expect(q.queryByTestId("form-preview-field-pool_size")).toBeNull();
  });

  it("forms without show_if render byte-identically (no Phase 2 artifacts)", () => {
    const plain = [SVC, NOTES, { id: "d", name: "email", type: "email", label: "Email", order: 3 }];
    const a = render(<FormSchemaPreview fields={plain as any} />).toJSON();
    const b = render(<FormSchemaPreview fields={plain.map((f) => ({ ...f, show_if: null })) as any} />).toJSON();
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
    const q = render(<FormSchemaPreview fields={plain as any} />);
    expect(q.queryByTestId("form-preview-hidden-count")).toBeNull();
    expect(q.queryByTestId("form-preview-conditional-service")).toBeNull();
    for (const k of ["service", "notes", "email"]) expect(q.getByTestId(`form-preview-field-${k}`)).toBeTruthy();
  });
});

describe("detail · versions + settings (read-only)", () => {
  it("versions render descending with action badges; no revert; copy desktop link", async () => {
    const q = render(<MarketingFormDetailScreen />);
    await act(async () => {});
    fireEvent.press(q.getByTestId("marketing-form-tab-versions"));
    await act(async () => {});
    const json = JSON.stringify(q.toJSON());
    const at = (n: number) => json.indexOf(`"form-version-${n}"`);
    expect(at(3)).toBeGreaterThan(-1);
    expect(at(3)).toBeLessThan(at(2));
    expect(at(2)).toBeLessThan(at(1));
    expect(q.getByText("REVERT")).toBeTruthy();
    expect(q.getByText("CREATE")).toBeTruthy();
    expect(q.getByText("Open on desktop to revert a version.")).toBeTruthy();
    await act(async () => { fireEvent.press(q.getByTestId("form-versions-copy-link")); });
    expect(mockCopy).toHaveBeenCalledWith(expect.stringMatching(/\/admin\/marketing\/forms$/));
    expect(mockPost).not.toHaveBeenCalled();
    const SRC = fs.readFileSync(path.resolve(__dirname, "../app/admin/marketing/forms/[id].tsx"), "utf-8");
    expect(SRC).not.toMatch(/api\.(post|patch|put|delete)|\/revert\//);
  });

  it("settings tab view-only", async () => {
    const q = render(<MarketingFormDetailScreen />);
    await act(async () => {});
    fireEvent.press(q.getByTestId("marketing-form-tab-settings"));
    expect(q.getByTestId("form-settings")).toBeTruthy();
    expect(q.getByText("Send")).toBeTruthy();
  });
});
