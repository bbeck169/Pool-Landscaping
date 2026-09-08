/**
 * Feb-2026 · P0 defensive · Onboarding modal dismissal persistence.
 *
 * The user P0 diagnostic surfaced this modal as the top candidate
 * for the "web schedule freezes" perception bug: its
 * ``fixed inset-0 z-[60]`` backdrop was intercepting every pointer
 * event across the viewport, and its dismissal only wrote
 * ``sessionStorage`` — so on every new browser session it
 * re-appeared and re-blocked.
 *
 * These tests lock down the new contract:
 *   1. On close, the modal writes ``localStorage[
 *      "onboarding_modal_dismissed_v2"] = "1"`` AND fires
 *      ``POST /api/onboarding/progress {skipped: true}`` so the
 *      state persists across sessions and devices.
 *   2. On the next mount (simulating a second navigation), the
 *      modal DOES NOT render.
 *   3. The backdrop wrapper carries ``pointer-events: none`` so
 *      taps click through — no more "why is the schedule frozen"
 *      perception bug.
 *   4. The dismiss "×" button has a minimum 44×44 tap target (WCAG
 *      2.1 min interactive size).
 */
import React from "react";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// The API surface used by ``OnboardingLoginModal``. We stub it
// per-test so we can assert the exact backend call on dismiss.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from "@/api";
import { OnboardingLoginModal } from "../pages/onboarding/OnboardingPage";


function _renderAt(pathname = "/schedule") {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <OnboardingLoginModal />
    </MemoryRouter>,
  );
}


describe("OnboardingLoginModal · P0 dismissal persistence", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    api.get.mockReset();
    api.post.mockReset();
    // GET /onboarding returns "not yet dismissed" — the shape the
    // real backend endpoint returns for a fresh tenant.
    api.get.mockResolvedValue({ completed: false, skipped: false });
    api.post.mockResolvedValue({ ok: true });
  });
  afterEach(() => {
    cleanup();
  });

  it("renders the modal on first navigation to a non-admin page",
     async () => {
    _renderAt("/schedule");
    const modal = await screen.findByTestId("onboarding-modal");
    expect(modal).toBeInTheDocument();
    // P0 · backdrop is pointer-events-none so taps click through.
    expect(modal.className).toMatch(/pointer-events-none/);
    // Card inside re-enables pointer events so its buttons work.
    // The card is the parent element of the close button; use a
    // walk-up to find the first ancestor with the pointer-events-auto
    // class (rather than ``closest("div")`` which grabs the button
    // row wrapper).
    const closeBtn = screen.getByTestId("onboarding-modal-close");
    let card = closeBtn.parentElement;
    while (card && !/pointer-events-auto/.test(card.className || "")) {
      card = card.parentElement;
    }
    expect(card).not.toBeNull();
    expect(card.className).toMatch(/pointer-events-auto/);
  });

  it("does NOT render on second mount after dismissal — " +
       "localStorage guard + persist-to-backend", async () => {
    // First render: user clicks Skip.
    const first = _renderAt("/schedule");
    await screen.findByTestId("onboarding-modal");
    fireEvent.click(screen.getByTestId("onboarding-modal-skip"));
    // Modal disappears immediately (local guard).
    await waitFor(() =>
      expect(screen.queryByTestId("onboarding-modal")).toBeNull(),
    );
    // Backend PATCH fires with {skipped:true} — fire-and-forget.
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/onboarding/progress",
        { skipped: true },
      );
    });
    expect(localStorage.getItem("onboarding_modal_dismissed_v2")).toBe("1");
    first.unmount();
    cleanup();

    // Second render (simulating a fresh navigation / new tab): the
    // localStorage guard MUST short-circuit before the API even
    // fires.
    api.get.mockClear();
    _renderAt("/schedule");
    // Give the useEffect a tick to run.
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId("onboarding-modal")).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("close (×) button has a min 44×44 tap target (WCAG 2.1)",
     async () => {
    _renderAt("/schedule");
    const closeBtn = await screen.findByTestId("onboarding-modal-close");
    // Inline style is set to 44×44 — matching the source of truth
    // in ``OnboardingPage.jsx``. RTL doesn't compute layout so we
    // introspect the inline style directly.
    expect(closeBtn.style.width).toBe("44px");
    expect(closeBtn.style.height).toBe("44px");
    // The button dismisses AND persists (same path as Skip).
    fireEvent.click(closeBtn);
    await waitFor(() =>
      expect(screen.queryByTestId("onboarding-modal")).toBeNull(),
    );
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/onboarding/progress",
        { skipped: true },
      );
    });
  });

  it("skips the modal entirely on /admin/* paths (existing " +
       "P0 fix — regression guard)", async () => {
    _renderAt("/admin/migrations");
    // useEffect returns early before any GET fires.
    await new Promise((r) => setTimeout(r, 30));
    expect(api.get).not.toHaveBeenCalled();
    expect(screen.queryByTestId("onboarding-modal")).toBeNull();
  });

  it("honors the legacy sessionStorage flag for backwards-compat " +
       "so mid-session users don't get re-nagged after ship",
     async () => {
    sessionStorage.setItem("onboarding_modal_seen", "1");
    _renderAt("/schedule");
    await new Promise((r) => setTimeout(r, 30));
    expect(api.get).not.toHaveBeenCalled();
    expect(screen.queryByTestId("onboarding-modal")).toBeNull();
  });
});
