/**
 * TD-92 · Feb-2026 — AuthProvider portal impersonation bootstrap · Vitest.
 *
 * Regression guard on the ``td92b-fe`` fix: when a browser lands on
 * ``/portal/*`` with NO device-local admin login (empty
 * ``localStorage.token``) but the pre-mount K13 bootstrap in
 * ``src/index.js`` has pinned an impersonation token to
 * ``sessionStorage.portal_token`` + seeded ``localStorage.user``
 * with the decoded customer shape, ``AuthProvider`` must hydrate
 * ``user`` on the FIRST render so ``ProtectedShell`` admits the
 * portal route instead of redirecting to ``/portal/login``.
 *
 * Pre-TD-92 behaviour: ``_readCachedUserSync`` required
 * ``localStorage.token`` to be present → returned ``null`` →
 * ``user === null`` → redirect.  The useEffect self-heal also
 * early-returned on the same signal, so ``/auth/me`` never fired.
 *
 * Sibling pattern parity: ``test/auth-bootstrap-sync.test.jsx``
 * (localStorage-only hydrate), ``test/api-auth-headers-portal-gate.test.jsx``
 * (API client portal_token preference).  This file closes the
 * last K13-aware gap — ``auth.jsx`` itself.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// ── /auth/me mock ──────────────────────────────────────────────────
// Returns the customer identity we expect the BE to emit when the
// impersonation token is attached as Bearer.
const _mockMe = vi.fn(async () => ({
  id: "cust-u-1",
  email: "trina@customer.example",
  role: "customer",
  name: "Trina Testerson",
  customer_id: "cust-1",
  tenant_id: "tenant-1",
  is_impersonated: true,
  impersonator_id: "admin-99",
}));
vi.mock("@/api", () => ({
  api: { get: (...args) => _mockMe(...args), post: vi.fn(), put: vi.fn() },
  TOKEN_KEY: "token",
}));

import { AuthProvider, useAuth } from "@/auth";


function ProbeUser() {
  const { user, loading } = useAuth();
  return (
    <div>
      <span data-testid="user-email">{user?.email || "NO_USER"}</span>
      <span data-testid="user-role">{user?.role || "NO_ROLE"}</span>
      <span data-testid="loading">{loading ? "loading" : "ready"}</span>
    </div>
  );
}

// ── pathname pin helper ────────────────────────────────────────────
// ``_readCachedToken`` branches on ``window.location.pathname`` so
// each spec pins the path before mounting ``<AuthProvider>``.  Uses
// the same ``Object.defineProperty(window, "location", …)`` mock
// pattern as sibling ``test/api-auth-headers-portal-gate.test.jsx``
// (JSDOM blocks ``history.replaceState`` cross-origin URL writes).
let _realLocation;
function _pinPath(pathname) {
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: {
      pathname,
      search: "",
      assign: () => {},
      origin: "http://localhost:3000",
      href: `http://localhost:3000${pathname}`,
    },
  });
}
function _restoreLocation() {
  if (_realLocation) {
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: _realLocation,
    });
  }
}


describe("AuthProvider · TD-92 portal impersonation bootstrap", () => {
  beforeEach(() => {
    _realLocation = window.location;
    window.localStorage.clear();
    window.sessionStorage.clear();
    _mockMe.mockClear();
    _pinPath("/");
  });
  afterEach(() => {
    _restoreLocation();
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  // ── Spec 1 — primary fix path ─────────────────────────────────
  it("sync-hydrates `user` on /portal/* from sessionStorage.portal_token + seeded localStorage.user", () => {
    _pinPath("/portal/home");
    // K13 pre-mount bootstrap would have done exactly this:
    window.sessionStorage.setItem("portal_token", "impersonation-jwt");
    window.localStorage.setItem(
      "user",
      JSON.stringify({
        id: "cust-u-1",
        email: "trina@customer.example",
        role: "customer",
        name: "Trina Testerson",
        is_impersonated: true,
      }),
    );
    // Critically: NO localStorage.token (mobile browser never saw
    // an admin login on this device).
    expect(window.localStorage.getItem("token")).toBeNull();

    render(<AuthProvider><ProbeUser /></AuthProvider>);

    // FIRST render — pre-TD-92 this was "NO_USER" → redirect.
    expect(screen.getByTestId("user-email").textContent)
      .toBe("trina@customer.example");
    expect(screen.getByTestId("user-role").textContent).toBe("customer");
  });

  // ── Spec 2 — admin path isolation ─────────────────────────────
  it("ignores sessionStorage.portal_token on admin / non-portal routes", () => {
    _pinPath("/admin/customers");
    // Rogue sessionStorage token on an admin pathname must NOT
    // hydrate — admin routes stay localStorage-only.  Prevents a
    // mis-leaked portal_token from granting admin UI access.
    window.sessionStorage.setItem("portal_token", "impersonation-jwt");
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "x", email: "stale", role: "customer" }),
    );

    render(<AuthProvider><ProbeUser /></AuthProvider>);

    expect(screen.getByTestId("user-email").textContent).toBe("NO_USER");
  });

  // ── Spec 3 — async self-heal fires /auth/me ───────────────────
  it("fires /auth/me via useEffect when only sessionStorage.portal_token is present on /portal/*", async () => {
    _pinPath("/portal/home");
    window.sessionStorage.setItem("portal_token", "impersonation-jwt");
    // Seed matches the K13 pre-mount seed shape so sync-hydrate
    // also lands something; the self-heal then upgrades it to
    // the BE-authoritative payload.
    window.localStorage.setItem(
      "user",
      JSON.stringify({
        id: "cust-u-1", email: "seed@stale", role: "customer",
      }),
    );

    render(<AuthProvider><ProbeUser /></AuthProvider>);

    await waitFor(() => {
      expect(_mockMe).toHaveBeenCalledWith("/auth/me");
    });
    // Post self-heal, the probe reflects the BE payload (not the stale seed).
    await waitFor(() => {
      expect(screen.getByTestId("user-email").textContent)
        .toBe("trina@customer.example");
    });
  });

  // ── Spec 4 — localStorage.token preference on non-portal paths ─
  it("prefers localStorage.token on non-portal paths even when sessionStorage.portal_token is also set", async () => {
    _pinPath("/dashboard");
    window.localStorage.setItem("token", "admin-jwt");
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "admin-99", email: "admin@plofv.com", role: "admin" }),
    );
    window.sessionStorage.setItem("portal_token", "impersonation-jwt");

    render(<AuthProvider><ProbeUser /></AuthProvider>);

    // Sync hydrate must prefer the localStorage admin identity
    // (admin-same-tab happy path is unchanged).
    expect(screen.getByTestId("user-email").textContent).toBe("admin@plofv.com");
    expect(screen.getByTestId("user-role").textContent).toBe("admin");
    // Self-heal fires /auth/me (same existing behaviour under this
    // precondition — regression guard).
    await waitFor(() => {
      expect(_mockMe).toHaveBeenCalledWith("/auth/me");
    });
  });

  // ── Spec 5 — portal path WITH both tokens: sessionStorage wins ─
  it("prefers sessionStorage.portal_token over localStorage.token on /portal/* (K13 decoupling)", () => {
    _pinPath("/portal/home");
    // Admin in same browser profile has a localStorage.token AND
    // the portal tab has an impersonation sessionStorage token
    // (admin-view-as-customer happy path).  Portal tab must
    // hydrate the customer identity (seeded by K13 pre-mount),
    // not the admin identity.
    window.localStorage.setItem("token", "admin-jwt");
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "cust-u-1", email: "trina@customer.example", role: "customer" }),
    );
    window.sessionStorage.setItem("portal_token", "impersonation-jwt");

    render(<AuthProvider><ProbeUser /></AuthProvider>);

    expect(screen.getByTestId("user-email").textContent)
      .toBe("trina@customer.example");
    expect(screen.getByTestId("user-role").textContent).toBe("customer");
  });

  // ── Spec 6 — logout() leaves sessionStorage.portal_token alone ─
  it("logout() clears localStorage only; sessionStorage.portal_token lifetime stays per-tab", () => {
    _pinPath("/portal/home");
    window.localStorage.setItem("token", "admin-jwt");
    window.localStorage.setItem("user", JSON.stringify({ id: "x", role: "admin" }));
    window.localStorage.setItem("tenant_slug", "acme");
    window.sessionStorage.setItem("portal_token", "impersonation-jwt");

    function LogoutButton() {
      const { logout } = useAuth();
      return <button data-testid="do-logout" onClick={logout}>logout</button>;
    }
    render(<AuthProvider><LogoutButton /></AuthProvider>);
    screen.getByTestId("do-logout").click();

    expect(window.localStorage.getItem("token")).toBeNull();
    expect(window.localStorage.getItem("user")).toBeNull();
    expect(window.localStorage.getItem("tenant_slug")).toBeNull();
    // Per-tab portal_token lifetime is preserved — the K13
    // decoupling is maintained.  Session storage dies when the
    // tab closes; logout() does not need to race it.
    expect(window.sessionStorage.getItem("portal_token"))
      .toBe("impersonation-jwt");
  });
});
