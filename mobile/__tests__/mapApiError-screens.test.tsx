/**
 * mapApiError screen integration tests.
 *
 * Validates that screens using mapApiError display the correct
 * title / icon / message for each error kind instead of a generic
 * "You're offline" message.
 */
import { mapApiError, errorKindIcon } from "@/src/utils/mapApiError";
import { ApiError } from "@/src/api";

/* ------------------------------------------------------------------ */
/*  Mock ApiError constructor (real module may not export it cleanly)  */
/* ------------------------------------------------------------------ */

jest.mock("@/src/api", () => ({
  api: { get: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn(), delete: jest.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    detail?: string;
    constructor(status: number, message?: string, detail?: string) {
      super(message || "Error");
      this.status = status;
      this.detail = detail;
    }
  },
  TOKEN_KEY: "token",
}));

/* ------------------------------------------------------------------ */
/*  Scenario: EbitTile — 403 forbidden                                */
/* ------------------------------------------------------------------ */

describe("EbitTile mapApiError integration", () => {
  it("shows 'Not authorized' for 403 instead of 'EBIT unavailable'", () => {
    const err = new ApiError(403, "Forbidden", "Insufficient role.");
    const mapped = mapApiError(err);
    
    expect(mapped.title).toBe("Not authorized");
    expect(mapped.message).toBe("Insufficient role.");
    expect(errorKindIcon(mapped.kind)).toBe("lock-closed-outline");
    // NOT the old "EBIT unavailable" + "alert-circle-outline"
    expect(mapped.title).not.toBe("EBIT unavailable");
  });

  it("shows 'Server error' for 500 instead of 'EBIT unavailable'", () => {
    const err = new ApiError(500, "Internal Server Error", "DB connection lost.");
    const mapped = mapApiError(err);
    
    expect(mapped.title).toBe("Server error");
    expect(errorKindIcon(mapped.kind)).toBe("warning-outline");
  });
});

/* ------------------------------------------------------------------ */
/*  Scenario: D2D sold leads — network error                          */
/* ------------------------------------------------------------------ */

describe("D2D mapApiError integration", () => {
  it("shows 'You're offline' for network error", () => {
    const err = { kind: "network", message: "Network request failed" };
    const mapped = mapApiError(err);
    
    expect(mapped.kind).toBe("offline");
    expect(errorKindIcon(mapped.kind)).toBe("cloud-offline-outline");
  });

  it("shows 'Server error' for 503 Zillow outage", () => {
    const err = new ApiError(503, "Service Unavailable", "Zillow API is down.");
    const mapped = mapApiError(err);
    
    expect(mapped.kind).toBe("server");
    expect(mapped.title).toBe("Server error");
    expect(mapped.message).toBe("Zillow API is down.");
  });
});

/* ------------------------------------------------------------------ */
/*  Scenario: Checklist bootstrap — 403                               */
/* ------------------------------------------------------------------ */

describe("Checklist mapApiError integration", () => {
  it("shows 'Not authorized' for 403 checklist access", () => {
    const err = new ApiError(403, "Forbidden", "Not your job.");
    const mapped = mapApiError(err);
    
    expect(mapped.kind).toBe("forbidden");
    expect(mapped.title).toBe("Not authorized");
    expect(errorKindIcon(mapped.kind)).toBe("lock-closed-outline");
    // Before: would show "cloud-offline-outline" and "Not cached for offline"
  });

  it("shows 'Not found' for 404 checklist", () => {
    const err = new ApiError(404, "Not Found");
    const mapped = mapApiError(err);
    
    expect(mapped.kind).toBe("not_found");
    expect(mapped.title).toBe("Not found");
    expect(errorKindIcon(mapped.kind)).toBe("help-circle-outline");
  });
});

/* ------------------------------------------------------------------ */
/*  Scenario: Comms templates/sends/automations — various errors      */
/* ------------------------------------------------------------------ */

describe("Comms screens mapApiError integration", () => {
  it("shows 'Session expired' for 401 on template load", () => {
    const err = new ApiError(401, "Unauthorized");
    const mapped = mapApiError(err);
    
    expect(mapped.kind).toBe("auth");
    expect(mapped.title).toBe("Session expired");
    expect(errorKindIcon(mapped.kind)).toBe("log-in-outline");
  });

  it("shows detailed message from API for 422 validation error", () => {
    const err = new ApiError(422, "Validation Error", "Template body cannot be empty.");
    const mapped = mapApiError(err);
    
    expect(mapped.kind).toBe("client");
    expect(mapped.message).toBe("Template body cannot be empty.");
    expect(errorKindIcon(mapped.kind)).toBe("alert-circle-outline");
  });
});

/* ------------------------------------------------------------------ */
/*  Scenario: Job detail — various error states                       */
/* ------------------------------------------------------------------ */

describe("Job detail mapApiError integration", () => {
  it("shows 'Not found' for 404 job", () => {
    const err = new ApiError(404, "Not Found", "Job not in database.");
    const mapped = mapApiError(err);
    
    expect(mapped.kind).toBe("not_found");
    expect(mapped.title).toBe("Not found");
    expect(errorKindIcon(mapped.kind)).toBe("help-circle-outline");
    // Before: would show "warning-outline" + "Couldn't load job. Retry?"
  });

  it("shows 'Server error' for 500 job load", () => {
    const err = new ApiError(500, "ISE", "Mongo timeout");
    const mapped = mapApiError(err);
    
    expect(mapped.kind).toBe("server");
    expect(mapped.title).toBe("Server error");
    expect(errorKindIcon(mapped.kind)).toBe("warning-outline");
  });

  it("falls back to offline for plain timeout error", () => {
    const err = new Error("__LOAD_TIMEOUT__");
    const mapped = mapApiError(err);
    
    // Timeout is a plain Error — mapApiError classifies as offline fallback
    expect(mapped.kind).toBe("offline");
    expect(mapped.message).toBe("__LOAD_TIMEOUT__");
  });
});
