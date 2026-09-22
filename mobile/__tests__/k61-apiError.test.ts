/**
 * K61.a.2 · Feb-2026 — ``ApiError`` structured-throw assertions.
 *
 * Guards ``mobile/src/api.ts`` against a regression to the pre-K61
 * plain-``Error`` throw.  Downstream Close-job / Save-draft handlers
 * depend on ``err.status`` (HTTP status code) and ``err.detail`` (raw
 * parsed backend ``detail`` field) being attached to the thrown
 * error so they can inspect the shape structurally instead of doing
 * fragile substring matching on ``err.message``.
 *
 * The regression this test locks in: pre-K61 the catch block in
 * ``app/job/[id]/checklist.tsx::closeJob`` read
 * ``e.response.data.detail`` (axios-shaped) — dead code on a fetch-
 * based client — and every close-job failure fell through to a
 * generic "Close failed" message with no ``setHighlightBodies``
 * wiring for the chemistry gate.
 *
 * See /app/memory/PHASE_K61_MOBILE_SAVE_CLOSE_ROBUSTNESS.md.
 */

// Mock the storage module BEFORE importing api.ts so ``authHeaders``
// doesn't try to touch SecureStore/AsyncStorage during the test.
jest.mock("@/src/utils/storage", () => ({
  storage: {
    secureGet: jest.fn(async () => ""),
    secureSet: jest.fn(async () => undefined),
    secureRemove: jest.fn(async () => undefined),
  },
}));

// Mock diagnostics so logApi calls are silent.
jest.mock("@/src/utils/diagnostics", () => ({
  logApi: jest.fn(),
}));

import { api, ApiError, ApiNetworkError } from "@/src/api";

describe("K61.a.2 · ApiError class", () => {
  it("attaches status + detail alongside the humanised message", () => {
    // Phase P17.1 · Feb-2026 — canonical rename: mirror the current
    // production 422 shape (``Chlorine`` / ``Alkalinity``, no legacy
    // FC/TA short forms).
    const raw = { detail: "chemistry_core_readings_missing", missing_labels: ["Chlorine", "Alkalinity"] };
    const err = new ApiError("Cannot close job", 422, raw);
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.name).toBe("ApiError");
    expect(err.message).toBe("Cannot close job");
    expect(err.status).toBe(422);
    expect(err.detail).toEqual(raw);
    expect(err.kind).toBe("http");
  });

  it("distinguishes from ApiNetworkError (different ``kind``)", () => {
    const httpErr = new ApiError("boom", 500, "server melted");
    const netErr = new ApiNetworkError("offline");
    expect(httpErr.kind).toBe("http");
    expect(netErr.kind).toBe("network");
    expect(httpErr).not.toBeInstanceOf(ApiNetworkError);
    expect(netErr).not.toBeInstanceOf(ApiError);
  });

  it("tolerates all three FastAPI ``detail`` shapes without coercion", () => {
    // String detail — HTTPException(400, "…")
    const s = new ApiError("Empty file", 400, "Empty file");
    expect(typeof s.detail).toBe("string");
    // Array detail — Pydantic-v2 422 validation
    const arr = new ApiError("body.file: Field required", 422, [
      { type: "missing", loc: ["body", "file"], msg: "Field required" },
    ]);
    expect(Array.isArray(arr.detail)).toBe(true);
    // Object detail — structured business-rule raise
    const obj = new ApiError("Missing", 422, { detail: "chemistry_core_readings_missing", missing_labels: [] });
    expect(typeof obj.detail).toBe("object");
    expect(Array.isArray(obj.detail)).toBe(false);
  });
});

describe("K61.a.2 · request() throws ApiError on HTTP failures", () => {
  const _origFetch = global.fetch;
  afterEach(() => {
    global.fetch = _origFetch;
    jest.restoreAllMocks();
  });

  const _mockFetch = (status: number, body: any) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (global as any).fetch = jest.fn(async () => ({
      ok: status >= 200 && status < 300,
      status,
      text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
    }));
  };

  it("attaches HTTP status on 4xx responses", async () => {
    _mockFetch(400, { detail: "Empty file" });
    await expect(api.post("/service-reports/x/media", {})).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      detail: "Empty file",
    });
  });

  it("attaches RAW array detail on 422 Pydantic validation", async () => {
    const rawDetail = [
      { type: "missing", loc: ["body", "file"], msg: "Field required" },
    ];
    _mockFetch(422, { detail: rawDetail });
    let caught: any;
    try { await api.post("/service-reports/x/media", {}); }
    catch (e) { caught = e; }
    expect(caught).toBeInstanceOf(ApiError);
    expect(caught.status).toBe(422);
    expect(caught.detail).toEqual(rawDetail); // Preserved verbatim.
    // Message is humanised via the pre-K61 flattener.
    expect(caught.message).toContain("Field required");
  });

  it("attaches RAW dict detail on structured 422 business-rule raise (chemistry gate)", async () => {
    const rawDetail = {
      detail: "chemistry_core_readings_missing",
      // Phase P17.1 · Feb-2026 — canonical rename: production 422
      // now emits ``chlorine`` / ``Chlorine`` (was ``free_cl`` /
      // ``Free Cl`` under P17; Phase CHEM1 dropped ``total_cl``
      // from the gate).
      missing_labels: ["Chlorine", "Alkalinity", "pH", "CYA"],
      missing_fields: ["chlorine", "alkalinity", "ph", "cya"],
      message: "Cannot close job — required chemistry readings missing",
    };
    _mockFetch(422, { detail: rawDetail });
    let caught: any;
    try { await api.post(`/jobs/xyz/service-report/submit`, {}); }
    catch (e) { caught = e; }
    expect(caught).toBeInstanceOf(ApiError);
    expect(caught.status).toBe(422);
    expect(caught.detail).toEqual(rawDetail);
    // Structured chemistry-gate detection — the shape Close-job now
    // reads via ``err.detail?.detail === 'chemistry_core_readings_missing'``.
    expect((caught.detail as any).detail).toBe("chemistry_core_readings_missing");
    expect((caught.detail as any).missing_labels).toEqual([
      "Chlorine", "Alkalinity", "pH", "CYA",
    ]);
    // Message is humanised for legacy callers.
    expect(caught.message).toContain("Cannot close job");
    expect(caught.message).toContain("Chlorine");
  });

  it("REGRESSION — never throws a plain ``Error`` on HTTP failures", async () => {
    _mockFetch(500, "internal");
    let caught: any;
    try { await api.get("/anything"); }
    catch (e) { caught = e; }
    // The pre-K61 code threw ``new Error(msg)`` — the K61.a.2 fix must
    // now throw an ``ApiError`` instance so every catch site can rely
    // on ``e.status``.
    expect(caught).toBeInstanceOf(ApiError);
    expect(caught.status).toBe(500);
  });
});
