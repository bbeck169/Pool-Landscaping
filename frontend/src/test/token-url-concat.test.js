/**
 * TD-66 · Feb-2026 — vitest coverage for ``withAuthToken``.
 *
 * Prod symptom: operator pasted a broken S3 URL from the Work Stream
 * image modal:
 *
 *   https://emergant.s3.amazonaws.com/Photos/...?X-Amz-...
 *     &X-Amz-Signature=1624...?token=eyJ...
 *                                 ^^ 2nd '?' instead of '&'
 *
 * Root cause: naïve concat ``url + "?token=" + token`` fired twice
 * on URLs that already carried an ``?X-Amz-…`` query string (BE
 * 302s the ``/api/public/job-photo/.../thumb`` request through an
 * S3 presigned URL).  The helper this file tests is the fix.
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
  it("appends ?token= to a bare relative path with no query", () => {
    const out = withAuthToken(
      "/api/public/job-photo/jid/pid/thumb",
      "jwt-xyz",
    );
    expect(out).toContain("token=jwt-xyz");
    expect(out).not.toContain("??");
    // Only one '?' total.
    expect((out.match(/\?/g) || []).length).toBe(1);
  });

  it("appends &token= to an absolute URL that ALREADY carries a query string", () => {
    // This is the exact prod shape operator pasted — the 2nd '?'
    // bug replicated verbatim.
    const s3 =
      "https://emergant.s3.amazonaws.com/Photos/xyz" +
      "?X-Amz-Algorithm=AWS4-HMAC-SHA256" +
      "&X-Amz-Signature=1624abc";
    const out = withAuthToken(s3, "eyJjwt");
    expect(out).toContain("X-Amz-Signature=1624abc");
    expect(out).toContain("token=eyJjwt");
    // CRITICAL regression lock: only ONE '?' in the final URL.
    expect((out.match(/\?/g) || []).length).toBe(1);
    // And the ``token`` param lands AFTER an ``&`` separator.
    expect(out).toMatch(/[&?]token=eyJjwt/);
    // Final URL must NOT contain the broken ``Signature=...?token=`` pattern.
    expect(out).not.toMatch(/Signature=[^&]+\?token=/);
  });

  it("is idempotent — a 2nd call REPLACES the existing token, not appends", () => {
    const once = withAuthToken(
      "/api/public/job-photo/jid/pid/thumb",
      "jwt-first",
    );
    const twice = withAuthToken(once, "jwt-second");
    expect(twice).toContain("token=jwt-second");
    expect(twice).not.toContain("jwt-first");
    // STILL exactly ONE '?' and ONE 'token=' occurrence.
    expect((twice.match(/\?/g) || []).length).toBe(1);
    expect((twice.match(/token=/g) || []).length).toBe(1);
  });

  it("preserves a #fragment at the end of the URL", () => {
    const out = withAuthToken(
      "https://example.com/path?a=1#section-2",
      "jwt",
    );
    expect(out).toContain("a=1");
    expect(out).toContain("token=jwt");
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
    expect(out).toContain("token=jwt");
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
    expect(out).not.toMatch(/token=jwt\+with\/slash=and&amp/);
    expect(out).toContain("token=");
    // Decode the token param and ensure we get the original back.
    const u = new URL(out, "http://localhost");
    expect(u.searchParams.get("token")).toBe("jwt+with/slash=and&amp");
  });

  it("does not corrupt an existing token= query param if a non-token value happens to contain the substring", () => {
    // e.g. a URL that has a ``?other=token=stuff`` — the regex must
    // NOT match it. (The fast-path uses URLSearchParams which is
    // name-aware, so this is just a smoke test.)
    const out = withAuthToken(
      "/api/foo?something=token=looks-like-it",
      "real-jwt",
    );
    const u = new URL(out, "http://localhost");
    expect(u.searchParams.get("token")).toBe("real-jwt");
    expect(u.searchParams.get("something")).toBe("token=looks-like-it");
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
      expect(out).toContain("&token=jwt");
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
        "/api/foo?token=old-jwt&a=1",
        "new-jwt",
      );
      expect(out).toContain("token=new-jwt");
      expect(out).not.toContain("old-jwt");
      // Only ONE occurrence of ``token=`` in the final URL.
      expect((out.match(/token=/g) || []).length).toBe(1);
    } finally {
      globalThis.URL = _origURL;
    }
  });
});
