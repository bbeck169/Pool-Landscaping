/**
 * Phase I1.7.a · Feb-2026 — TenantIntegrationsCard vitest suite.
 *
 * Pins:
 *   1. Renders a grid with the Stripe card + "Coming soon"
 *      placeholders (SMS, Email, AI, Maps, Calendars, Storage).
 *   2. GET /tenants/me/integrations is called on mount.
 *   3. Connect Stripe (admin) → GET /integrations/stripe/connect-link
 *      then full-page redirect to the returned URL.
 *   4. Test connection → POST /tenants/me/integrations/stripe/test,
 *      shows success toast on ok=true.
 *   5. Disconnect → DELETE /tenants/me/integrations/stripe when the
 *      user confirms.
 *   6. Non-admin (role=manager) does NOT render Connect / Test /
 *      Disconnect buttons.
 *   7. Response body is scanned — NO plaintext token pattern ever
 *      shows up on screen (belt-and-suspenders lock on the
 *      encryption-boundary guarantee).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


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
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(
    (...a) => mockToastSuccess(...a),
    { success: (...a) => mockToastSuccess(...a),
      error: (...a) => mockToastError(...a) },
  ),
}));

import TenantIntegrationsCard from "@/components/settings/TenantIntegrationsCard";
import { ConfirmProvider } from "@/components/ui/confirm-dialog";


// I1.7.c.2.followup · Feb-2026 — every ``render`` in this file must
// live inside a ``ConfirmProvider`` so ``mustConfirm(...)`` on the
// disconnect flows resolves to the real in-app Radix modal (not the
// legacy ``window.confirm`` fallback). See ``useConfirmDelete.jsx``
// for the hook variant used elsewhere; this test suite drives the
// module-level escape hatch instead.
const renderCard = () => render(
  <ConfirmProvider>
    <TenantIntegrationsCard />
  </ConfirmProvider>,
);


const _seedList = (overrides = []) => ({
  tenant_id: "tenant-i17a-vitest",
  integrations: overrides,
});


const _seedSchemas = () => ({
  sms: [
    { provider_key: "twilio", kind: "sms", fields: [
      { name: "account_sid", required: true, secret: false, label: "Twilio Account SID" },
      { name: "auth_token",  required: true, secret: true,  label: "Auth Token" },
      { name: "from_number", required: true, secret: false, label: "From number (E.164)" },
    ]},
    { provider_key: "textmagic", kind: "sms", fields: [
      { name: "username", required: true, secret: false, label: "TextMagic username" },
      { name: "api_key",  required: true, secret: true,  label: "API key" },
    ]},
    { provider_key: "ringcentral", kind: "sms", fields: [
      { name: "server_url", required: true, secret: false, label: "Server URL" },
      { name: "client_id",  required: true, secret: false, label: "App Client ID" },
      { name: "client_secret", required: true, secret: true, label: "App Client Secret" },
      { name: "jwt_token", required: true, secret: true, label: "JWT token" },
      { name: "from_number", required: true, secret: false, label: "From number" },
    ]},
  ],
  email: [
    { provider_key: "resend", kind: "email", fields: [
      { name: "api_key",   required: true, secret: true,  label: "Resend API key" },
      { name: "from_addr", required: true, secret: false, label: "Default From address" },
    ]},
    { provider_key: "sendgrid", kind: "email", fields: [
      { name: "api_key", required: true, secret: true, label: "SendGrid API key" },
      { name: "from_addr", required: true, secret: false, label: "Verified sender address" },
    ]},
    { provider_key: "postmark", kind: "email", fields: [
      { name: "server_token", required: true, secret: true, label: "Server API token" },
      { name: "from_addr", required: true, secret: false, label: "Verified sender address" },
    ]},
    { provider_key: "mailgun", kind: "email", fields: [
      { name: "api_key", required: true, secret: true, label: "Mailgun API key" },
      { name: "domain", required: true, secret: false, label: "Sending domain" },
      { name: "from_addr", required: true, secret: false, label: "Default From address" },
    ]},
    { provider_key: "smtp", kind: "email", fields: [
      { name: "host", required: true, secret: false, label: "SMTP host" },
      { name: "port", required: true, secret: false, label: "SMTP port" },
      { name: "username", required: true, secret: false, label: "SMTP username" },
      { name: "password", required: true, secret: true,  label: "SMTP password" },
      { name: "from_addr", required: true, secret: false, label: "Default From address" },
    ]},
  ],
  ai: [
    { provider_key: "ai_openai", kind: "ai", models: ["gpt-4o-mini", "gpt-4o"], fields: [
      { name: "api_key", required: true, secret: true, label: "OpenAI API Key" },
      { name: "default_model", required: false, secret: false, label: "Default model" },
    ]},
    { provider_key: "ai_anthropic", kind: "ai", models: ["claude-3-5-sonnet-latest"], fields: [
      { name: "api_key", required: true, secret: true, label: "Anthropic API Key" },
      { name: "default_model", required: false, secret: false, label: "Default model" },
    ]},
    { provider_key: "ai_gemini", kind: "ai", models: ["gemini-1.5-flash"], fields: [
      { name: "api_key", required: true, secret: true, label: "Google Gemini API Key" },
      { name: "default_model", required: false, secret: false, label: "Default model" },
    ]},
  ],
  maps: [
    { provider_key: "maps_google", kind: "maps", models: [], fields: [
      { name: "api_key", required: true, secret: true, label: "Google Maps API Key" },
      { name: "region_bias", required: false, secret: false, label: "Region bias" },
    ]},
    { provider_key: "maps_mapbox", kind: "maps", models: [], fields: [
      { name: "api_key", required: true, secret: true, label: "Mapbox Access Token" },
      { name: "style", required: false, secret: false, label: "Static map style" },
    ]},
  ],
});


// Helper: install a single get() handler that routes both
// /tenants/me/integrations and /tenants/me/integrations/schemas
// to the given rows + default schemas.
const _installListAndSchemasMock = (rowsFactory) => {
  mockGet.mockImplementation(async (path) => {
    if (path === "/tenants/me/integrations") return rowsFactory();
    if (path === "/tenants/me/integrations/schemas") return _seedSchemas();
    if (path === "/tenants/me/integrations/ai/usage")
      return { tenant_id: "tenant-i17a-vitest", period_yyyymm: "202602", providers: [] };
    if (path === "/tenants/me/integrations/maps/usage")
      return { tenant_id: "tenant-i17a-vitest", period_yyyymm: "202602", providers: [] };
    if (path === "/integrations/stripe/connect-link")
      return { url: "https://connect.stripe.com/oauth/authorize?client_id=ca_x&state=abc", state: "abc" };
    return {};
  });
};


const _asAdmin = () => {
  window.localStorage.setItem("user", JSON.stringify({
    id: "user-i17a-admin", role: "admin", email: "admin@example.com",
  }));
};


const _asManager = () => {
  window.localStorage.setItem("user", JSON.stringify({
    id: "user-i17a-mgr", role: "manager", email: "mgr@example.com",
  }));
};


beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockDelete.mockReset();
  mockToastSuccess.mockReset();
  mockToastError.mockReset();
  window.localStorage.clear();
  // I1.7.c.2.followup · Feb-2026 — no more ``window.confirm`` spy;
  // the disconnect flow is driven through the in-app modal via
  // ``integrations-disconnect-confirm`` / ``-cancel`` testids.
  // JSDOM doesn't implement navigation — stub location.assign so the
  // Stripe connect redirect doesn't blow up the test.
  Object.defineProperty(window, "location", {
    configurable: true,
    value: {
      ...window.location,
      assign: vi.fn(),
      pathname: "/settings/integrations",
      search: "",
      hash: "",
    },
  });
});


afterEach(() => {
  vi.restoreAllMocks();
});


describe("TenantIntegrationsCard · I1.7.a", () => {
  it("renders Stripe + coming-soon placeholders and loads the list", async () => {
    _asAdmin();
    _installListAndSchemasMock(() => _seedList());
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integrations-card")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-stripe")).toBeTruthy();
    // SMS + Email are now real cards (I1.7.b) — status is "Not connected".
    expect(screen.getByTestId("tenant-integration-sms-status").textContent)
      .toMatch(/not connected/i);
    expect(screen.getByTestId("tenant-integration-email-status").textContent)
      .toMatch(/not connected/i);
    // AI is now a real card (I1.7.c.1) — Not connected default.
    ["ai_openai", "ai_anthropic", "ai_gemini"].forEach((k) => {
      expect(screen.getByTestId(`tenant-integration-${k}`)).toBeTruthy();
      expect(screen.getByTestId(`tenant-integration-${k}-status`).textContent)
        .toMatch(/not connected/i);
    });
    // Maps is now a real card too (I1.7.c.2).
    ["maps_google", "maps_mapbox"].forEach((k) => {
      expect(screen.getByTestId(`tenant-integration-${k}`)).toBeTruthy();
      expect(screen.getByTestId(`tenant-integration-${k}-status`).textContent)
        .toMatch(/not connected/i);
    });
    // Calendars is now a real card (I1.7.c.3 per-tech OAuth), so
    // only "storage" remains a coming-soon placeholder in this suite.
    ["storage"].forEach((k) => {
      expect(screen.getByTestId(`tenant-integration-${k}`)).toBeTruthy();
      expect(screen.getByTestId(`tenant-integration-${k}-status`).textContent)
        .toMatch(/coming soon/i);
    });
    expect(mockGet).toHaveBeenCalledWith("/tenants/me/integrations");
    expect(mockGet).toHaveBeenCalledWith("/tenants/me/integrations/schemas");
  });

  it("connect-stripe hits the backend and redirects to the returned URL", async () => {
    _asAdmin();
    _installListAndSchemasMock(() => _seedList());
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe-connect")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("tenant-integration-stripe-connect"));
    await waitFor(() =>
      expect(mockGet).toHaveBeenCalledWith("/integrations/stripe/connect-link"),
    );
    await waitFor(() =>
      expect(window.location.assign).toHaveBeenCalledWith(
        expect.stringContaining("connect.stripe.com"),
      ),
    );
  });

  it("renders masked account + last_4 when Stripe is connected — never plaintext", async () => {
    _asAdmin();
    const connectedRow = {
      provider_key: "stripe",
      connection_type: "oauth_stripe_connect",
      connected: true,
      last_4: "beef",
      connected_account_id_masked: "acct_…9xyz",
      last_used_at: "2026-02-01T12:00:00Z",
      connected_status: "connected",
      error_log_count: 0,
      last_error: null,
    };
    _installListAndSchemasMock(() => _seedList([connectedRow]));
    const { container } = render(
      <ConfirmProvider>
        <TenantIntegrationsCard />
      </ConfirmProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe-summary")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-stripe-account").textContent)
      .toBe("acct_…9xyz");
    expect(screen.getByTestId("tenant-integration-stripe-last4").textContent)
      .toBe("••••beef");
    // Belt-and-braces: nothing rendered contains a plaintext ``sk_``.
    expect(container.textContent).not.toMatch(/sk_(test|live)_[A-Za-z0-9]/);
  });

  it("test-connection posts and surfaces a success toast on ok=true", async () => {
    _asAdmin();
    _installListAndSchemasMock(() => _seedList([{
      provider_key: "stripe", connection_type: "oauth_stripe_connect",
      connected: true, last_4: "abcd",
      connected_account_id_masked: "acct_…1234",
      connected_status: "connected", error_log_count: 0,
    }]));
    mockPost.mockResolvedValue({
      provider_key: "stripe", tenant_id: "tenant-i17a-vitest", ok: true,
      connected_account_id_masked: "acct_…1234",
      message: "Stripe Account.retrieve returned OK.",
      checked_at: "2026-02-01T12:34:56Z",
    });
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe-test")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("tenant-integration-stripe-test"));
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith("/tenants/me/integrations/stripe/test"),
    );
    await waitFor(() =>
      expect(mockToastSuccess).toHaveBeenCalled(),
    );
  });

  it("disconnect calls DELETE and refreshes the list", async () => {
    _asAdmin();
    _installListAndSchemasMock(() => _seedList([{
      provider_key: "stripe", connection_type: "oauth_stripe_connect",
      connected: true, last_4: "abcd",
      connected_account_id_masked: "acct_…1234",
      connected_status: "connected", error_log_count: 0,
    }]));
    mockDelete.mockResolvedValue({ removed: true, provider_key: "stripe" });
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe-disconnect")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("tenant-integration-stripe-disconnect"));
    // I1.7.c.2.followup — must confirm through the in-app modal now.
    await waitFor(() =>
      expect(screen.getByTestId("integrations-disconnect-confirm")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("integrations-disconnect-confirm"));
    await waitFor(() =>
      expect(mockDelete).toHaveBeenCalledWith("/tenants/me/integrations/stripe"),
    );
    await waitFor(() =>
      expect(mockToastSuccess).toHaveBeenCalled(),
    );
  });

  // I1.7.c.2.followup · Task A · Feb-2026 — Modal interaction tests.
  // Locks in that ``window.confirm`` is gone and the disconnect flow
  // is now a two-step "open modal → confirm/cancel" that browser-use
  // automation can drive by testid.
  describe("disconnect confirmation modal · Task A", () => {
    const _seedConnectedStripe = () => _seedList([{
      provider_key: "stripe", connection_type: "oauth_stripe_connect",
      connected: true, last_4: "abcd",
      connected_account_id_masked: "acct_…1234",
      connected_status: "connected", error_log_count: 0,
    }]);

    it("Stripe disconnect click opens the in-app modal (no window.confirm)", async () => {
      _asAdmin();
      _installListAndSchemasMock(_seedConnectedStripe);
      renderCard();
      await waitFor(() =>
        expect(screen.getByTestId("tenant-integration-stripe-disconnect")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("tenant-integration-stripe-disconnect"));
      await waitFor(() =>
        expect(screen.getByTestId("integrations-disconnect-confirm")).toBeTruthy(),
      );
      expect(screen.getByTestId("integrations-disconnect-cancel")).toBeTruthy();
      expect(mockDelete).not.toHaveBeenCalled();
    });

    it("Stripe modal · Confirm fires DELETE", async () => {
      _asAdmin();
      _installListAndSchemasMock(_seedConnectedStripe);
      mockDelete.mockResolvedValue({ removed: true, provider_key: "stripe" });
      renderCard();
      await waitFor(() =>
        expect(screen.getByTestId("tenant-integration-stripe-disconnect")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("tenant-integration-stripe-disconnect"));
      await waitFor(() =>
        expect(screen.getByTestId("integrations-disconnect-confirm")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("integrations-disconnect-confirm"));
      await waitFor(() =>
        expect(mockDelete).toHaveBeenCalledWith("/tenants/me/integrations/stripe"),
      );
    });

    it("Stripe modal · Cancel closes it and does NOT fire DELETE", async () => {
      _asAdmin();
      _installListAndSchemasMock(_seedConnectedStripe);
      renderCard();
      await waitFor(() =>
        expect(screen.getByTestId("tenant-integration-stripe-disconnect")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("tenant-integration-stripe-disconnect"));
      await waitFor(() =>
        expect(screen.getByTestId("integrations-disconnect-cancel")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("integrations-disconnect-cancel"));
      await waitFor(() =>
        expect(screen.queryByTestId("integrations-disconnect-confirm")).toBeNull(),
      );
      expect(mockDelete).not.toHaveBeenCalled();
    });
  });

  it("managers see the Stripe card but no write buttons", async () => {
    _asManager();
    _installListAndSchemasMock(() => _seedList());
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe")).toBeTruthy(),
    );
    expect(screen.queryByTestId("tenant-integration-stripe-connect")).toBeNull();
    expect(screen.queryByTestId("tenant-integration-stripe-test")).toBeNull();
    expect(screen.queryByTestId("tenant-integration-stripe-disconnect")).toBeNull();
  });
});
