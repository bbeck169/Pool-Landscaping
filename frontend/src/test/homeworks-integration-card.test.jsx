/**
 * Feb-2026 · Phase 1a — HomeworksIntegrationCard render + interactions.
 *
 * Covers:
 *   1. Disconnected state renders the "Connect Homeworks" button.
 *   2. Connected state renders the tenant metadata + Disconnect button.
 *   3. Non-super_admin sees no "Test refresh" button.
 *   4. Super_admin sees the "Test refresh" button.
 *   5. Connect button hits /oauth/start and redirects the window.
 *   6. Disconnect calls the DELETE endpoint (after confirm=true).
 *   7. Post-callback ?homeworks=connected surfaces the OK banner.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const mockGet    = vi.fn();
const mockPost   = vi.fn();
const mockDelete = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get:    (...a) => mockGet(...a),
    post:   (...a) => mockPost(...a),
    delete: (...a) => mockDelete(...a),
  },
}));

import HomeworksIntegrationCard from "@/components/settings/HomeworksIntegrationCard";

function _setUser(role) {
  localStorage.setItem("user", JSON.stringify({
    id: "u1", role, email: "test@aquaterra.com",
  }));
}

const _origConfirm = window.confirm;
let _assignSpy;

// jsdom's `window.location.assign` is non-configurable, so we replace
// the entire `window.location` object with a stub whose `assign` is a
// vi.fn() we can assert against.
const _origLocation = window.location;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  _assignSpy = vi.fn();
  delete window.location;
  window.location = {
    ..._origLocation,
    href: "http://localhost/settings/integrations",
    pathname: "/settings/integrations",
    search: "",
    origin: "http://localhost",
    assign: _assignSpy,
  };
  window.history.replaceState({}, "", "/settings/integrations");
  window.confirm = vi.fn(() => true);
});

afterEach(() => {
  window.location = _origLocation;
  window.confirm = _origConfirm;
});

describe("HomeworksIntegrationCard", () => {
  it("renders the Connect button when disconnected", async () => {
    _setUser("admin");
    mockGet.mockResolvedValue({ connected: false });
    render(<HomeworksIntegrationCard />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-connect-btn")).toBeTruthy();
    });
    expect(screen.getByTestId("homeworks-status-chip").textContent).toMatch(/not connected/i);
    // No disconnect button in the disconnected branch.
    expect(screen.queryByTestId("homeworks-disconnect-btn")).toBeNull();
  });

  it("renders the connected body + Disconnect when connected", async () => {
    _setUser("admin");
    mockGet.mockResolvedValue({
      connected: true,
      connected_by_email: "boss@aquaterra.com",
      connected_at: "2026-02-15T10:00:00Z",
      expires_at:  "2026-02-15T11:00:00Z",
      scope: "openid company",
    });
    render(<HomeworksIntegrationCard />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-connected-body")).toBeTruthy();
    });
    expect(screen.getByTestId("homeworks-status-chip").textContent).toMatch(/connected/i);
    expect(screen.getByTestId("homeworks-disconnect-btn")).toBeTruthy();
    // Non-super_admin does NOT see the debug refresh button.
    expect(screen.queryByTestId("homeworks-debug-refresh-btn")).toBeNull();
  });

  it("shows Test refresh only for super_admin", async () => {
    _setUser("super_admin");
    mockGet.mockResolvedValue({
      connected: true,
      connected_by_email: "root@aquaterra.com",
      connected_at: "2026-02-15T10:00:00Z",
      expires_at:  "2026-02-15T11:00:00Z",
      scope: "openid company",
    });
    render(<HomeworksIntegrationCard />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-debug-refresh-btn")).toBeTruthy();
    });
  });

  it("Connect button hits /oauth/start and redirects the browser", async () => {
    _setUser("admin");
    mockGet.mockResolvedValueOnce({ connected: false })    // initial status
           .mockResolvedValueOnce({ authorize_url: "https://api.home.works/oauth/authorize?state=x" });
    render(<HomeworksIntegrationCard />);
    const btn = await screen.findByTestId("homeworks-connect-btn");
    await act(async () => { fireEvent.click(btn); });
    await waitFor(() => {
      expect(_assignSpy).toHaveBeenCalledWith(
        "https://api.home.works/oauth/authorize?state=x",
      );
    });
    // Both api.get calls fired — status + start.
    expect(mockGet).toHaveBeenCalledWith("/integrations/homeworks/status");
    expect(mockGet).toHaveBeenCalledWith("/integrations/homeworks/oauth/start");
  });

  it("Disconnect calls DELETE after confirm=true", async () => {
    _setUser("admin");
    mockGet.mockResolvedValueOnce({
      connected: true, connected_by_email: "boss@aquaterra.com",
      connected_at: "2026-02-15T10:00:00Z",
      expires_at: "2026-02-15T11:00:00Z",
      scope: "openid company",
    }).mockResolvedValueOnce({ connected: false });   // after delete
    mockDelete.mockResolvedValue({ ok: true, deleted: 1 });

    render(<HomeworksIntegrationCard />);
    const btn = await screen.findByTestId("homeworks-disconnect-btn");
    await act(async () => { fireEvent.click(btn); });
    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith("/integrations/homeworks/disconnect");
    });
  });

  it("surfaces the OK banner after ?homeworks=connected landing", async () => {
    _setUser("admin");
    mockGet.mockResolvedValue({ connected: true,
      connected_by_email: "boss@aquaterra.com",
      connected_at: "2026-02-15T10:00:00Z",
      expires_at: "2026-02-15T11:00:00Z",
      scope: "openid company" });
    window.location.search = "?homeworks=connected";
    window.location.href = "http://localhost/settings/integrations?homeworks=connected";
    render(<HomeworksIntegrationCard />);
    await waitFor(() => {
      expect(screen.getByTestId("homeworks-banner-ok")).toBeTruthy();
    });
  });

  it("hides the entire card for a customer role", () => {
    _setUser("customer");
    mockGet.mockResolvedValue({ connected: false });
    const { container } = render(<HomeworksIntegrationCard />);
    expect(container.firstChild).toBeNull();
  });
});
