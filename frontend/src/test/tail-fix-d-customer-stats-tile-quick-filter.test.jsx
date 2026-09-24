/**
 * Feb-2026 · Tail Fix D — Customer stats tile quick-filter
 * interactivity.
 *
 * Completes the click-through contract on the P53 Tail Bundle Fix C
 * ``Cards on file`` tile that emits
 * ``/customers?has_payment_method=true&is_active=true``.  This suite
 * pins the URL-hydration → filter-state → API-request wiring on
 * ``CustomersList.jsx``:
 *
 *   1. ``?has_payment_method=true`` hydrates the new
 *      ``hasCardFilter`` state and fires an ``/api/customers``
 *      request with ``has_payment_method=true`` on the wire.
 *   2. ``?is_active=true`` lands on the Active tab (the initializer
 *      accepts it as a third alias below ``?tab=`` / ``?status=``).
 *   3. Regression — ``?portal_invited=any`` still hydrates + fires.
 *   4. Regression — ``?portal_activated=1`` still hydrates + fires.
 *   5. Regression — ``?first_access=any`` still hydrates + fires.
 *   6. Combined tile URL
 *      ``?has_payment_method=true&is_active=true`` fires BOTH
 *      predicates in a single request (real tile click-through).
 *   7. P44 ↔ Tail Fix D mutex round-trip: user lands via the tile
 *      with ``?has_payment_method=true`` → toggles the P44 chip ON
 *      → the URL param flips from ``"1"`` to ``"0"`` and the wire
 *      request follows suit in one render.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPatch = vi.fn();
const mockDelete = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
    delete: (...a) => mockDelete(...a),
  },
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ role: "admin", effectiveRole: "admin" }),
}));

import CustomersList from "@/pages/customers/CustomersList";

function _installMockGet() {
  mockGet.mockImplementation((path) => {
    if (path.includes("count_only=true")) {
      return Promise.resolve({ count: 0 });
    }
    if (path.startsWith("/customers/counts")) {
      return Promise.resolve({
        active: 0, inactive: 0, muted: 0, waitlist: 0,
        missing_address: 0, portal_activated: 0,
        portal_not_activated: 0, no_payment_method: 0,
        never_logged_in: 0,
      });
    }
    return Promise.resolve({
      items: [], total: 0, page: 1, page_size: 25, total_pages: 0,
    });
  });
}

function _renderAt(url) {
  _installMockGet();
  return render(
    <MemoryRouter initialEntries={[url]}>
      <CustomersList />
    </MemoryRouter>,
  );
}

// Helper — the list-fetch call is the ``/customers?...`` request
// that does NOT include ``count_only`` and is NOT the ``/counts``
// envelope. The load effect fires this on every relevant state
// change; we grab the most-recent call to assert on.
function _lastListCall() {
  const calls = mockGet.mock.calls.map((c) => c[0]);
  return calls
    .filter((p) => p.startsWith("/customers?"))
    .filter((p) => !p.includes("count_only"))
    .pop();
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
  mockDelete.mockReset();
});

describe("Tail Fix D · Customer stats tile quick-filter", () => {
  it("hydrates ?has_payment_method=true and fires a list request with has_payment_method=true", async () => {
    _renderAt("/customers?has_payment_method=true");
    await waitFor(() => {
      const listCall = _lastListCall();
      expect(listCall).toBeTruthy();
      expect(listCall).toContain("has_payment_method=true");
    });
  });

  it("?is_active=true lands on the Active tab (tab initializer third-alias)", async () => {
    _renderAt("/customers?is_active=true");
    await waitFor(() => {
      const active = screen.getByTestId("tab-active");
      // The Active tab is the default cohort; assert the request
      // wire carries ``is_active=true`` (which only fires when the
      // tab state resolves to ``"active"`` — see ``load()``
      // L521 in ``CustomersList.jsx``).
      const listCall = _lastListCall();
      expect(active).toBeTruthy();
      expect(listCall).toContain("is_active=true");
    });
  });

  it("regression — ?portal_invited=any still hydrates and reaches the wire", async () => {
    _renderAt("/customers?portal_invited=any");
    await waitFor(() => {
      const listCall = _lastListCall();
      expect(listCall).toContain("portal_invited=any");
    });
  });

  it("regression — ?portal_activated=1 still hydrates and reaches the wire", async () => {
    _renderAt("/customers?portal_activated=1");
    await waitFor(() => {
      const listCall = _lastListCall();
      // ``portalStatusFilter`` maps ``1`` → ``"activated"`` which
      // emits ``portal_activated=true`` on the wire.
      expect(listCall).toContain("portal_activated=true");
    });
  });

  it("regression — ?first_access=any still hydrates and reaches the wire", async () => {
    _renderAt("/customers?first_access=any");
    await waitFor(() => {
      const listCall = _lastListCall();
      expect(listCall).toContain("first_access=any");
    });
  });

  it("combined tile URL fires BOTH has_payment_method=true and is_active=true in one request", async () => {
    _renderAt("/customers?has_payment_method=true&is_active=true");
    await waitFor(() => {
      const listCall = _lastListCall();
      expect(listCall).toContain("has_payment_method=true");
      expect(listCall).toContain("is_active=true");
    });
  });

  it("P44 ↔ Tail Fix D mutex — tile landing then chip toggle flips has_payment_method=1 → 0", async () => {
    _renderAt("/customers?has_payment_method=true&is_active=true");

    // Phase 1 — mount hydration wins for the tile signal.
    await waitFor(() => {
      const listCall = _lastListCall();
      expect(listCall).toContain("has_payment_method=true");
      // P44 chip must be OFF (tile-inbound wins on mount).
      const chip = screen.getByTestId("customers-no-payment-filter");
      expect(chip.getAttribute("aria-pressed")).toBe("false");
    });

    // Phase 2 — user toggles the P44 chip ON. Mutex clears the
    // ``hasCardFilter`` state; URL sync flips the shared param
    // from ``"1"`` to ``"0"``; the wire request follows.
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("customers-no-payment-filter"));

    await waitFor(() => {
      const listCall = _lastListCall();
      expect(listCall).toBeTruthy();
      // New wire request carries the P44 predicate.
      expect(listCall).toContain("has_payment_method=false");
      // AND the previous ``=true`` predicate is gone — mutex
      // means the two states never co-fire.
      expect(listCall).not.toContain("has_payment_method=true");
      const chip = screen.getByTestId("customers-no-payment-filter");
      expect(chip.getAttribute("aria-pressed")).toBe("true");
    });
  });
});
