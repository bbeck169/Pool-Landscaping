/**
 * Feb 2026 · P0 iOS close-job 422 fix · api.ts error unwrapper.
 *
 * The mobile api client's ``request`` helper turns non-OK responses
 * into ``throw new Error(...)``. Historically it unwrapped:
 *   - ``detail`` as a string          — the plain-text 422/500 case
 *   - ``detail`` as a list of dicts   — Pydantic body validation errors
 * ...but returned "Request failed (422)" for the third shape used by
 * every structured business-rule raise on the backend:
 *   - ``detail`` as a DICT with ``{message, missing_fields, ...}``
 *
 * The chemistry gate at
 * ``/app/backend/services/chemistry_gate.py::assert_core_readings_present``
 * uses this shape.  When a tech tried to Close a pool job without the
 * five core readings on iOS TestFlight, they saw a generic "Request
 * failed (422)" instead of the actual error.  This suite locks the
 * unwrapper's new behaviour in place.
 */
import { api } from "@/src/api";
import { storage } from "@/src/utils/storage";


// The API client reads REACT_NATIVE_API_URL from expo-constants at
// import time; storage.secureGet is called on every request for the
// token.  Stub both with jest so the tests run hermetically.
jest.mock("@/src/utils/storage", () => ({
  storage: {
    secureGet: jest.fn().mockResolvedValue("mock-token"),
    secureRemove: jest.fn().mockResolvedValue(undefined),
    getItem: jest.fn().mockResolvedValue(null),
    setItem: jest.fn().mockResolvedValue(undefined),
    removeItem: jest.fn().mockResolvedValue(undefined),
  },
  TOKEN_KEY: "mock-token-key",
}));


function _mockJsonResponse(status: number, body: any) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get: (k: string) =>
        k.toLowerCase() === "content-type" ? "application/json" : null,
    },
    text: async () => JSON.stringify(body),
  } as any;
}


describe("api.ts · 422 dict-detail unwrapper (Feb 2026 · P0 fix)", () => {
  const _origFetch = global.fetch;
  afterEach(() => {
    global.fetch = _origFetch;
    jest.clearAllMocks();
  });

  it("chemistry gate 422 renders message + missing labels", async () => {
    global.fetch = jest.fn().mockResolvedValue(
      _mockJsonResponse(422, {
        detail: {
          detail: "chemistry_core_readings_missing",
          message: "Cannot close job — required chemistry readings missing",
          missing_fields: ["free_cl", "cya"],
          missing_labels: ["Free Cl", "CYA"],
        },
      }),
    );
    let err: any = null;
    try {
      await api.post("/jobs/x/service-report/submit", {});
    } catch (e) {
      err = e;
    }
    expect(err).toBeTruthy();
    // Message combines base + labels for a single human-readable line.
    expect(err.message).toMatch(/Cannot close job/i);
    expect(err.message).toMatch(/Free Cl/);
    expect(err.message).toMatch(/CYA/);
    // Never falls back to the generic "Request failed" bucket.
    expect(err.message).not.toMatch(/Request failed \(422\)/);
  });

  it("dict-detail with only 'message' still surfaces cleanly", async () => {
    global.fetch = jest.fn().mockResolvedValue(
      _mockJsonResponse(422, {
        detail: { message: "Something specific went wrong" },
      }),
    );
    let err: any = null;
    try {
      await api.post("/whatever", {});
    } catch (e) {
      err = e;
    }
    expect(err?.message).toBe("Something specific went wrong");
  });

  it("dict-detail with only 'msg' still surfaces cleanly", async () => {
    global.fetch = jest.fn().mockResolvedValue(
      _mockJsonResponse(422, {
        detail: { msg: "Alt shape from a legacy caller" },
      }),
    );
    let err: any = null;
    try {
      await api.post("/whatever", {});
    } catch (e) {
      err = e;
    }
    expect(err?.message).toBe("Alt shape from a legacy caller");
  });

  it("string detail (unchanged path) still works", async () => {
    global.fetch = jest.fn().mockResolvedValue(
      _mockJsonResponse(400, { detail: "plain string error" }),
    );
    let err: any = null;
    try {
      await api.post("/whatever", {});
    } catch (e) {
      err = e;
    }
    expect(err?.message).toBe("plain string error");
  });

  it("list-of-dicts detail (Pydantic path — unchanged)", async () => {
    global.fetch = jest.fn().mockResolvedValue(
      _mockJsonResponse(422, {
        detail: [
          { msg: "field required", loc: ["body", "email"], type: "missing" },
        ],
      }),
    );
    let err: any = null;
    try {
      await api.post("/whatever", {});
    } catch (e) {
      err = e;
    }
    expect(err?.message).toMatch(/field required/);
  });

  it("dict-detail with no known keys falls back to a diagnosable JSON", async () => {
    global.fetch = jest.fn().mockResolvedValue(
      _mockJsonResponse(500, {
        detail: { unknown_key: "opaque", nested: { deeper: 42 } },
      }),
    );
    let err: any = null;
    try {
      await api.post("/whatever", {});
    } catch (e) {
      err = e;
    }
    // Not the generic "Request failed" — carries enough to be useful.
    expect(err?.message).toContain("unknown_key");
    expect(err?.message).not.toMatch(/^Request failed \(500\)$/);
  });
});
