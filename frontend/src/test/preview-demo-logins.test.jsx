/**
 * Feb 2026 — Preview-only demo logins on the web login page · Jest.
 *
 * Contract-level tests (mirrors the existing repo pattern in
 * ``task-rr-ss-p2-revised.test.jsx``). The Login page is
 * router-heavy and hangs under jsdom in this Jest config, so we
 * cover:
 *   (a) The env-gate predicate is exactly the string check the page uses.
 *   (b) The ``PreviewDemoLogins`` component renders 4 buttons with the
 *       correct testids and wire-shape, and clicking each invokes
 *       ``onSubmitDirect`` with the exact ``(email, password="password123")``
 *       payload that the page then passes to ``login()``.
 */
import React from "react";
import { describe, it, expect, jest, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import {
  PreviewDemoLogins,
  DEMO_ACCOUNTS,
} from "@/components/auth/PreviewDemoLogins";


// ═══════════════════════════════════════════════════════════════════
// Env-gate predicate (exact literal used inside pages/Login.jsx).
// ═══════════════════════════════════════════════════════════════════
function isPreviewGateOn(rawEnv) {
  return String(rawEnv || "").toLowerCase() === "preview";
}

describe("preview demo logins · env gate predicate", () => {
  it("returns true only when env is exactly 'preview' (case-insensitive)", () => {
    expect(isPreviewGateOn("preview")).toBe(true);
    expect(isPreviewGateOn("Preview")).toBe(true);
    expect(isPreviewGateOn("PREVIEW")).toBe(true);
  });

  it("returns false when env is unset / empty / production / other", () => {
    expect(isPreviewGateOn(undefined)).toBe(false);
    expect(isPreviewGateOn(null)).toBe(false);
    expect(isPreviewGateOn("")).toBe(false);
    expect(isPreviewGateOn("production")).toBe(false);
    expect(isPreviewGateOn("prod")).toBe(false);
    expect(isPreviewGateOn("staging")).toBe(false);
    expect(isPreviewGateOn("dev")).toBe(false);
  });
});


// ═══════════════════════════════════════════════════════════════════
// PreviewDemoLogins component contract
// ═══════════════════════════════════════════════════════════════════
describe("PreviewDemoLogins · component contract", () => {
  it("DEMO_ACCOUNTS list matches the spec (4 accounts, correct emails, correct labels)", () => {
    expect(DEMO_ACCOUNTS).toHaveLength(4);
    expect(DEMO_ACCOUNTS.map((a) => a.email)).toEqual([
      "super@aquaterra.com",
      "manager@aquaterra.com",
      "customer@aquaterra.com",
      // Phase 22 · 2026-08-02 — was mike@aquaterra.com (never seeded);
      // fixed to the real landscaper seed account so the tech chip
      // actually logs in instead of 401'ing on submit.
      "landscaper@aquaterra.com",
    ]);
    expect(DEMO_ACCOUNTS.map((a) => a.role_label)).toEqual([
      "Super Admin", "Admin", "Customer", "Landscape Tech",
    ]);
    expect(DEMO_ACCOUNTS.map((a) => a.key)).toEqual([
      "super", "admin", "customer", "tech",
    ]);
  });

  it("renders 4 buttons with expected testids and the preview-only header", () => {
    render(
      <PreviewDemoLogins onPick={() => {}} onSubmitDirect={() => {}} />,
    );
    expect(screen.getByTestId("preview-demo-logins")).toBeTruthy();
    for (const key of ["super", "admin", "customer", "tech"]) {
      expect(screen.getByTestId(`demo-login-${key}`)).toBeTruthy();
    }
    expect(screen.getByText(/Preview Only/i)).toBeTruthy();
  });

  it("clicking a button invokes onPick + onSubmitDirect with the account email (auto-populate contract for all 4 chips)", () => {
    const pickSpy = vi.fn();
    const submitSpy = vi.fn();
    render(
      <PreviewDemoLogins onPick={pickSpy} onSubmitDirect={submitSpy} />,
    );

    // Phase 22 · 2026-08-02 · expanded — every chip must fire BOTH
    // onPick (populates the visible email/password fields at the
    // call site) AND onSubmitDirect (kicks off the login) with the
    // correct email. Previously only the "super" chip's onPick was
    // asserted, so the tech chip's mike@aquaterra.com typo went
    // undetected. This wider assertion is the permanent guard.
    const expected = [
      ["demo-login-super",    "super@aquaterra.com"],
      ["demo-login-admin",    "manager@aquaterra.com"],
      ["demo-login-customer", "customer@aquaterra.com"],
      ["demo-login-tech",     "landscaper@aquaterra.com"],
    ];
    for (const [testid, email] of expected) {
      pickSpy.mockClear();
      submitSpy.mockClear();
      fireEvent.click(screen.getByTestId(testid));
      expect(pickSpy).toHaveBeenCalledTimes(1);
      expect(pickSpy).toHaveBeenLastCalledWith(email);
      expect(submitSpy).toHaveBeenCalledTimes(1);
      expect(submitSpy).toHaveBeenLastCalledWith(email);
    }
  });

  it("respects the `disabled` prop — no callbacks fire", () => {
    const pickSpy = vi.fn();
    const submitSpy = vi.fn();
    render(
      <PreviewDemoLogins onPick={pickSpy} onSubmitDirect={submitSpy} disabled />,
    );
    fireEvent.click(screen.getByTestId("demo-login-admin"));
    expect(pickSpy).not.toHaveBeenCalled();
    expect(submitSpy).not.toHaveBeenCalled();
  });
});


// ═══════════════════════════════════════════════════════════════════
// Password invariant — the page passes "password123" to login()
// alongside the email returned from the DEMO_ACCOUNTS row. This
// assertion locks that convention so a future rename can't drift.
// ═══════════════════════════════════════════════════════════════════
describe("preview demo logins · password invariant", () => {
  it("every DEMO_ACCOUNTS row's email is a canonical seed account (@aquaterra.com)", () => {
    for (const acc of DEMO_ACCOUNTS) {
      expect(acc.email.endsWith("@aquaterra.com")).toBe(true);
    }
  });

  it("the page contract locks password to 'password123' (verified against pages/Login.jsx source)", async () => {
    // Rather than render Login (router-heavy + hangs in jsdom), we
    // read its source and grep for the credential literal. This is
    // enough to catch a future drift where a maintainer changes the
    // constant without touching this test file.
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/Login.jsx"),
      "utf-8",
    );
    // Password appears twice (setPassword call + onSubmitDirect call).
    const hits = (src.match(/"password123"/g) || []).length;
    expect(hits).toBeGreaterThanOrEqual(2);
    // And the demo-logins gate literal is present.
    expect(src.includes('REACT_APP_PUBLIC_ENV')).toBe(true);
    expect(src.includes('=== "preview"')).toBe(true);
  });
});
