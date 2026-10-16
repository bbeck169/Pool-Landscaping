/**
 * Service report "Submit & Clock Out" — /workforce/clock-out body fix.
 * Was: `try { await api.post("/workforce/clock-out", {}) } catch {}` → always
 * 422 (ClockOutReq needs entry_id/lat/lng), silently swallowed. Now resolves
 * the open entry for this job and surfaces failures to the tech.
 */
import React from "react";
import { Alert } from "react-native";
import { render, act, fireEvent } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockReplace = jest.fn();
jest.mock("@/src/hooks/useFormTemplateRuntime", () => ({
  useFormTemplateRuntime: () => ({ fieldsById: {}, fieldsOrdered: [], isLoading: false, error: null, isEmpty: true, version: null }),
}));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: mockReplace }),
  useLocalSearchParams: () => ({ id: "j1" }),
  useFocusEffect: (cb: any) => require("react").useEffect(() => { cb(); }, []),
}));
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockGet(...a), post: (...a: any[]) => mockPost(...a), patch: jest.fn(async () => ({})) },
  TOKEN_KEY: "tok",
}));
jest.mock("@/src/utils/storage", () => ({ storage: { secureGet: async () => "jwt" } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u-tech", role: "technician" } }) }));
jest.mock("@/utils/chemistryGate", () => ({ missingCoreReadings: () => [] }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("expo-image", () => ({ Image: "Image" }));
jest.mock("expo-image-picker", () => ({}));
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));
jest.mock("@/src/services/readCache", () => ({ writeCache: async () => {}, readCache: async () => null }));
jest.mock("@/src/services/sync/photoWorker", () => ({ capturePhoto: jest.fn(), getPhotosForEntity: async () => [] }));
const mockPerm = jest.fn();
const mockPos = jest.fn();
jest.mock("expo-location", () => ({
  requestForegroundPermissionsAsync: (...a: any[]) => mockPerm(...a),
  getCurrentPositionAsync: (...a: any[]) => mockPos(...a),
  Accuracy: { High: 4 },
}));

import ServiceReport from "@/app/(app)/service-report/[id]";
import { clockOutOpenEntryForJob } from "@/src/utils/serviceReportClockOut";

const REPORT = { template: "pool", submitted_at: null, photos: [], job: { id: "j1" }, chemical_readings: [], chemicals_added: [], checklist_items: [], notes: "" };
const OPEN = { id: "te-1", job_id: "j1", user_id: "u-tech", clock_out_at: null, status: "open" };
class ApiError extends Error { status: number; detail: unknown; constructor(m: string, s: number, d: unknown) { super(m); this.status = s; this.detail = d; } }

let timesheets: any[] = [OPEN];
let alertSpy: jest.SpyInstance;
beforeEach(() => {
  timesheets = [OPEN];
  mockGet.mockReset().mockImplementation(async (url: string) => {
    if (url === "/jobs/j1/service-report") return REPORT;
    if (url === "/workforce/timesheets?status=open") return timesheets;
    return {};
  });
  mockPost.mockReset().mockImplementation(async (url: string) => (url.endsWith("/submit") ? {} : { id: "te-1" }));
  mockReplace.mockReset();
  mockPerm.mockReset().mockResolvedValue({ status: "granted" });
  mockPos.mockReset().mockResolvedValue({ coords: { latitude: 33.6, longitude: -112.3 } });
  (global as any).fetch = jest.fn(async () => ({ ok: true, json: async () => REPORT }));
  alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => {});
});
afterEach(() => alertSpy.mockRestore());

/** Press Submit, then the confirm dialog's "Submit" button. */
async function submit() {
  const q = render(<ServiceReport />);
  const btn = await q.findByTestId("svc-report-submit");
  fireEvent.press(btn);
  const confirm = alertSpy.mock.calls.find((c) => c[0] === "Submit report");
  expect(confirm).toBeTruthy();
  await act(async () => { await confirm![2].find((b: any) => b.text === "Submit").onPress(); });
  return q;
}

describe("clockOutOpenEntryForJob — backend contract", () => {
  it("POSTs {entry_id, lat, lng} for the open entry of THIS job + user", async () => {
    timesheets = [
      { id: "other-user", job_id: "j1", user_id: "u-x", clock_out_at: null },
      { id: "closed", job_id: "j1", user_id: "u-tech", clock_out_at: "2026-10-16T10:00:00Z" },
      OPEN,
    ];
    const r = await clockOutOpenEntryForJob("j1", "u-tech");
    expect(r).toEqual({ status: "closed", entryId: "te-1" });
    expect(mockPost).toHaveBeenCalledWith("/workforce/clock-out", { entry_id: "te-1", lat: 33.6, lng: -112.3 });
  });

  it("no open entry for this job → 'none', no POST (tech never clocked in via Time Clock)", async () => {
    timesheets = [{ id: "te-9", job_id: "other-job", user_id: "u-tech", clock_out_at: null }];
    expect(await clockOutOpenEntryForJob("j1", "u-tech")).toEqual({ status: "none" });
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("4xx → 'failed' with the backend detail; location denied → 'failed', no POST", async () => {
    mockPost.mockRejectedValueOnce(new ApiError("Not found", 404, "Time entry not found"));
    expect(await clockOutOpenEntryForJob("j1", "u-tech")).toEqual({ status: "failed", message: "Time entry not found" });
    mockPost.mockReset();
    mockPerm.mockResolvedValueOnce({ status: "denied" });
    const r = await clockOutOpenEntryForJob("j1", "u-tech");
    expect(r.status).toBe("failed");
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("422 with array detail falls back to the humanised message (no [object Object])", async () => {
    mockPost.mockRejectedValueOnce(new ApiError("Invalid request", 422, [{ loc: ["body", "lat"] }]));
    expect(await clockOutOpenEntryForJob("j1", "u-tech")).toEqual({ status: "failed", message: "Invalid request" });
  });
});

describe("Service report screen — Submit & Clock Out", () => {
  it("end-to-end success: submit → clock-out with contract body → navigates to Today, no error alert", async () => {
    await submit();
    expect(mockPost).toHaveBeenCalledWith("/jobs/j1/service-report/submit", {});
    expect(mockPost).toHaveBeenCalledWith("/workforce/clock-out", { entry_id: "te-1", lat: 33.6, lng: -112.3 });
    expect(mockPost).not.toHaveBeenCalledWith("/workforce/clock-out", {});
    expect(alertSpy.mock.calls.find((c) => c[0] === "Clock-out failed")).toBeUndefined();
    expect(mockReplace).toHaveBeenCalledWith("/(app)/today");
  });

  it("clock-out 4xx → 'Clock-out failed' alert surfaces the reason; report still submitted", async () => {
    mockPost.mockImplementation(async (url: string) => {
      if (url.endsWith("/submit")) return { invoice_id: "abcdef123456" };
      throw new ApiError("Bad request", 400, "Already clocked out");
    });
    await submit();
    const a = alertSpy.mock.calls.find((c) => c[0] === "Clock-out failed");
    expect(a).toBeTruthy();
    expect(a![1]).toContain("Report submitted · Invoice #abcdef12 created");
    expect(a![1]).toContain("Already clocked out");
    expect(mockReplace).not.toHaveBeenCalled();
    a![2][0].onPress();
    expect(mockReplace).toHaveBeenCalledWith("/(app)/today");
  });

  it("no open entry → no clock-out POST, no error; auto-invoice alert unchanged", async () => {
    timesheets = [];
    mockPost.mockImplementation(async () => ({ invoice_id: "inv99999xyz" }));
    await submit();
    expect(mockPost).not.toHaveBeenCalledWith("/workforce/clock-out", expect.anything());
    expect(alertSpy.mock.calls.find((c) => c[0] === "Clock-out failed")).toBeUndefined();
    const inv = alertSpy.mock.calls.find((c) => c[0] === "Auto-invoiced");
    expect(inv![1]).toBe("Report submitted · Invoice #inv99999 created");
  });
});
