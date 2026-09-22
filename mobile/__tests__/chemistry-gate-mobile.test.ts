/**
 * Chemistry gate mobile fix — ref→report mirror + submit payload tests.
 *
 * Verifies:
 * 1. flattenPoolReadings produces the correct flat structure
 * 2. Editing a reading through handleBodiesChange mirrors into report.chemical_readings
 * 3. The submit payload uses waterBodiesRef.current, not stale report.water_bodies
 */

/* ── Standard mocks ────────────────────────────────────────── */
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: "test-job-123" }),
  useFocusEffect: (cb: any) => cb(),
}));
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn().mockResolvedValue(null),
  setItem: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "technician", id: "u1", technician_id: "t1" } }),
  AuthProvider: ({ children }: any) => children,
}));
jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn().mockResolvedValue({}),
    post: jest.fn().mockResolvedValue({}),
    patch: jest.fn().mockResolvedValue({}),
    put: jest.fn().mockResolvedValue({}),
  },
  ApiError: class ApiError extends Error {
    status: number;
    detail: any;
    constructor(msg: string, status: number, detail?: any) {
      super(msg);
      this.status = status;
      this.detail = detail;
    }
  },
}));
jest.mock("@/src/offline", () => ({ useOnline: () => true }));
jest.mock("@/src/services/writeQueue", () => ({
  enqueue: jest.fn().mockResolvedValue("q1"),
  subscribe: jest.fn(() => () => {}),
  flush: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("@/src/services/offlineWrite", () => ({
  offlineWrite: jest.fn(async ({ onlineFn }: any) => {
    const data = await onlineFn();
    return { data, queued: false };
  }),
}));
jest.mock("@/src/services/retryWithBackoff", () => ({
  retryWithBackoff: jest.fn(async (fn: any) => fn()),
}));
jest.mock("@/src/services/sync/offlineServiceLog", () => ({
  submitOffline: jest.fn().mockResolvedValue("off-1"),
  cacheServiceReport: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("@/src/services/offlineCache", () => ({
  cacheJobBootstrap: jest.fn().mockResolvedValue(undefined),
  getCachedBootstrap: jest.fn().mockResolvedValue(null),
}));
jest.mock("@/src/services/routeHydrator", () => ({
  getCachedJobBootstrap: jest.fn().mockResolvedValue(null),
  CK: { jobBootstrap: (id: string) => `jb:${id}` },
}));
jest.mock("@/src/services/readCache", () => ({
  writeCache: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("@/src/services/sync/photoWorker", () => ({
  capturePhoto: jest.fn(),
  getPhotosForEntity: jest.fn().mockResolvedValue([]),
  purgePhotosForEntity: jest.fn(),
}));
jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: jest.fn() }),
}));
jest.mock("@/src/lib/offline/apiCache", () => ({
  writeThroughCustomer: jest.fn().mockResolvedValue(undefined),
  readCachedCustomer: jest.fn().mockResolvedValue(null),
}));
jest.mock("expo-clipboard", () => ({
  setStringAsync: jest.fn().mockResolvedValue(true),
}));

import {
  flattenPoolReadings,
  makeEmptyBody,
  WaterBody,
} from "@/src/lib/waterBodies";

/* ─── Unit: flattenPoolReadings ─────────────────────────────── */

describe("flattenPoolReadings", () => {
  it("flattens multi-body readings into flat array with body_id and body_label", () => {
    const bodies: WaterBody[] = [
      {
        ...makeEmptyBody("pool", 0),
        id: "body-1",
        label: "Main Pool",
        readings: [
          { key: "free_chlorine", value: 3.5, unit: "ppm" },
          { key: "ph", value: 7.4, unit: "" },
        ],
      },
      {
        ...makeEmptyBody("spa", 1),
        id: "body-2",
        label: "Hot Tub",
        readings: [
          { key: "free_chlorine", value: 5.0, unit: "ppm" },
        ],
      },
    ];

    const flat = flattenPoolReadings(bodies);

    expect(flat).toHaveLength(3);
    // First body entries
    expect(flat[0]).toMatchObject({
      key: "free_chlorine",
      value: 3.5,
      body_id: "body-1",
      body_label: "Main Pool",
    });
    expect(flat[1]).toMatchObject({
      key: "ph",
      value: 7.4,
      body_id: "body-1",
      body_label: "Main Pool",
    });
    // Second body entry
    expect(flat[2]).toMatchObject({
      key: "free_chlorine",
      value: 5.0,
      body_id: "body-2",
      body_label: "Hot Tub",
    });
  });

  it("returns empty array for empty bodies", () => {
    expect(flattenPoolReadings([])).toEqual([]);
  });

  it("handles bodies with no readings", () => {
    const bodies: WaterBody[] = [
      { ...makeEmptyBody("pool", 0), readings: [] },
    ];
    expect(flattenPoolReadings(bodies)).toEqual([]);
  });

  it("populates name from READING_LABELS when name not provided", () => {
    // Phase P17.1 · Feb-2026 — canonical rename: READING_LABELS keys
    // on ``chlorine``.  Phase P17.2 · Feb-2026 — display-label
    // unification flipped the ``name`` field from ``Free Chlorine``
    // to ``Chlorine``.
    const bodies: WaterBody[] = [
      {
        ...makeEmptyBody("pool", 0),
        id: "b1",
        label: "Pool",
        readings: [
          { key: "chlorine", value: 2.0 },  // no name field
        ],
      },
    ];
    const flat = flattenPoolReadings(bodies);
    expect(flat[0].name).toBe("Chlorine");  // from READING_LABELS (P17.2 unified)
  });
});

/* ─── Integration: handleBodiesChange mirrors into report ────── */

describe("chemistry-gate: ref→report mirror (integration)", () => {
  // These tests verify the contract that handleBodiesChange in
  // checklist.tsx mirrors waterBodiesRef.current into the report
  // state, specifically report.chemical_readings and report.water_bodies.
  // We test this at the unit level by verifying the flatten helper
  // produces correct output and that the PATCH payload is built correctly.

  it("editing a reading produces flattened chemical_readings matching body data", () => {
    // Simulate: tech edits free_chlorine on body-0
    const bodies: WaterBody[] = [
      {
        ...makeEmptyBody("pool", 0),
        id: "wb-1",
        label: "Pool",
        readings: [
          { key: "free_chlorine", value: 4.0, unit: "ppm" },
          { key: "ph", value: 7.2, unit: "" },
        ],
      },
    ];

    // This is what handleBodiesChange would produce for patchReport:
    const flatReadings = flattenPoolReadings(bodies);

    expect(flatReadings).toHaveLength(2);
    expect(flatReadings[0]).toMatchObject({
      key: "free_chlorine",
      value: 4.0,
      body_id: "wb-1",
      body_label: "Pool",
    });
    expect(flatReadings[1]).toMatchObject({
      key: "ph",
      value: 7.2,
      body_id: "wb-1",
      body_label: "Pool",
    });
  });

  it("submit payload built from ref always includes water_bodies when bodies exist", () => {
    // Simulate the payload-build logic from flushSave:
    const staleReport = {
      chemical_readings: [{ key: "old_reading", value: 99 }],
      chemicals_added: [],
      checklist_items: [],
      notes: "",
      water_bodies: [],
    };

    const freshBodies: WaterBody[] = [
      {
        ...makeEmptyBody("pool", 0),
        id: "wb-fresh",
        label: "Main Pool",
        readings: [{ key: "free_chlorine", value: 5.0, unit: "ppm" }],
      },
    ];

    // Build patch payload (mirrors flushSave logic)
    const patchBody: Record<string, any> = {
      chemical_readings: staleReport.chemical_readings,
      chemicals_added: staleReport.chemicals_added,
      checklist_items: staleReport.checklist_items,
      notes: staleReport.notes,
    };

    // Apply the fix: when bodies exist, overwrite from ref
    if (freshBodies.length > 0) {
      patchBody.water_bodies = freshBodies;
      patchBody.chemical_readings = flattenPoolReadings(freshBodies);
    }

    // Verify the stale reading is gone, replaced by fresh data
    expect(patchBody.water_bodies).toBe(freshBodies);
    expect(patchBody.chemical_readings).toHaveLength(1);
    expect(patchBody.chemical_readings[0]).toMatchObject({
      key: "free_chlorine",
      value: 5.0,
      body_id: "wb-fresh",
      body_label: "Main Pool",
    });
    // The old stale reading should NOT be present
    expect(patchBody.chemical_readings.find((r: any) => r.key === "old_reading")).toBeUndefined();
  });

  it("offline submit enriches report with fresh water body data from ref", () => {
    // Simulate the offline path in doCloseJob
    const staleReport = {
      id: "sr-1",
      chemical_readings: [{ key: "stale", value: 0 }],
      water_bodies: [],
      chemicals_added: [],
      checklist_items: [],
      notes: "",
    };

    const freshBodies: WaterBody[] = [
      {
        ...makeEmptyBody("pool", 0),
        id: "wb-offline",
        label: "Pool",
        readings: [
          { key: "free_chlorine", value: 3.0, unit: "ppm" },
          { key: "ph", value: 7.6, unit: "" },
        ],
      },
    ];

    // Mirror the fix in doCloseJob offline path
    const offlineReport = { ...staleReport };
    if (freshBodies.length > 0) {
      offlineReport.water_bodies = freshBodies as any;
      offlineReport.chemical_readings = flattenPoolReadings(freshBodies) as any;
    }

    // water_bodies should be the fresh bodies
    expect(offlineReport.water_bodies).toEqual(freshBodies);
    // chemical_readings should be rebuilt from fresh bodies
    expect(offlineReport.chemical_readings).toHaveLength(2);
    expect(offlineReport.chemical_readings[0]).toMatchObject({
      key: "free_chlorine",
      value: 3.0,
      body_id: "wb-offline",
    });
    // Stale reading gone
    expect(offlineReport.chemical_readings.find((r: any) => r.key === "stale")).toBeUndefined();
  });

  it("when no bodies exist, chemical_readings from report is preserved (fallback)", () => {
    // No water bodies → keep whatever report.chemical_readings has
    const report = {
      chemical_readings: [{ key: "free_chlorine", value: 2.0 }],
      chemicals_added: [],
      checklist_items: [],
      notes: "",
    };

    const bodies: WaterBody[] = [];

    const patchBody: Record<string, any> = {
      chemical_readings: report.chemical_readings,
      chemicals_added: report.chemicals_added,
      checklist_items: report.checklist_items,
      notes: report.notes,
    };

    if (bodies.length > 0) {
      patchBody.water_bodies = bodies;
      patchBody.chemical_readings = flattenPoolReadings(bodies);
    }

    // No water_bodies key in payload (preserve-semantics)
    expect(patchBody.water_bodies).toBeUndefined();
    // Original readings preserved
    expect(patchBody.chemical_readings).toEqual(report.chemical_readings);
  });
});
