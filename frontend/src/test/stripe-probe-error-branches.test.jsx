// P0e Stage 2 S2-3 · Feb-2026 — vitest for the Stripe probe result
// panel + the StripeCard testConn flow.
//
// Pins:
//   · GREEN state renders account id, mode, and timestamp.
//   · RED state (AuthenticationError) renders specific message +
//     "Re-enter Stripe Key" button.
//   · AMBER state (connectivity / rate-limited) does NOT render the
//     reconnect button.
//   · Pre-fix "Stripe probe failed:" generic text is NEVER rendered.
//   · Clicking reconnect triggers the connect-link flow.
//
// Follows the mock pattern established in
// src/test/i17a-integrations-page.test.jsx so the same hydration
// paths (/tenants/me/integrations + /schemas) are stubbed.
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockDelete = vi.fn();
const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    delete: (...a) => mockDelete(...a),
    put: vi.fn(), patch: vi.fn(), del: vi.fn(), request: vi.fn(),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(
    (...a) => mockToastSuccess(...a),
    { success: (...a) => mockToastSuccess(...a),
       error: (...a) => mockToastError(...a),
       info: vi.fn(), warning: vi.fn() },
  ),
}));
vi.mock("@/theme", () => ({
  colors: {
    brand: "#111", border: "#ccc", onSurface: "#000",
    onSurfaceSecondary: "#666", surfaceSecondary: "#eee",
  },
}));
vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(async () => true),
}));

import TenantIntegrationsCard from "../components/settings/TenantIntegrationsCard.jsx";

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockDelete.mockReset();
  mockToastSuccess.mockReset();
  mockToastError.mockReset();
  window.localStorage.clear();
  // Admin role so the Test/Disconnect buttons render.
  window.localStorage.setItem("user", JSON.stringify({
    id: "u-p0e", role: "admin", email: "admin@test",
  }));
  // JSDOM doesn't implement navigation.
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, assign: vi.fn(),
             pathname: "/settings/integrations", search: "", hash: "" },
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const _CONNECTED_STRIPE_ROW = {
  provider_key: "stripe",
  connected: true,
  kind: "payments",
  connected_account_id_masked: "acct_…7560",
  last_4: "1234",
  last_used_at: "2026-10-11T20:00:00Z",
};

function _installMocks({ probeResult, connectLinkUrl = "https://connect.stripe.test/oauth?x" } = {}) {
  mockGet.mockImplementation(async (path) => {
    if (path === "/tenants/me/integrations") {
      return { tenant_id: "t-vitest",
               integrations: [{ ..._CONNECTED_STRIPE_ROW }] };
    }
    if (path === "/tenants/me/integrations/schemas") {
      return { sms: [], email: [], ai: [], maps: [] };
    }
    if (path === "/tenants/me/integrations/health") {
      return { items: [] };
    }
    if (path?.startsWith("/tenants/me/integrations/ai/usage")
        || path?.startsWith("/tenants/me/integrations/maps/usage")) {
      return { providers: [] };
    }
    if (path === "/integrations/stripe/connect-link") {
      return { url: connectLinkUrl };
    }
    return {};
  });
  mockPost.mockImplementation(async (path) => {
    if (path === "/tenants/me/integrations/stripe/test") return probeResult;
    return {};
  });
}

function _renderCard() {
  return render(<TenantIntegrationsCard />);
}


describe("StripeCard probe result panel · P0e S2-2", () => {
  it("renders GREEN panel with masked account + mode + timestamp on success", async () => {
    _installMocks({ probeResult: {
      ok: true,
      connected_account_id_masked: "acct_…7560",
      mode: "live",
      checked_at: "2026-10-12T04:30:00Z",
      message: "Connected to Stripe account acct_…7560 (live mode).",
      error_code: null,
    }});
    _renderCard();
    await waitFor(() => {
      expect(screen.getByTestId("tenant-integration-stripe-test")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("tenant-integration-stripe-test"));
    await waitFor(() => {
      expect(screen.getByTestId("stripe-probe-result")).toBeInTheDocument();
    });
    const panel = screen.getByTestId("stripe-probe-result");
    expect(panel.getAttribute("data-tone")).toBe("green");
    expect(screen.getByTestId("stripe-probe-tone-label")).toHaveTextContent("Connected");
    expect(screen.getByTestId("stripe-probe-account")).toHaveTextContent("acct_…7560");
    expect(screen.getByTestId("stripe-probe-mode")).toHaveTextContent("live");
    expect(screen.getByTestId("stripe-probe-timestamp")).toBeInTheDocument();
    expect(screen.queryByTestId("stripe-probe-reenter-key")).toBeNull();
  });

  it("renders RED panel + 'Re-enter Stripe Key' button on AuthenticationError", async () => {
    _installMocks({ probeResult: {
      ok: false,
      error_code: "stripe_key_invalid_or_revoked",
      error_class: "AuthenticationError",
      message: "The stored Stripe secret key was rejected. It may have been revoked, rotated, or belongs to a different account. Click 'Re-enter Stripe Key' to update it.",
      remediation: "Reconnect Stripe via OAuth — the current token has been rejected by Stripe and must be refreshed.",
      checked_at: "2026-10-12T04:30:00Z",
      mode: "live",
    }});
    _renderCard();
    await waitFor(() => {
      expect(screen.getByTestId("tenant-integration-stripe-test")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("tenant-integration-stripe-test"));
    await waitFor(() => {
      expect(screen.getByTestId("stripe-probe-result")).toBeInTheDocument();
    });

    const panel = screen.getByTestId("stripe-probe-result");
    expect(panel.getAttribute("data-tone")).toBe("red");
    expect(panel.getAttribute("data-error-code")).toBe("stripe_key_invalid_or_revoked");

    const msg = screen.getByTestId("stripe-probe-message");
    expect(msg).toHaveTextContent(/rejected/);
    expect(msg).toHaveTextContent(/Re-enter Stripe Key/);
    expect(msg.textContent).not.toMatch(/^Stripe probe failed: AuthenticationError$/);

    expect(screen.getByTestId("stripe-probe-remediation")).toHaveTextContent(/OAuth|Reconnect/i);
    const reconnectBtn = screen.getByTestId("stripe-probe-reenter-key");
    expect(reconnectBtn).toBeInTheDocument();
    expect(reconnectBtn).toHaveTextContent("Re-enter Stripe Key");
  });

  it("renders AMBER panel WITHOUT reconnect button on APIConnectionError", async () => {
    _installMocks({ probeResult: {
      ok: false,
      error_code: "stripe_connectivity_error",
      error_class: "APIConnectionError",
      message: "Could not reach Stripe's API. Check your network / firewall and retry in a moment.",
      remediation: "Verify outbound HTTPS to api.stripe.com from the pod + retry.",
      checked_at: "2026-10-12T04:30:00Z",
    }});
    _renderCard();
    await waitFor(() => {
      expect(screen.getByTestId("tenant-integration-stripe-test")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("tenant-integration-stripe-test"));
    await waitFor(() => {
      expect(screen.getByTestId("stripe-probe-result")).toBeInTheDocument();
    });

    const panel = screen.getByTestId("stripe-probe-result");
    expect(panel.getAttribute("data-tone")).toBe("amber");
    expect(screen.queryByTestId("stripe-probe-reenter-key")).toBeNull();
  });

  it("renders RED panel + reconnect button on account_mismatch", async () => {
    _installMocks({ probeResult: {
      ok: false,
      error_code: "stripe_account_mismatch",
      error_class: "InvalidRequestError",
      message: "The Stripe key belongs to a different account than this tenant expects. Reconnect using the correct Stripe account.",
      remediation: "Disconnect this tenant from Stripe and reconnect using the intended Stripe account.",
      checked_at: "2026-10-12T04:30:00Z",
    }});
    _renderCard();
    await waitFor(() => {
      expect(screen.getByTestId("tenant-integration-stripe-test")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("tenant-integration-stripe-test"));
    await waitFor(() => {
      expect(screen.getByTestId("stripe-probe-reenter-key")).toBeInTheDocument();
    });
  });

  it("clicking 'Re-enter Stripe Key' triggers the connect-link flow", async () => {
    _installMocks({ probeResult: {
      ok: false,
      error_code: "stripe_key_invalid_or_revoked",
      error_class: "AuthenticationError",
      message: "The stored Stripe secret key was rejected.",
      remediation: "Reconnect Stripe via OAuth.",
      checked_at: "2026-10-12T04:30:00Z",
    }});
    const assignSpy = vi.fn();
    Object.defineProperty(window, "location", {
      writable: true,
      value: { ...window.location, assign: assignSpy },
    });
    _renderCard();
    await waitFor(() => {
      expect(screen.getByTestId("tenant-integration-stripe-test")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("tenant-integration-stripe-test"));
    await waitFor(() => {
      expect(screen.getByTestId("stripe-probe-reenter-key")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("stripe-probe-reenter-key"));
    await waitFor(() => {
      expect(assignSpy).toHaveBeenCalledWith(
        "https://connect.stripe.test/oauth?x",
      );
    });
  });

  it("renders the backend's specific message on each error branch (never the pre-fix generic)", async () => {
    const generic_regex = /^Stripe probe failed: /;
    const branches = [
      { error_code: "stripe_key_missing_scopes",
        message: "The Stripe key is valid but lacks required permissions." },
      { error_code: "stripe_connectivity_error",
        message: "Could not reach Stripe's API." },
      { error_code: "stripe_rate_limited",
        message: "Stripe is rate-limiting requests." },
      { error_code: "stripe_account_mismatch",
        message: "The Stripe key belongs to a different account." },
      { error_code: "stripe_api_error",
        message: "Stripe returned an unexpected error: foo." },
    ];
    for (const b of branches) {
      cleanup();
      _installMocks({ probeResult: {
        ok: false, ...b, checked_at: "2026-10-12T04:30:00Z",
        remediation: "do a thing",
      }});
      _renderCard();
      await waitFor(() => {
        expect(screen.getByTestId("tenant-integration-stripe-test")).toBeInTheDocument();
      });
      fireEvent.click(screen.getByTestId("tenant-integration-stripe-test"));
      await waitFor(() => {
        expect(screen.getByTestId("stripe-probe-message")).toBeInTheDocument();
      });
      const text = screen.getByTestId("stripe-probe-message").textContent;
      expect(text).not.toMatch(generic_regex);
      expect(text?.length || 0).toBeGreaterThan(5);
    }
  });
});
