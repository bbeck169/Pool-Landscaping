/**
 * K59.a · Feb-2026 — Upload error stringifier assertions.
 *
 * Guards ``mobile/src/api/serviceReportMedia.ts::stringifyDetail``
 * against regressions.  Covers the four documented shape families
 * FastAPI + Pydantic-v2 emit in ``response.detail``:
 *
 *   1. plain string
 *   2. list[dict]  — Pydantic-v2 auto validation errors ({type, loc, msg, ...})
 *   3. dict        — business-rule raises with {message, missing_labels, ...}
 *   4. primitive / null / undefined  — falls through to String() coercion
 *
 * Regression contract: NO input path may ever produce the literal
 * ``"[object Object]"`` string.
 *
 * See /app/memory/PHASE_K59_a_UPLOAD_ERROR_STRINGIFIER.md.
 */
import { stringifyDetail } from "@/src/api/serviceReportMediaErrors";

describe("K59.a · stringifyDetail — string detail", () => {
  it("passes plain strings through unchanged", () => {
    expect(stringifyDetail("File too large")).toBe("File too large");
  });

  it("clips over-length strings to 400 chars", () => {
    const long = "x".repeat(1000);
    const out = stringifyDetail(long);
    expect(out.length).toBe(400);
  });
});

describe("K59.a · stringifyDetail — array[dict] (Pydantic v2 validation shape)", () => {
  it("flattens loc + msg into a human-readable string", () => {
    const detail = [
      { type: "missing", loc: ["body", "file"], msg: "Field required", input: null },
    ];
    expect(stringifyDetail(detail)).toBe("body.file: Field required");
  });

  it("joins multiple validation errors with ``; ``", () => {
    const detail = [
      { type: "missing", loc: ["body", "file"], msg: "Field required" },
      { type: "value_error", loc: ["body", "kind"], msg: "Value error, must be 'photo' or 'video'" },
    ];
    const out = stringifyDetail(detail);
    expect(out).toContain("body.file: Field required");
    expect(out).toContain("body.kind: Value error");
    expect(out).toContain(";");
  });

  it("falls back to JSON.stringify when a validation item has no msg", () => {
    const detail = [{ type: "opaque", loc: ["body"] }];
    expect(stringifyDetail(detail)).not.toBe("[object Object]");
    expect(stringifyDetail(detail)).toContain("opaque");
  });

  it("REGRESSION — never produces the raw ``[object Object]`` string", () => {
    const detail = [
      { type: "missing", loc: ["body", "file"], msg: "Field required", input: null,
        url: "https://errors.pydantic.dev/2.13/v/missing" },
    ];
    expect(stringifyDetail(detail)).not.toContain("[object Object]");
  });
});

describe("K59.a · stringifyDetail — dict (structured business-rule raise)", () => {
  it("extracts the ``message`` key and appends missing_labels when present", () => {
    const detail = {
      detail: "chemistry_core_readings_missing",
      message: "Cannot close job — required chemistry readings missing",
      missing_labels: ["Free Cl", "Total Cl", "Alkalinity", "pH", "CYA"],
    };
    const out = stringifyDetail(detail);
    expect(out).toContain("Cannot close job");
    expect(out).toContain("Free Cl, Total Cl, Alkalinity, pH, CYA");
  });

  it("prefers ``message`` over ``msg`` over ``error`` over ``detail``", () => {
    const detail = { message: "one", msg: "two", error: "three", detail: "four" };
    expect(stringifyDetail(detail)).toBe("one");
  });

  it("falls back to JSON.stringify when no known key is present", () => {
    const detail = { random_field: 42 };
    const out = stringifyDetail(detail);
    expect(out).not.toBe("[object Object]");
    expect(out).toContain("random_field");
  });
});

describe("K59.a · stringifyDetail — primitive / null / undefined", () => {
  it("returns the empty string for null / undefined", () => {
    expect(stringifyDetail(null)).toBe("");
    expect(stringifyDetail(undefined)).toBe("");
  });

  it("coerces numbers + booleans to their String() form", () => {
    expect(stringifyDetail(42)).toBe("42");
    expect(stringifyDetail(true)).toBe("true");
  });
});
