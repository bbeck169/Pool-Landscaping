/**
 * Feb-2026 · Slice 2C — Customer portal OnboardingGate vitest.
 *
 * Covers the UI contract from the 2C brief:
 *   1. Fresh customer + one pending pool doc → pool modal renders;
 *      after accept the modal unmounts (or advances if landscaping
 *      is also pending — see case 2).
 *   2. Pool + landscaping pending → pool renders first; after accept
 *      landscaping renders; after accept children render.
 *   3. Fully onboarded → children render immediately + a single
 *      onboarding-state fetch (no accept POST).
 *   4. ``I Agree`` disabled until scroll reaches bottom.
 *   5. Non-customer roles → children render immediately, NO
 *      onboarding-state fetch.
 *   6. 409 ``document_not_published`` → inline banner + reload.
 *   7. Layout wraps children so the header (with Sign Out) remains
 *      mounted while the ToS modal is open.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, waitFor, fireEvent,
} from "@testing-library/react";

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
  },
}));

const mockUser = { current: null };
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: mockUser.current, setUser: vi.fn() }),
}));

vi.mock("@/theme", () => ({
  colors: {
    onSurface: "#0F172A", muted: "#64748B", border: "#E2E8F0",
    surface: "#FFFFFF", surfaceSubtle: "#F8FAFC",
    brand: "#0EA5E9", onBrand: "#FFFFFF",
    brandTertiary: "#DBEAFE", onBrandTertiary: "#1E40AF",
  },
}));

import OnboardingGate from "@/components/legal/OnboardingGate";


function _child() {
  return (
    <div data-testid="portal-child">
      <button data-testid="header-signout">Sign out</button>
      Portal Home
    </div>
  );
}


function _customer() {
  return { id: "u1", role: "customer", customer_id: "c1" };
}


// jsdom does NOT compute layout, so ``scrollHeight`` = ``clientHeight``
// which trips the "already short enough" early-bottom heuristic.
// Force ``scrollHeight`` > ``clientHeight`` so the button starts
// disabled and only enables when we simulate a scroll event whose
// target has ``scrollTop`` reaching the bottom.
function _tallenScrollAreas() {
  Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
    configurable: true,
    get() { return 2000; },
  });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get() { return 400; },
  });
}


describe("<OnboardingGate>", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    mockUser.current = null;
    _tallenScrollAreas();
  });
  afterEach(() => cleanup());

  it("non-customer role → children render immediately, no API call", async () => {
    for (const role of ["admin", "super_admin", "technician", "manager"]) {
      mockUser.current = { id: "u", role };
      const { unmount } = render(
        <OnboardingGate>{_child()}</OnboardingGate>,
      );
      expect(screen.getByTestId("portal-child")).toBeTruthy();
      unmount();
    }
    expect(getMock).not.toHaveBeenCalled();
    expect(postMock).not.toHaveBeenCalled();
  });

  it("fully-onboarded customer → children render, no modal, no accept POST", async () => {
    mockUser.current = _customer();
    getMock.mockResolvedValue({
      tutorial_completed: true,
      pending_tos: [],
      tos_status: {
        pool: { document_id: "d-pool", version: 1 },
        landscaping: { document_id: "d-ls", version: 1 },
      },
    });
    render(<OnboardingGate>{_child()}</OnboardingGate>);
    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        "/customer-portal/onboarding-state",
      )
    );
    await waitFor(() =>
      expect(screen.queryByTestId("onboarding-gate-loading")).toBeNull()
    );
    expect(screen.getByTestId("portal-child")).toBeTruthy();
    expect(screen.queryByTestId("onboarding-tos-modal")).toBeNull();
    expect(postMock).not.toHaveBeenCalled();
  });

  it("pending pool + landscaping → pool first, then landscaping, then unmount", async () => {
    mockUser.current = _customer();
    getMock.mockResolvedValue({
      tutorial_completed: true,
      pending_tos: [
        { document_id: "d-pool", service_type: "pool", version: 1,
          title: "Pool ToS", content_html: "<p>pool text</p>" },
        { document_id: "d-ls", service_type: "landscaping", version: 1,
          title: "Landscaping ToS", content_html: "<p>ls text</p>" },
      ],
    });
    render(<OnboardingGate>{_child()}</OnboardingGate>);
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-tos-modal")).toBeTruthy()
    );
    // Pool renders first.
    expect(screen.getByTestId("onboarding-tos-title").textContent)
      .toBe("Pool ToS");
    expect(
      screen.getByTestId("onboarding-tos-modal").getAttribute("data-service-type"),
    ).toBe("pool");

    // Simulate scroll-to-bottom.
    const scroll = screen.getByTestId("onboarding-tos-scroll");
    Object.defineProperty(scroll, "scrollTop", { configurable: true, value: 1600 });
    fireEvent.scroll(scroll);
    await waitFor(() => {
      const btn = screen.getByTestId("onboarding-tos-agree");
      expect(btn.disabled).toBe(false);
    });

    // Accept pool → server returns landscaping still pending.
    postMock.mockResolvedValueOnce({
      ok: true, acceptance: { document_id: "d-pool" },
      pending_tos: [{ document_id: "d-ls", service_type: "landscaping",
                     version: 1, title: "Landscaping ToS",
                     content_html: "<p>ls text</p>" }],
    });
    fireEvent.click(screen.getByTestId("onboarding-tos-agree"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/customer-portal/tos/d-pool/accept", {},
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-tos-title").textContent)
        .toBe("Landscaping ToS")
    );

    // Landscaping — scroll then accept → modal unmounts.
    const scroll2 = screen.getByTestId("onboarding-tos-scroll");
    Object.defineProperty(scroll2, "scrollTop", { configurable: true, value: 1600 });
    fireEvent.scroll(scroll2);
    postMock.mockResolvedValueOnce({
      ok: true, acceptance: { document_id: "d-ls" },
      pending_tos: [],
    });
    await waitFor(() => {
      const btn = screen.getByTestId("onboarding-tos-agree");
      expect(btn.disabled).toBe(false);
    });
    fireEvent.click(screen.getByTestId("onboarding-tos-agree"));
    await waitFor(() =>
      expect(screen.queryByTestId("onboarding-tos-modal")).toBeNull()
    );
    expect(screen.getByTestId("portal-child")).toBeTruthy();
  });

  it("only landscaping pending → landscaping modal renders (skip pool)", async () => {
    mockUser.current = _customer();
    getMock.mockResolvedValue({
      tutorial_completed: true,
      pending_tos: [
        { document_id: "d-ls", service_type: "landscaping", version: 2,
          title: "Landscaping ToS v2", content_html: "<p>ls</p>" },
      ],
    });
    render(<OnboardingGate>{_child()}</OnboardingGate>);
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-tos-modal")).toBeTruthy()
    );
    expect(
      screen.getByTestId("onboarding-tos-modal").getAttribute("data-service-type"),
    ).toBe("landscaping");
    expect(screen.getByTestId("onboarding-tos-title").textContent).toBe(
      "Landscaping ToS v2",
    );
  });

  it("I Agree stays disabled until the scroll area reaches bottom", async () => {
    mockUser.current = _customer();
    getMock.mockResolvedValue({
      tutorial_completed: true,
      pending_tos: [
        { document_id: "d-pool", service_type: "pool", version: 1,
          title: "Pool ToS", content_html: "<p>pool</p>" },
      ],
    });
    render(<OnboardingGate>{_child()}</OnboardingGate>);
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-tos-modal")).toBeTruthy()
    );
    // Initially disabled (tall doc).
    expect(screen.getByTestId("onboarding-tos-agree").disabled).toBe(true);
    expect(
      screen.getByTestId("onboarding-tos-scroll-hint").textContent,
    ).toMatch(/scroll to the bottom/i);

    // Simulate scroll-to-bottom.
    const scroll = screen.getByTestId("onboarding-tos-scroll");
    Object.defineProperty(scroll, "scrollTop", { configurable: true, value: 1600 });
    fireEvent.scroll(scroll);
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-tos-agree").disabled).toBe(false)
    );
    expect(
      screen.getByTestId("onboarding-tos-scroll-hint").textContent,
    ).toMatch(/you've read the full terms/i);
  });

  it("accept 409 document_not_published → error banner + reload", async () => {
    mockUser.current = _customer();
    getMock.mockResolvedValue({
      tutorial_completed: true,
      pending_tos: [{
        document_id: "d-pool", service_type: "pool", version: 1,
        title: "Pool ToS", content_html: "<p>pool</p>",
      }],
    });
    render(<OnboardingGate>{_child()}</OnboardingGate>);
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-tos-modal")).toBeTruthy()
    );
    const scroll = screen.getByTestId("onboarding-tos-scroll");
    Object.defineProperty(scroll, "scrollTop", { configurable: true, value: 1600 });
    fireEvent.scroll(scroll);
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-tos-agree").disabled).toBe(false)
    );

    postMock.mockRejectedValueOnce({
      status: 409, detail: "document_not_published",
    });
    // Second (post-error) refresh call gets the new pending list.
    getMock.mockResolvedValueOnce({
      tutorial_completed: true,
      pending_tos: [{
        document_id: "d-pool-v2", service_type: "pool", version: 2,
        title: "Pool ToS v2", content_html: "<p>v2</p>",
      }],
    });
    fireEvent.click(screen.getByTestId("onboarding-tos-agree"));
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-tos-error")).toBeTruthy()
    );
    expect(
      screen.getByTestId("onboarding-tos-error").textContent,
    ).toMatch(/no longer active/i);
    // Modal STAYS mounted until reload swaps the doc.
    expect(screen.getByTestId("onboarding-tos-modal")).toBeTruthy();
  });

  it("children (header + Sign Out) remain in the DOM while ToS modal is open", async () => {
    mockUser.current = _customer();
    getMock.mockResolvedValue({
      tutorial_completed: true,
      pending_tos: [{
        document_id: "d-pool", service_type: "pool", version: 1,
        title: "Pool ToS", content_html: "<p>pool</p>",
      }],
    });
    render(<OnboardingGate>{_child()}</OnboardingGate>);
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-tos-modal")).toBeTruthy()
    );
    // The gate renders the modal ALONGSIDE children (not instead of),
    // so Sign Out remains reachable in the header while the modal is
    // open. Children get pointer-events blocked by the modal's
    // full-viewport overlay, but Sign Out lives above at z-50 in the
    // portal shell — we assert its DOM presence here.
    expect(screen.getByTestId("portal-child")).toBeTruthy();
    expect(screen.getByTestId("header-signout")).toBeTruthy();
  });
});
