/**
 * Phase P30 · Feb-2026 — SetupSuccess portal page behavioural tests.
 *
 * The customer arrives at ``/portal/setup-success`` after Stripe's
 * hosted Checkout Session (mode=setup) redirects them back with
 * ``?session_id=cs_...``. This page is a friendly confirmation screen
 * only — the server-side ``checkout.session.completed`` webhook
 * (filtered on ``metadata.source == "card_add_setup"``) is the
 * source of truth for the actual card attachment.
 *
 * Coverage:
 *   1. Happy path — ``?session_id=...`` present → renders success
 *      icon + "your card is saved" copy + Return-to-Portal link.
 *   2. Missing session_id → renders the "we couldn't confirm" fallback
 *      with the warn icon (no crash, no error page).
 *   3. Hidden session-id echo is present on the happy path so QA /
 *      support can eyeball which session landed on the page.
 *   4. Return-to-Portal link targets ``/portal`` in both states.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, afterEach } from "vitest";

import SetupSuccess from "@/pages/portal/SetupSuccess";


function _setLocation(search) {
  // JSDOM lets us reassign ``window.location`` cleanly with a full
  // URL — the page reads ``window.location.search`` directly, not
  // React Router's ``useLocation``.
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: new URL(`https://app.plofv.com/portal/setup-success${search}`),
  });
}


function _renderPage() {
  return render(
    <MemoryRouter>
      <SetupSuccess />
    </MemoryRouter>,
  );
}


describe("P30 · SetupSuccess portal page", () => {
  let _origLocation;

  beforeEach(() => {
    _origLocation = window.location;
  });

  afterEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true, writable: true, value: _origLocation,
    });
  });

  it("renders the success state when ?session_id=... is present", () => {
    _setLocation("?session_id=cs_test_stripe_abc123");
    _renderPage();
    const page = screen.getByTestId("setup-success-page");
    expect(page).toBeInTheDocument();
    expect(page.textContent).toMatch(/your card is saved/i);
    // The Return-to-Portal link is present and routes to /portal.
    const back = screen.getByTestId("setup-success-return-to-portal");
    expect(back).toBeInTheDocument();
    expect(back.getAttribute("href")).toBe("/portal");
  });

  it("echoes the session id in a hidden div for QA visibility", () => {
    _setLocation("?session_id=cs_test_echo_xyz");
    _renderPage();
    const echo = screen.getByTestId("setup-success-session-id");
    expect(echo.textContent).toBe("cs_test_echo_xyz");
    // Hidden from the customer visually.
    expect(echo.style.display).toBe("none");
    expect(echo.getAttribute("aria-hidden")).toBe("true");
  });

  it("renders the graceful fallback when session_id is missing", () => {
    _setLocation("");
    _renderPage();
    const fallback = screen.getByTestId("setup-success-missing-session");
    expect(fallback).toBeInTheDocument();
    expect(fallback.textContent).toMatch(/couldn't confirm/i);
    // Return-to-Portal link ALSO present on the fallback screen so
    // the customer never dead-ends.
    const back = screen.getByTestId("setup-success-return-to-portal");
    expect(back).toBeInTheDocument();
    expect(back.getAttribute("href")).toBe("/portal");
  });

  it("does NOT render the success state when session_id is missing", () => {
    _setLocation("");
    _renderPage();
    // The success testid MUST be absent on the fallback screen.
    expect(screen.queryByTestId("setup-success-page")).toBeNull();
    expect(screen.queryByTestId("setup-success-session-id")).toBeNull();
  });

  it("does NOT render the fallback when session_id IS present", () => {
    _setLocation("?session_id=cs_test_present");
    _renderPage();
    expect(
      screen.queryByTestId("setup-success-missing-session"),
    ).toBeNull();
  });
});
