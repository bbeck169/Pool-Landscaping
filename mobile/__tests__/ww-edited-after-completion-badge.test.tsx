/**
 * WW mobile parity (web cc8858980 / BE 5d105aaa3) — "Edited after
 * completion" badge on job detail + checklist, gated on
 * `job.edited_after_completion === true`. Sits alongside the TD-78b
 * ClosedJobEditsBanner. Checklist is source-level locked (full render
 * stalls in bootstrap — TECH_DEBT TD-78b L409).
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, waitFor, within } from "@testing-library/react-native";

import EditedAfterCompletionBadge from "@/src/components/job/EditedAfterCompletionBadge";
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

const BADGE = "edited-after-completion-badge";
const job = (flag: any) => ({
  id: "j1", title: "Weekly Pool", status: "completed", customer_id: "c1",
  completed_at: new Date(Date.now() - 72 * 3_600_000).toISOString(),
  ...(flag === "__missing__" ? {} : { edited_after_completion: flag }),
});

async function renderJD(role: string, j: any) {
  mockUser = { id: "u1", role };
  mockJob = j;
  const q = render(<JobDetail />);
  await waitFor(() => q.getByTestId("job-detail-scroll"));
  return q;
}

describe("EditedAfterCompletionBadge", () => {
  it("visible → copy + amber palette (snapshot)", () => {
    const q = render(<EditedAfterCompletionBadge visible />);
    expect(q.getByText("Edited after completion")).toBeTruthy();
    const style = Object.assign({}, ...[q.getByTestId(BADGE).props.style].flat());
    expect(style).toMatchObject({ backgroundColor: "#FEF3C7", borderColor: "#FCD34D" });
    expect(q.toJSON()).toMatchSnapshot();
  });
  it("visible=false → renders nothing", () => {
    expect(render(<EditedAfterCompletionBadge visible={false} />).toJSON()).toBeNull();
  });
});

describe("Job detail", () => {
  it("flag true → badge adjacent to StatusChip, alongside TD-78b banner (snapshot)", async () => {
    const q = await renderJD("admin", job(true));
    const row = q.getByTestId("job-status-row");
    expect(within(row).getByTestId("job-status-chip")).toBeTruthy();
    expect(within(row).getByTestId(BADGE)).toBeTruthy();
    expect(q.getByTestId("job-closed-edits-logged-banner")).toBeTruthy();
    const ids = row.findAll((n: any) => typeof n.type === "string" && !!n.props.testID).map((n: any) => n.props.testID);
    expect([...new Set(ids)]).toMatchSnapshot();
  });

  it.each([false, null, undefined, "__missing__", "true", 1])("flag %p → no badge; chip + banner kept", async (flag) => {
    const q = await renderJD("technician", job(flag));
    expect(q.queryByTestId(BADGE)).toBeNull();
    expect(q.getByTestId("job-status-chip")).toBeTruthy();
    expect(q.getByTestId("job-closed-edits-logged-banner")).toBeTruthy();
  });
});

describe("Checklist screen wiring", () => {
  const SRC = fs.readFileSync(path.join(__dirname, "../app/job/[id]/checklist.tsx"), "utf8");
  const BADGE_JSX = "<EditedAfterCompletionBadge visible={job?.edited_after_completion === true} />";
  it("badge gated on strict === true, placed after ClosedJobEditsBanner and before the hero", () => {
    expect(SRC).toContain(BADGE_JSX);
    const banner = SRC.indexOf("{canEditCompletedJob(role, job) ? <ClosedJobEditsBanner /> : null}");
    expect(banner).toBeGreaterThan(-1);
    expect(SRC.indexOf(BADGE_JSX)).toBeGreaterThan(banner);
    expect(SRC.indexOf(BADGE_JSX)).toBeLessThan(SRC.indexOf('testID="checklist-hero"'));
  });
  it("D1(b) — broader K6 unlock unchanged", () => {
    expect(SRC).toContain("const canEditCompleted = !locked ? false : canEditCompletedJob(role, job);");
    expect(SRC).toContain("const effectiveLocked = locked && !canEditCompleted;");
  });
});
