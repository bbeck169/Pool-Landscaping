/**
 * TD-66 · Feb-2026 — vitest coverage for ``withAuthToken``.
 * TD-76b · Feb-2026 — query-param key renamed from ``token`` to
 * ``auth`` to match the TD-67 handler contract
 * (``stream_customer_job_photo`` + ``_resolve_bearer_or_query_auth``
 * both read ``?auth=<token>``). All assertions below now expect
 * ``auth=`` in the output URL. The underlying double-``?`` /
 * idempotency / fragment-safety behavior is unchanged.
 *
 * Prod symptom that motivated TD-66: operator pasted a broken S3
 * URL from the Work Stream image modal where a naïve string concat
 * produced a URL with TWO question marks and S3 403'd the
 * signature verification. The helper this file tests is the fix.
 */
import { describe, it, expect, vi } from "vitest";
import { withAuthToken } from "@/lib/urlToken";


describe("withAuthToken · basic contract", () => {
  it("no-ops when the token is falsy", () => {
    expect(withAuthToken("/api/foo", "")).toBe("/api/foo");
    expect(withAuthToken("/api/foo", null)).toBe("/api/foo");
    expect(withAuthToken("/api/foo", undefined)).toBe("/api/foo");
  });

  it("no-ops when the url is falsy", () => {
    expect(withAuthToken("", "jwt")).toBe("");
    expect(withAuthToken(null, "jwt")).toBe(null);
    expect(withAuthToken(undefined, "jwt")).toBe(undefined);
  });
});


describe("withAuthToken · query-string separator (TD-66 bug fix)", () => {
  it("appends ?auth= to a bare relative path with no query", () => {
    const out = withAuthToken(
      "/api/public/job-photo/jid/pid/thumb",
      "jwt-xyz",
    );
    expect(out).toContain("auth=jwt-xyz");
    expect(out).not.toContain("??");
    // Only one '?' total.
    expect((out.match(/\?/g) || []).length).toBe(1);
  });

  it("appends &auth= to an absolute URL that ALREADY carries a query string", () => {
    // Operator's prod shape — the 2nd '?' bug replicated verbatim.
    const s3 =
      "https://emergant.s3.amazonaws.com/Photos/xyz" +
      "?X-Amz-Algorithm=AWS4-HMAC-SHA256" +
      "&X-Amz-Signature=1624abc";
    const out = withAuthToken(s3, "eyJjwt");
    expect(out).toContain("X-Amz-Signature=1624abc");
    expect(out).toContain("auth=eyJjwt");
    // CRITICAL regression lock: only ONE '?' in the final URL.
    expect((out.match(/\?/g) || []).length).toBe(1);
    // And the ``auth`` param lands AFTER an ``&`` separator.
    expect(out).toMatch(/[&?]auth=eyJjwt/);
    // Final URL must NOT contain the broken ``Signature=...?auth=`` pattern.
    expect(out).not.toMatch(/Signature=[^&]+\?auth=/);
  });

  it("is idempotent — a 2nd call REPLACES the existing auth, not appends", () => {
    const once = withAuthToken(
      "/api/public/job-photo/jid/pid/thumb",
      "jwt-first",
    );
    const twice = withAuthToken(once, "jwt-second");
    expect(twice).toContain("auth=jwt-second");
    expect(twice).not.toContain("jwt-first");
    // STILL exactly ONE '?' and ONE 'auth=' occurrence.
    expect((twice.match(/\?/g) || []).length).toBe(1);
    expect((twice.match(/auth=/g) || []).length).toBe(1);
  });

  it("preserves a #fragment at the end of the URL", () => {
    const out = withAuthToken(
      "https://example.com/path?a=1#section-2",
      "jwt",
    );
    expect(out).toContain("a=1");
    expect(out).toContain("auth=jwt");
    // Fragment stays at the end, not in the middle.
    expect(out.endsWith("#section-2")).toBe(true);
    // Not accidentally query-encoded as %23.
    expect(out).not.toContain("%23");
  });

  it("preserves a #fragment on a relative URL with no query", () => {
    const out = withAuthToken(
      "/api/foo#section-2",
      "jwt",
    );
    expect(out).toContain("auth=jwt");
    expect(out.endsWith("#section-2")).toBe(true);
  });
});


describe("withAuthToken · encoding safety", () => {
  it("URL-encodes special chars in the token value", () => {
    const out = withAuthToken(
      "/api/public/job-photo/jid/pid/thumb",
      "jwt+with/slash=and&amp",
    );
    // Must NOT leak raw ``&`` or ``=`` into the query string value.
    expect(out).not.toMatch(/auth=jwt\+with\/slash=and&amp/);
    expect(out).toContain("auth=");
    // Decode the auth param and ensure we get the original back.
    const u = new URL(out, "http://localhost");
    expect(u.searchParams.get("auth")).toBe("jwt+with/slash=and&amp");
  });

  it("does not corrupt an existing auth= query param if a non-auth value happens to contain the substring", () => {
    // e.g. a URL that has a ``?other=auth=stuff`` — the regex must
    // NOT match it. (The fast-path uses URLSearchParams which is
    // name-aware, so this is just a smoke test.)
    const out = withAuthToken(
      "/api/foo?something=auth=looks-like-it",
      "real-jwt",
    );
    const u = new URL(out, "http://localhost");
    expect(u.searchParams.get("auth")).toBe("real-jwt");
    expect(u.searchParams.get("something")).toBe("auth=looks-like-it");
  });
});


describe("withAuthToken · fallback path (URL constructor throws)", () => {
  it("falls back to separator-aware splice when URL constructor is unavailable", () => {
    // Simulate a non-browser env by stubbing globalThis.URL to throw.
    const _origURL = globalThis.URL;
    // @ts-ignore
    globalThis.URL = class {
      constructor() {
        throw new Error("simulated no-URL env");
      }
    };
    try {
      const out = withAuthToken(
        "https://emergant.s3.amazonaws.com/Photos/xyz?X-Amz-Signature=abc",
        "jwt",
      );
      // Fallback must still produce a valid single-'?' URL with '&' sep.
      expect(out).toContain("X-Amz-Signature=abc");
      expect(out).toContain("&auth=jwt");
      expect((out.match(/\?/g) || []).length).toBe(1);
    } finally {
      globalThis.URL = _origURL;
    }
  });

  it("fallback path handles the idempotent re-stamp", () => {
    const _origURL = globalThis.URL;
    // @ts-ignore
    globalThis.URL = class {
      constructor() {
        throw new Error("simulated no-URL env");
      }
    };
    try {
      const out = withAuthToken(
        "/api/foo?auth=old-jwt&a=1",
        "new-jwt",
      );
      expect(out).toContain("auth=new-jwt");
      expect(out).not.toContain("old-jwt");
      // Only ONE occurrence of ``auth=`` in the final URL.
      expect((out.match(/auth=/g) || []).length).toBe(1);
    } finally {
      globalThis.URL = _origURL;
    }
  });
});


// ─────────────────────────────────────────────────────────────────
// TD-76b · scheme-rename regression locks.
// ─────────────────────────────────────────────────────────────────
describe("withAuthToken · TD-76b scheme rename (?token → ?auth)", () => {
  it("stamps `auth=`, NOT `token=`, on relative URLs", () => {
    const out = withAuthToken("/api/customers/me/jobs/j1/photos/p1", "jwt-x");
    expect(out).toContain("auth=jwt-x");
    // Guard against pre-TD-76b scheme reappearance.
    expect(out).not.toMatch(/[?&]token=/);
  });

  it("stamps `auth=`, NOT `token=`, on absolute URLs", () => {
    const out = withAuthToken(
      "https://cdn.example/img.jpg?v=2",
      "jwt-x",
    );
    expect(out).toContain("auth=jwt-x");
    expect(out).not.toMatch(/[?&]token=jwt-x/);
  });

  it("a URL that pre-existing carried `?token=X` is NOT touched by the TD-76b helper", () => {
    // The helper only cares about its own `auth` param — any
    // user-provided `token` param on the input URL is preserved.
    const out = withAuthToken(
      "/api/foo?token=user-provided",
      "jwt-x",
    );
    const u = new URL(out, "http://localhost");
    expect(u.searchParams.get("token")).toBe("user-provided");
    expect(u.searchParams.get("auth")).toBe("jwt-x");
  });
});
