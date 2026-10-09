/**
 * Feb-2026 · Regression test — outbound URL for the magic-link
 * surface is character-exact.
 *
 * The tester reported a trailing period being appended to the JWT
 * before ``/api/portal/quotes/via-token`` fired. Previous regression
 * test mocked ``api.get`` — its URL assertion checked the wrapper
 * args, not the actual URL going over the wire. This file mocks
 * ``global.fetch`` at the transport boundary so the real URL
 * assembly (``BASE + /api + path``) is validated end-to-end.
 *
 *   1. ``/api/portal/quotes/via-token`` outbound URL matches
 *      ``token=<jwt>`` character-exact — no trailing dot, no extra.
 *   2. ``/api/portal/tenant/branding`` outbound URL (from the
 *      ``useTenantBranding`` hook) matches the same token.
 *   3. Token ending in a period-adjacent character (a digit right
 *      before the query terminator) is still uncorrupted.
 */
// Feb-2026 · Regression fix — vitest hoists all top-level ``import``
// statements above bare statements, so a plain
// ``process.env.X = "…"`` before the imports doesn't run before
// the ``@/api`` module captures ``BASE`` at load time. ``vi.hoisted``
// IS hoisted alongside the imports, so this stubs the env in the
// right pass.
import { vi } from "vitest";
vi.hoisted(() => {
  process.env.REACT_APP_BACKEND_URL = "http://localhost:8001";
});

import React from "react";
import {
  describe, it, expect, beforeEach, afterEach,
} from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";


vi.mock("@/theme", () => ({
  colors: {
    brand: "#0B4A6F", muted: "#6B7280", onSurface: "#111827",
    border: "#E5E7EB", surface: "#FFFFFF",
    // Phase C.web Batch 1 (Bucket B) · Feb-2026 — PublicEstimateLanding
    // reads ``colors.nav.bgDeep`` for its page chassis background.
    // The pre-C.web mock dropped the ``nav`` sub-object, so render
    // crashed with ``Cannot read properties of undefined (reading
    // 'bgDeep')``.  Minimal fix: expose a ``nav`` sub-object with the
    // single key the page touches.
    nav: { bgDeep: "#0A0940", bg: "#1B1F5C", border: "#1E293B" },
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));


const VALID_QUOTE_PAYLOAD = {
  estimate_id: "q-live",
  status: "sent",
  decision: null,
  sent_at: "2026-02-14T00:00:00Z",
  company: { name: "Acme Pools" },
  bill_to: { name: "Cust", customer_number: "C-1" },
  property_address: "1 Reef St",
  header: {
    estimate_number: "EST-201",
    estimate_date: "2026-02-14",
    customer_number: "C-1",
  },
  title: "Backyard Overhaul",
  line_items: [
    { description: "Pavers", quantity: 100, unit_price: 40 },
  ],
  totals: {
    subtotal: 4000, taxes: 400, amount_paid: 0,
    total_estimated_cost: 4400,
    original_subtotal: 4000, original_total: 4400,
    adjusted_subtotal: 4000, adjusted_total: 4400,
    has_declined_lines: false, declined_line_count: 0,
  },
  notes: null,
  as_customer: true,
  customer_view: {
    customer_group_display: true,
    groups: [
      { category_id: "cat-a", group_key: "cat-a",
        label: "Hardscape", description: "",
        subtotal: 4000, active_subtotal: 4000,
        declined: false, declined_at: null, declined_by: null },
    ],
    subtotal: 4000, tax: 400, discount: 0, total: 4400,
    grouped_subtotal: 4000, grouped_active_subtotal: 4000,
    has_declined_groups: false, currency: "USD",
  },
};

const VALID_BRANDING_PAYLOAD = {
  tenant_id: "t-1",
  branding: {
    company_display_name: "Acme Pools",
    brand_primary_hex: "#0B4A6F",
    brand_secondary_hex: "#F97316",
  },
};


let fetchSpy;
beforeEach(() => {
  fetchSpy = vi.fn(async (url, opts) => {
    let body = {};
    if (String(url).includes("/portal/quotes/via-token")) {
      body = VALID_QUOTE_PAYLOAD;
    } else if (String(url).includes("/portal/tenant/branding")) {
      body = VALID_BRANDING_PAYLOAD;
    }
    return {
      ok: true,
      status: 200,
      headers: {
        get: (k) => (k.toLowerCase() === "x-request-id" ? "req-1" : null),
      },
      text: async () => JSON.stringify(body),
    };
  });
  global.fetch = fetchSpy;
  // Ensure the REACT_APP_BACKEND_URL is present for BASE.
  if (!process.env.REACT_APP_BACKEND_URL) {
    process.env.REACT_APP_BACKEND_URL = "http://localhost:8001";
  }
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  fetchSpy = null;
});


// Import AFTER the theme mock is registered.
import PublicEstimateLanding from "@/pages/portal/PublicEstimateLanding";


async function _mountAtToken(token) {
  render(
    <MemoryRouter initialEntries={[`/e/estimate?token=${token}`]}>
      <Routes>
        <Route path="/e/estimate" element={<PublicEstimateLanding />} />
      </Routes>
    </MemoryRouter>,
  );
  // Wait for both fetches to fire (via-token + branding).
  await waitFor(() =>
    expect(fetchSpy).toHaveBeenCalledTimes(2),
  );
}


function _fetchUrlContaining(needle) {
  const call = fetchSpy.mock.calls.find(([u]) =>
    String(u).includes(needle),
  );
  return call ? String(call[0]) : null;
}


describe("Magic-link outbound URL — character-exact token", () => {
  it("/portal/quotes/via-token URL contains the token verbatim",
      async () => {
    const jwt = "eyJhbGciOiJIUzI1NiJ9.abc123.SIG_TAIL";
    await _mountAtToken(jwt);
    const viaTokenUrl = _fetchUrlContaining("/portal/quotes/via-token");
    expect(viaTokenUrl).not.toBeNull();
    // Character-exact match: ends with the JWT + nothing else.
    // encodeURIComponent leaves ``.`` untouched so a simple endsWith
    // captures the tester's bug.
    expect(viaTokenUrl.endsWith(`?token=${jwt}`)).toBe(true);
    // Belt + suspenders: no trailing dot after the token.
    expect(viaTokenUrl.endsWith(".")).toBe(false);
    // And the token in the URL is length-exact.
    const paramValue = new URL(viaTokenUrl).searchParams.get("token");
    expect(paramValue).toBe(jwt);
    expect(paramValue.length).toBe(jwt.length);
  });

  it("/portal/tenant/branding URL contains the token verbatim",
      async () => {
    const jwt = "eyJhbGciOiJIUzI1NiJ9.abc123.SIG_TAIL";
    await _mountAtToken(jwt);
    const brandingUrl = _fetchUrlContaining("/portal/tenant/branding");
    expect(brandingUrl).not.toBeNull();
    expect(brandingUrl.endsWith(`?token=${jwt}`)).toBe(true);
    expect(brandingUrl.endsWith(".")).toBe(false);
    const paramValue = new URL(brandingUrl).searchParams.get("token");
    expect(paramValue).toBe(jwt);
  });

  it("token whose last char is period-adjacent is uncorrupted",
      async () => {
    // Token whose LAST char is a period-adjacent value (a digit right
    // before what would be the query terminator). If any code path
    // was doing string concat like `` `${token}.` ``, this would
    // reveal the trailing dot.
    const jwt = "eyJhbGciOiJIUzI1NiJ9.payload1234.SIG9";
    await _mountAtToken(jwt);
    const viaTokenUrl = _fetchUrlContaining("/portal/quotes/via-token");
    const brandingUrl = _fetchUrlContaining("/portal/tenant/branding");
    for (const u of [viaTokenUrl, brandingUrl]) {
      expect(u).not.toBeNull();
      const val = new URL(u).searchParams.get("token");
      expect(val).toBe(jwt);
      expect(val.endsWith(".")).toBe(false);
    }
  });

  // Feb-2026 · Trailing-period defense — locks the sanitizer in
  // ``PublicEstimateLanding``. If the URL that reaches the client
  // has a trailing period (browser-automation report bug, email
  // plain-text body where a period followed the URL, etc.), the
  // sanitizer strips it before the token flows into either
  // outbound endpoint. Without this defense the tester saw a
  // ``backend-401`` because the corrupted JWT failed signature
  // verification.
  it("strips a trailing period from the incoming URL before firing",
      async () => {
    const jwt = "eyJhbGciOiJIUzI1NiJ9.payload.SIG";
    const corrupted = `${jwt}.`;
    await _mountAtToken(corrupted);
    const viaTokenUrl = _fetchUrlContaining("/portal/quotes/via-token");
    const brandingUrl = _fetchUrlContaining("/portal/tenant/branding");
    // Both outbound URLs must carry the CLEAN token — no trailing
    // period, character-exact match against the intended JWT.
    for (const u of [viaTokenUrl, brandingUrl]) {
      expect(u).not.toBeNull();
      expect(u.endsWith(`?token=${jwt}`)).toBe(true);
      const val = new URL(u).searchParams.get("token");
      expect(val).toBe(jwt);
      expect(val.endsWith(".")).toBe(false);
    }
  });

  // Belt + suspenders — strip any trailing sentence-ending
  // punctuation (comma, semicolon, etc.), not just period. Covers
  // "click <URL>," from a comma-separated list.
  it("strips trailing comma / whitespace too", async () => {
    const jwt = "eyJhbGciOiJIUzI1NiJ9.payload.SIG";
    await _mountAtToken(`${jwt},`);
    const viaTokenUrl = _fetchUrlContaining("/portal/quotes/via-token");
    expect(viaTokenUrl.endsWith(`?token=${jwt}`)).toBe(true);
  });
});
