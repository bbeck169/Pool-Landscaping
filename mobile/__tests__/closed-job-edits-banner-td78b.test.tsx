/**
 * TD-78b (web c1cb22dcc) — "Closed job — edits logged" banner on mobile
 * job detail + checklist, gated exactly like web: job completed AND K6
 * role. Job detail also keeps its Edit affordance for K6 roles past the
 * 24h window (web K6 parity) — label "Edit" (no countdown).
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, waitFor } from "@testing-library/react-native";

import ClosedJobEditsBanner from "@/src/components/job/ClosedJobEditsBanner";
import { canEditCompletedJob } from "@/src/lib/k6Unlock";
import JobDetail from "@/app/job/[id]";

let mockUser: any = { id: "u1", role: "admin" };
let mockJob: any = null;

function mockStub() {
  return new Proxy({ __esModule: true } as any, { get: (t, k) => (k in t ? t[k] : () => null) });
}

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(async (p: string) => (p === "/jobs/j1" ? mockJob : p.endsWith("/detail") ? {} : [])),
    post: jest.fn(), patch: jest.fn(),
  },
  api_base: () => "https://be.test/api",
  getAuthToken: jest.fn(async () => "tok"),
}));
jest.mock("react-native-safe-area-context", () => ({
  ...jest.requireActual("react-native-safe-area-context"),
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: mockUser }) }));
jest.mock("@/src/hooks/useAttendance", () => ({ useAttendance: () => ({}) }));
jest.mock("@/src/offline", () => ({
  useOnline: () => true,
  getCachedJobs: jest.fn(async () => null), cacheJob: jest.fn(), getCachedJob: jest.fn(async () => null),
  queueMutation: jest.fn(), flushPendingMutations: jest.fn(async () => {}),
}));
jest.mock("@/src/services/sync/photoWorker", () => ({
  capturePhoto: jest.fn(), getPhotosForEntity: jest.fn(async () => []),
  flushPhotos: jest.fn(async () => {}), subscribePhotos: () => () => {},
}));
jest.mock("@/src/services/sync/jobArrive", () => ({ enqueueJobArrive: jest.fn() }));
jest.mock("@/src/services/offlineWrite", () => ({ offlineWrite: jest.fn() }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("@/src/services/readCache", () =>
  new Proxy({ __esModule: true, CK: { jobDetail: (x: string) => x } } as any, {
    get: (t, k) => (k in t ? t[k] : async () => null),
  }),
);
jest.mock("expo-router", () => {
  const React = jest.requireActual("react");
  return {
    useLocalSearchParams: () => ({ id: "j1" }),
    useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
    useFocusEffect: (cb: any) => React.useEffect(cb, [cb]),
    Stack: { Screen: () => null },
    Link: () => null,
  };
});
jest.mock("@/src/components/marco/MarcoVoiceButton", () => mockStub());
jest.mock("@/src/components/OfflineBadge", () => mockStub());
jest.mock("@/src/components/files", () => mockStub());
jest.mock("@/src/components/job/FieldReport", () => mockStub());
jest.mock("@/src/components/job/MaintenanceLog", () => mockStub());
jest.mock("@/src/components/job/ServiceIssues", () => mockStub());
jest.mock("@/src/components/job/PhotoCarousel", () => mockStub());
jest.mock("@/src/components/job/JobTimerCard", () => mockStub());
jest.mock("@/src/components/media/VideoMediaUploader", () => mockStub());
jest.mock("@/src/components/schedule/CouldNotServiceButton", () => mockStub());
jest.mock("@/src/components/jobs/LineItemsSection", () => mockStub());
jest.mock("@/src/components/job/SmartBriefCard", () => mockStub());
jest.mock("@/src/components/customer", () => mockStub());
jest.mock("@/src/components/fleet/CheckInButtons", () => mockStub());

const HOURS = 3_600_000;
const job = (status: string, completedHoursAgo: number | null) => ({
  id: "j1", title: "Weekly Pool", status, customer_id: "c1",
  completed_at: completedHoursAgo == null ? null : new Date(Date.now() - completedHoursAgo * HOURS).toISOString(),
});

async function renderJD(role: string, j: any) {
  mockUser = { id: "u1", role };
  mockJob = j;
  const q = render(<JobDetail />);
  await waitFor(() => q.getByTestId("job-detail-scroll"));
  return q;
}

it("banner copy matches web (non-dismissible, no close control)", () => {
  const q = render(<ClosedJobEditsBanner />);
  expect(q.getByText("Closed job")).toBeTruthy();
  expect(q.getByText(" — edits are logged to the audit history on this job.")).toBeTruthy();
  expect(q.queryByRole("button")).toBeNull();
});

it("gate: K6 + completed only", () => {
  expect(canEditCompletedJob("admin", { status: "completed" })).toBe(true);
  expect(canEditCompletedJob("technician", { status: "active" })).toBe(false);
  expect(canEditCompletedJob("customer", { status: "completed" })).toBe(false);
  expect(canEditCompletedJob("", { status: "completed" })).toBe(false);
  expect(canEditCompletedJob("admin", null)).toBe(false);
});

describe("Job detail screen", () => {
  it("K6 role + completed → banner visible; Edit kept past 24h with no countdown", async () => {
    const q = await renderJD("technician", job("completed", 72));
    expect(q.getByTestId("job-closed-edits-logged-banner")).toBeTruthy();
    expect(q.getByTestId("job-edit-button-label").props.children).toBe("Edit");
  });

  it("K6 role + completed inside 24h → banner + 'Edit (Xh left)' countdown preserved", async () => {
    const q = await renderJD("admin", job("completed", 2));
    expect(q.getByTestId("job-closed-edits-logged-banner")).toBeTruthy();
    expect(q.getByTestId("job-edit-button-label").props.children).toMatch(/^Edit \(\d+\.\dh left\)$/);
  });

  it("K6 role + in-progress → banner hidden", async () => {
    const q = await renderJD("admin", job("active", null));
    expect(q.queryByTestId("job-closed-edits-logged-banner")).toBeNull();
  });

  it("non-K6 role (customer) + completed → banner hidden, no Edit", async () => {
    const q = await renderJD("customer", job("completed", 2));
    expect(q.queryByTestId("job-closed-edits-logged-banner")).toBeNull();
    expect(q.queryByTestId("job-edit-open")).toBeNull();
  });

  it("non-K6 unknown role + completed past 24h → banner hidden, no Edit", async () => {
    const q = await renderJD("viewer", job("completed", 72));
    expect(q.queryByTestId("job-closed-edits-logged-banner")).toBeNull();
    expect(q.queryByTestId("job-edit-open")).toBeNull();
  });

  it("TD-78c · dispatcher on a closed job → edit controls enabled + banner visible", async () => {
    const q = await renderJD("dispatcher", job("completed", 72));
    expect(q.getByTestId("job-closed-edits-logged-banner")).toBeTruthy();
    const edit = q.getByTestId("job-edit-open");
    expect(edit.props.accessibilityState?.disabled ?? edit.props.disabled ?? false).toBeFalsy();
    expect(q.getByTestId("job-edit-button-label").props.children).toBe("Edit");
  });

  it("TD-78c · dispatcher on an in-progress job → banner hidden", async () => {
    const q = await renderJD("dispatcher", job("active", null));
    expect(q.queryByTestId("job-closed-edits-logged-banner")).toBeNull();
  });
});

describe("Checklist screen wiring (same web rule)", () => {
  const SRC = fs.readFileSync(path.join(__dirname, "../app/job/[id]/checklist.tsx"), "utf8");
  it("renders the banner under canEditCompletedJob(role, job), above the hero", () => {
    expect(SRC).toContain("{canEditCompletedJob(role, job) ? <ClosedJobEditsBanner /> : null}");
    expect(SRC.indexOf("<ClosedJobEditsBanner />")).toBeLessThan(SRC.indexOf('testID="checklist-hero"'));
  });
});
