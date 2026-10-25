/**
 * TD-mobile-sync-tech-not-linked · orphan-tech 409 gets an actionable amber
 * message instead of the generic red "Sync failed — retry".
 * BE contract: HTTPException(409, detail={"error": "technician_not_linked", ...})
 * → ApiError.detail = inner object. Matched by error code, not endpoint.
 */
import React from "react";
import { render } from "@testing-library/react-native";

const mockGet = jest.fn();
let mockOnline = true;
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockGet(...a) } }));
jest.mock("@/src/services/readCache", () => ({ writeCache: jest.fn().mockResolvedValue(undefined), readCache: jest.fn().mockResolvedValue(null) }));
jest.mock("@/src/services/sync/netBus", () => ({ isOnlineNow: () => true }));
jest.mock("@/src/services/photoUrlCache", () => ({ stripBase64FromReport: (r: any) => r }));
jest.mock("@/src/lib/offline/netStatus", () => ({ useOnline: () => mockOnline, getSecondsSinceLastSuccess: () => 0 }));
jest.mock("@expo/vector-icons", () => {
  const { Text } = require("react-native");
  return { Ionicons: (p: any) => <Text testID={`icon-${p.name}`} /> };
});

import { hydrateToday } from "@/src/services/routeHydrator";
import OfflineBadge from "@/src/components/OfflineBadge";
import { isTechNotLinked, TECH_NOT_LINKED_COPY } from "@/src/lib/syncErrors";

class FakeApiError extends Error {
  constructor(msg: string, public status: number, public detail: unknown) { super(msg); }
}
const NOT_LINKED = new FakeApiError("User X has role=technician but is not linked…", 409, {
  error: "technician_not_linked", detail: "User X has role=technician but is not linked to a technician record. Contact your admin.",
  tenant_id: "t1", user_id: "u1",
});
const badge = (syncStatus: string) =>
  render(<OfflineBadge cacheStats={{ cached: 0, total: 0, lastSyncedAt: null, syncStatus } as any} />);

beforeEach(() => { mockGet.mockReset(); mockOnline = true; });

it("S1 · error-code matcher: inner detail.error only (FastAPI unwrap); other 409s / strings / nulls don't match", () => {
  expect(isTechNotLinked(NOT_LINKED)).toBe(true);
  expect(isTechNotLinked(new FakeApiError("conflict", 409, { error: "something_else" }))).toBe(false);
  expect(isTechNotLinked(new FakeApiError("conflict", 409, "technician_not_linked"))).toBe(false);
  expect(isTechNotLinked(null)).toBe(false);
  expect(isTechNotLinked(new Error("Network request failed"))).toBe(false);
});

it("S2 · hydration: 409 technician_not_linked → syncStatus tech_not_linked + actionable copy (not 'failed')", async () => {
  mockGet.mockRejectedValue(NOT_LINKED);
  const meta = await hydrateToday("u1");
  expect(meta.syncStatus).toBe("tech_not_linked");
  expect(meta.lastError).toBe(TECH_NOT_LINKED_COPY);
  expect(meta.inProgress).toBe(false);
});

it("S3 · hydration: network / 5xx failures keep the existing 'failed' status + message", async () => {
  mockGet.mockRejectedValueOnce(new Error("Network request failed"));
  expect((await hydrateToday("u1")).syncStatus).toBe("failed");
  mockGet.mockRejectedValueOnce(new FakeApiError("Server error", 503, "upstream down"));
  const meta = await hydrateToday("u1");
  expect(meta.syncStatus).toBe("failed");
  expect(meta.lastError).toBe("Could not reach the server.");
});

it("S4 · a later successful sync clears the not-linked state (no sticky error)", async () => {
  mockGet.mockRejectedValueOnce(NOT_LINKED);
  expect((await hydrateToday("u1")).syncStatus).toBe("tech_not_linked");
  mockGet.mockResolvedValueOnce({ jobs: [], reports: [] });
  expect((await hydrateToday("u1")).syncStatus).not.toBe("tech_not_linked");
});

it("S5 · badge: tech_not_linked → amber + info icon + admin copy, NOT the red 'Sync failed — retry'", () => {
  const q = badge("tech_not_linked");
  expect(q.getByTestId("offline-badge-label").props.children).toBe(
    "Your account isn't linked to a technician profile. Contact your admin to resolve.");
  expect(q.queryByText(/Sync failed/)).toBeNull();
  const flat = Object.assign({}, ...[].concat(q.getByTestId("offline-badge").props.style as any));
  expect(flat.backgroundColor).toBe("#FEF3C7");
  expect(q.getByTestId("icon-information-circle")).toBeTruthy();
  expect(q.queryByTestId("icon-alert-circle")).toBeNull();
});

it("S6 · badge: same admin copy when offline (account state, not connectivity)", () => {
  mockOnline = false;
  expect(badge("tech_not_linked").getByTestId("offline-badge-label").props.children).toBe(TECH_NOT_LINKED_COPY);
});

it("S7 · regression: real failures still show the red 'Sync failed — retry' pill", () => {
  const q = badge("failed");
  expect(q.getByTestId("offline-badge-label").props.children).toBe("Sync failed — retry");
  const flat = Object.assign({}, ...[].concat(q.getByTestId("offline-badge").props.style as any));
  expect(flat.backgroundColor).toBe("#FEE2E2");
});
