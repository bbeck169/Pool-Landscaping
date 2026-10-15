/**
 * Form Builder mobile parity C2 — read-only submissions inbox + detail.
 */
import React from "react";
import { render, fireEvent, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockGet(...a), post: (...a: any[]) => mockPost(...a) } }));
let mockRole = "admin";
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: mockRole } }) }));
const mockPush = jest.fn();
let mockParams: any = {};
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn() }),
  useLocalSearchParams: () => mockParams,
}));
jest.mock("@/src/components/widgets", () => {
  const RN = require("react-native");
  return { Header: (p: any) => <RN.View><RN.Text>{p.title}</RN.Text></RN.View> };
});

import FormSubmissionsScreen from "@/app/admin/marketing/forms/submissions/index";
import FormSubmissionDetailScreen from "@/app/admin/marketing/forms/submissions/[sid]";
import { inRange, summaryLine, destinationLabel, formatAnswer, isSensitive, ALL_FORMS_FANOUT_CAP } from "@/src/utils/formSubmissions";

const NOW = Date.now();
const iso = (daysAgo: number) => new Date(NOW - daysAgo * 86400000).toISOString();
const FORMS = [
  { id: "f1", name: "Quote request", submission_count: 2, fields: [
    { id: "a", name: "email", label: "Email", type: "email", pii_tag: "contact" },
    { id: "b", name: "service", label: "Service", type: "dropdown" },
    { id: "c", name: "extras", label: "Extras", type: "multiselect" },
  ] },
  { id: "f2", name: "Newsletter", submission_count: 1, fields: [] },
  { id: "f3", name: "Empty", submission_count: 0, fields: [] },
];
const SUBS: Record<string, any[]> = {
  f1: [
    { id: "s1", form_id: "f1", form_name: "Quote request", created_at: iso(1), answers: { email: "jane@x.com", service: "Pool", extras: ["Salt", "Algae"] }, ip: "1.2.3.4", user_agent: "UA/1", page_url: "https://site/quote", customer_id: "cust-9" },
    { id: "s2", form_id: "f1", form_name: "Quote request", created_at: iso(20), answers: { email: "old@x.com" }, lead_id: "lead-3" },
  ],
  f2: [{ id: "s3", form_id: "f2", form_name: "Newsletter", created_at: iso(3), data: { name: "Bob", email: "bob@x.com" } }],
};
beforeEach(() => {
  mockRole = "admin";
  mockParams = {};
  mockPush.mockReset();
  mockPost.mockReset();
  mockGet.mockReset().mockImplementation(async (url: string) => {
    if (url === "/admin/forms") return FORMS;
    const m = url.match(/^\/admin\/forms\/(f\d)\/submissions/);
    if (m) return SUBS[m[1]] || [];
    const g = url.match(/^\/admin\/forms\/(f\d)$/);
    if (g) return FORMS.find((f) => f.id === g[1]);
    throw new Error(url);
  });
});
const subCalls = () => mockGet.mock.calls.map((c) => c[0]).filter((u: string) => u.includes("/submissions"));

describe("submissions inbox", () => {
  it("1. All forms: fetches only forms with submissions, merges newest-first", async () => {
    const q = render(<FormSubmissionsScreen />);
    await act(async () => {});
    expect(subCalls().sort()).toEqual(["/admin/forms/f1/submissions?limit=50", "/admin/forms/f2/submissions?limit=50"]);
    expect(q.getAllByTestId(/^form-sub-row-/).map((n) => n.props.testID)).toEqual(["form-sub-row-s1", "form-sub-row-s3", "form-sub-row-s2"]);
    expect(q.getByText("Bob · bob@x.com")).toBeTruthy(); // falls back to `data`
    expect(q.getByTestId("form-sub-dest-s1").props.children).toEqual(["→ ", "Customer"]);
    expect(q.queryByTestId("form-subs-filter-f3")).toBeNull(); // zero-submission forms hidden
    expect(ALL_FORMS_FANOUT_CAP).toBe(25);
  });

  it("2. filter by form → per-form fetch; date range narrows client-side", async () => {
    const q = render(<FormSubmissionsScreen />);
    await act(async () => {});
    await act(async () => { fireEvent.press(q.getByTestId("form-subs-filter-f1")); });
    expect(mockGet).toHaveBeenLastCalledWith("/admin/forms/f1/submissions?limit=100");
    expect(q.queryByTestId("form-sub-row-s3")).toBeNull();
    expect(q.getByTestId("form-sub-row-s2")).toBeTruthy();
    fireEvent.press(q.getByTestId("form-subs-range-7d"));
    expect(q.queryByTestId("form-sub-row-s2")).toBeNull();
    expect(q.getByTestId("form-sub-row-s1")).toBeTruthy();
    fireEvent.press(q.getByTestId("form-sub-row-s1"));
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/admin/marketing/forms/submissions/[sid]", params: { sid: "s1", fid: "f1" } });
  });

  it("3. deep-link ?fid preselects the form", async () => {
    mockParams = { fid: "f2" };
    const q = render(<FormSubmissionsScreen />);
    await act(async () => {});
    expect(subCalls()).toEqual(["/admin/forms/f2/submissions?limit=100"]);
    expect(q.getByTestId("form-sub-row-s3")).toBeTruthy();
  });

  it.each(["manager", "owner", "technician"])("4. role gate: %s blocked, no fetch", async (role) => {
    mockRole = role;
    const q = render(<FormSubmissionsScreen />);
    await act(async () => {});
    expect(q.getByTestId("comms-admin-gate-denied")).toBeTruthy();
    expect(mockGet).not.toHaveBeenCalled();
  });
});

describe("submission detail", () => {
  it("5. renders every answer (schema labels), metadata, destination; PII masked until tapped", async () => {
    mockParams = { sid: "s1", fid: "f1" };
    const q = render(<FormSubmissionDetailScreen />);
    await act(async () => {});
    expect(q.getByText("Service")).toBeTruthy();
    expect(q.getByText("Pool")).toBeTruthy();
    expect(q.getByText("Salt, Algae")).toBeTruthy();
    expect(q.queryByText("jane@x.com")).toBeNull();
    fireEvent.press(q.getByTestId("form-submission-answer-email-reveal"));
    expect(q.getByText("jane@x.com")).toBeTruthy();
    for (const v of ["1.2.3.4", "UA/1", "https://site/quote"]) expect(q.getByText(v)).toBeTruthy();
    fireEvent.press(q.getByTestId("form-submission-customer-link"));
    expect(mockPush).toHaveBeenCalledWith("/customer/cust-9");
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("6. lead destination + unknown sid", async () => {
    mockParams = { sid: "s2", fid: "f1" };
    const q = render(<FormSubmissionDetailScreen />);
    await act(async () => {});
    expect(q.getByTestId("form-submission-lead")).toBeTruthy();
    mockParams = { sid: "nope", fid: "f1" };
    const q2 = render(<FormSubmissionDetailScreen />);
    await act(async () => {});
    expect(q2.getByTestId("form-submission-error")).toBeTruthy();
  });

  it("7. manager blocked on detail", async () => {
    mockRole = "manager";
    mockParams = { sid: "s1", fid: "f1" };
    const q = render(<FormSubmissionDetailScreen />);
    expect(q.getByTestId("comms-admin-gate-denied")).toBeTruthy();
  });
});

describe("helpers", () => {
  it("inRange / summaryLine / destinationLabel / formatAnswer / isSensitive", () => {
    expect(inRange(iso(3), "7d", NOW)).toBe(true);
    expect(inRange(iso(8), "7d", NOW)).toBe(false);
    expect(inRange(undefined, "30d", NOW)).toBe(false);
    expect(inRange(undefined, "all", NOW)).toBe(true);
    expect(summaryLine({ id: "x", form_id: "f", answers: { first_name: "A", last_name: "B", phone: "555" } })).toBe("A B · 555");
    expect(destinationLabel({ id: "x", form_id: "f", lead_id: "l", customer_id: "c" })).toBe("Customer");
    expect([formatAnswer(true), formatAnswer(""), formatAnswer(["a", 2]), formatAnswer({ k: 1 })]).toEqual(["Yes", "—", "a, 2", '{"k":1}']);
    expect([isSensitive({ pii_tag: "x" }), isSensitive({ is_customer_facing: false }), isSensitive({}), isSensitive(undefined)]).toEqual([true, true, false, false]);
  });
});
