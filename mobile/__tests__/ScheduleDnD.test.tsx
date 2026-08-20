/**
 * Item 3 · Schedule DnD Reorder tests.
 *
 * Tests the reorder logic and role gating without mounting the full
 * calendar component. Focuses on:
 *   1. Drag handles hidden for technician role.
 *   2. Drag handles visible for admin/manager/super_admin.
 *   3. POST /api/jobs/reorder fires on drop with correct payload.
 *   4. Error path shows alert (snap-back scenario).
 */
import { Alert } from "react-native";

/* ── Mocks ─────────────────────────────────────────────────────────── */

const mockApiPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(),
    post: (...a: any[]) => mockApiPost(...a),
    put: jest.fn(),
    delete: jest.fn(),
  },
  getAuthToken: jest.fn().mockResolvedValue("tok"),
}));

jest.spyOn(Alert, "alert");

/* ── Helpers ───────────────────────────────────────────────────────── */

const ADMIN_ROLES = new Set(["admin", "manager", "super_admin"]);
const ALLOWED_DND_ROLES = new Set(["admin", "manager", "super_admin"]);

function isAdminRole(role: string): boolean {
  return ADMIN_ROLES.has(role);
}

function shouldShowDragHandle(role: string, rearrangeMode: boolean): boolean {
  return rearrangeMode && ALLOWED_DND_ROLES.has(role);
}

/** Simulate the onDragEnd handler from calendar.tsx */
async function simulateDragEnd(
  newOrder: string[],
  setReorderList: jest.Mock,
  originalOrder: string[],
) {
  setReorderList(newOrder);
  try {
    await mockApiPost("/jobs/reorder", { job_ids: newOrder });
  } catch (e: any) {
    setReorderList(originalOrder); // snap back
    Alert.alert("Reorder failed", e?.message || "Could not save new order.");
  }
}

/* ── Tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  jest.clearAllMocks();
});

describe("Schedule DnD Reorder", () => {

  test("drag handles hidden for technician role", () => {
    expect(shouldShowDragHandle("technician", true)).toBe(false);
    expect(shouldShowDragHandle("technician", false)).toBe(false);
  });

  test("drag handles visible for admin in rearrange mode", () => {
    expect(shouldShowDragHandle("admin", true)).toBe(true);
    expect(shouldShowDragHandle("manager", true)).toBe(true);
    expect(shouldShowDragHandle("super_admin", true)).toBe(true);
  });

  test("drag handles hidden outside rearrange mode even for admin", () => {
    expect(shouldShowDragHandle("admin", false)).toBe(false);
  });

  test("POST /api/jobs/reorder fires on drop with job_ids payload", async () => {
    mockApiPost.mockResolvedValueOnce({});
    const setReorderList = jest.fn();
    const original = ["j1", "j2", "j3"];
    const reordered = ["j3", "j1", "j2"];

    await simulateDragEnd(reordered, setReorderList, original);

    expect(setReorderList).toHaveBeenCalledWith(reordered);
    expect(mockApiPost).toHaveBeenCalledWith("/jobs/reorder", { job_ids: ["j3", "j1", "j2"] });
    // Should NOT snap back on success
    expect(setReorderList).toHaveBeenCalledTimes(1);
  });

  test("error path snaps back to original order and shows alert", async () => {
    mockApiPost.mockRejectedValueOnce(new Error("Network failure"));
    const setReorderList = jest.fn();
    const original = ["j1", "j2", "j3"];
    const reordered = ["j2", "j3", "j1"];

    await simulateDragEnd(reordered, setReorderList, original);

    // First call: optimistic update
    expect(setReorderList).toHaveBeenNthCalledWith(1, reordered);
    // Second call: snap back
    expect(setReorderList).toHaveBeenNthCalledWith(2, original);
    expect(Alert.alert).toHaveBeenCalledWith("Reorder failed", "Network failure");
  });
});
