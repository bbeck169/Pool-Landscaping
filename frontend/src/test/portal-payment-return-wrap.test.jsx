/**
 * PORTAL-PAYMENT-RETURN-WRAP · Feb-2026 — regression for the Lumino
 * hosted-checkout return route placement.
 *
 * Companion to fix commit b014bceb9. Pins the two invariants that
 * prevent the "silent redirect to /portal/login" regression:
 *
 *   1. Source-grep invariant — the Route declaration must sit
 *      BEFORE the ``<Route path="/" element={<AppLayout />}>``
 *      wrapper opener in ``src/App.js``. Any future edit that
 *      nests this Route back inside the protected shell will fail
 *      this test.
 *
 *   2. Render invariant — ``PortalPaymentReturn`` mounts cleanly
 *      with the ``?session_id=...`` query parameter and without
 *      an authenticated user context (no AppLayout wrapper, no
 *      token stub, no Query/Router providers beyond MemoryRouter).
 *      Proves the page is self-contained and doesn't depend on
 *      portal-shell context that only exists inside AppLayout.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");


describe("PORTAL-PAYMENT-RETURN-WRAP · route placement invariant", () => {
  it("Route is declared OUTSIDE the AppLayout wrapper in App.js", () => {
    const src = read("src/App.js");

    // Find the AppLayout wrapper opener line.
    const appLayoutMarker =
      '<Route path="/" element={<AppLayout />}>';
    const appLayoutIdx = src.indexOf(appLayoutMarker);
    expect(appLayoutIdx).toBeGreaterThan(-1);

    // Find every Route whose path ends with "payment-method/return"
    // regardless of leading-slash form. Each one must sit BEFORE
    // the AppLayout wrapper opener.
    const routeRe =
      /<Route\s+path="\/?portal\/payment-method\/return"[^/]*\/>/g;
    let matched = 0;
    for (const m of src.matchAll(routeRe)) {
      matched += 1;
      expect(m.index).toBeLessThan(appLayoutIdx);
    }

    // Exactly one declaration — no duplicate / stale route.
    expect(matched).toBe(1);
  });

  it("Route uses the absolute path form '/portal/payment-method/return'", () => {
    const src = read("src/App.js");
    // Absolute-path form (matches sibling return pages).
    expect(src).toMatch(
      /<Route\s+path="\/portal\/payment-method\/return"\s+element=/);
    // Legacy nested-relative form must NOT be present.
    expect(src).not.toMatch(
      /<Route\s+path="portal\/payment-method\/return"\s+element=/);
  });
});


describe("PORTAL-PAYMENT-RETURN-WRAP · unauthenticated render", () => {
  beforeEach(() => {
    // Reset window.location.search so the component reads the
    // intended ?session_id for the test.
    window.history.replaceState({}, "", "/portal/payment-method/return?session_id=cs_test_xyz");
    vi.resetModules();
  });

  it("renders without an authenticated user context (loading → outcome)", async () => {
    // Stub the api module so no network call escapes the test
    // process. The real module lives at ``src/api.js``; the import
    // path matches what ``PortalPaymentReturn`` uses (``@/api``).
    vi.doMock("@/api", () => ({
      api: {
        post: vi.fn().mockResolvedValue({ status: "paid",
                                            invoice_id: "inv_abc" }),
      },
    }));
    // Import AFTER the mock is registered so the component picks up
    // the stub.
    const { default: PortalPaymentReturn } =
      await import("@/pages/portal/PortalPaymentReturn");

    render(
      <MemoryRouter initialEntries={["/portal/payment-method/return?session_id=cs_test_xyz"]}>
        <PortalPaymentReturn />
      </MemoryRouter>,
    );

    // First frame: loading spinner (no auth required).
    expect(
      screen.getByTestId("payment-return-loading"),
    ).toBeTruthy();

    // After the (stubbed) api.post resolves, the success outcome
    // renders. The success screen is the "paid" branch of the
    // state machine — proves the component is self-contained and
    // does not depend on portal-shell context.
    await waitFor(() => {
      expect(
        screen.getByTestId("payment-return-success"),
      ).toBeTruthy();
    });
  });
});
