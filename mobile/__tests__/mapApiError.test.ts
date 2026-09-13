/**
 * mapApiError.test.ts — Unit tests for the error classifier.
 *
 * Covers: 403→forbidden, 401→auth, 404→not_found, 500→server,
 * network→offline, 422→client, plain Error→offline.
 */
import { mapApiError, errorKindIcon } from "@/src/utils/mapApiError";
import { ApiError, ApiNetworkError } from "@/src/api";

describe("mapApiError", () => {
  it("classifies 403 as forbidden", () => {
    const err = new ApiError("Forbidden: admin only", 403, "Forbidden: admin only");
    const mapped = mapApiError(err);
    expect(mapped.kind).toBe("forbidden");
    expect(mapped.title).toBe("Not authorized");
    expect(mapped.status).toBe(403);
  });

  it("classifies 401 as auth", () => {
    const err = new ApiError("Token expired", 401, "Token expired");
    const mapped = mapApiError(err);
    expect(mapped.kind).toBe("auth");
    expect(mapped.title).toBe("Session expired");
    expect(mapped.status).toBe(401);
  });

  it("classifies 404 as not_found", () => {
    const err = new ApiError("Quote not found", 404, "Quote not found");
    const mapped = mapApiError(err);
    expect(mapped.kind).toBe("not_found");
    expect(mapped.title).toBe("Not found");
    expect(mapped.status).toBe(404);
  });

  it("classifies 500 as server", () => {
    const err = new ApiError("Internal server error", 500, "Internal server error");
    const mapped = mapApiError(err);
    expect(mapped.kind).toBe("server");
    expect(mapped.title).toBe("Server error");
    expect(mapped.status).toBe(500);
  });

  it("classifies 502 as server", () => {
    const err = new ApiError("Bad gateway", 502, "Bad gateway");
    const mapped = mapApiError(err);
    expect(mapped.kind).toBe("server");
    expect(mapped.status).toBe(502);
  });

  it("classifies 422 as client", () => {
    const err = new ApiError("Property does not belong to customer", 422, "Property does not belong to customer");
    const mapped = mapApiError(err);
    expect(mapped.kind).toBe("client");
    expect(mapped.title).toBe("Something went wrong");
    expect(mapped.message).toContain("Property");
    expect(mapped.status).toBe(422);
  });

  it("classifies ApiNetworkError as offline", () => {
    const err = new ApiNetworkError("Failed to fetch");
    const mapped = mapApiError(err);
    expect(mapped.kind).toBe("offline");
    expect(mapped.title).toBe("You're offline");
  });

  it("classifies plain Error as offline (fallback)", () => {
    const err = new Error("Network request failed");
    const mapped = mapApiError(err);
    expect(mapped.kind).toBe("offline");
    expect(mapped.title).toBe("You're offline");
    expect(mapped.message).toContain("Network request failed");
  });

  it("classifies null/undefined as offline", () => {
    const mapped = mapApiError(null);
    expect(mapped.kind).toBe("offline");
  });
});

describe("errorKindIcon", () => {
  it("returns correct icons for each kind", () => {
    expect(errorKindIcon("auth")).toBe("log-in-outline");
    expect(errorKindIcon("forbidden")).toBe("lock-closed-outline");
    expect(errorKindIcon("not_found")).toBe("help-circle-outline");
    expect(errorKindIcon("server")).toBe("warning-outline");
    expect(errorKindIcon("offline")).toBe("cloud-offline-outline");
    expect(errorKindIcon("client")).toBe("alert-circle-outline");
  });
});
