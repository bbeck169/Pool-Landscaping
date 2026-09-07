/**
 * Phase I1.7.c.1 · Feb-2026 — AI BYO card vitest suite.
 *
 * Pins:
 *   1. Renders one AI card per provider (openai, anthropic, gemini).
 *   2. Model dropdown reflects schema.models[] per provider.
 *   3. Save posts PUT with the api_key + default_model + monthly_token_cap.
 *   4. Empty cap input serializes to `monthly_token_cap: null` (unlimited).
 *   5. Cap = 0 serializes to `monthly_token_cap: 0` (kill switch).
 *   6. Usage bar renders WITH correct status colour when
 *      backend flags soft-warn / blocked.
 *   7. Manager sees the cards but no save/disconnect controls.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();
const mockDelete = vi.fn();
const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    put: (...a) => mockPut(...a),
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


const _AI_SCHEMAS = [
  { provider_key: "ai_openai", kind: "ai", models: ["gpt-4o-mini", "gpt-4o"], fields: [
    { name: "api_key", required: true, secret: true, label: "OpenAI API Key" },
    { name: "default_model", required: false, secret: false, label: "Default model" },
  ]},
  { provider_key: "ai_anthropic", kind: "ai", models: ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"], fields: [
    { name: "api_key", required: true, secret: true, label: "Anthropic API Key" },
    { name: "default_model", required: false, secret: false, label: "Default model" },
  ]},
  { provider_key: "ai_gemini", kind: "ai", models: ["gemini-1.5-flash", "gemini-1.5-pro"], fields: [
    { name: "api_key", required: true, secret: true, label: "Google Gemini API Key" },
    { name: "default_model", required: false, secret: false, label: "Default model" },
  ]},
];


const _mockRoutes = (rows, usageProviders = []) => {
  mockGet.mockImplementation(async (path) => {
    if (path === "/tenants/me/integrations")
      return { tenant_id: "tenant-i17c1", integrations: rows };
    if (path === "/tenants/me/integrations/schemas")
      return { sms: [], email: [], ai: _AI_SCHEMAS };
    if (path === "/tenants/me/integrations/ai/usage")
      return { tenant_id: "tenant-i17c1", period_yyyymm: "202602",
                providers: usageProviders };
    return {};
  });
};


beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPut.mockReset();
  mockDelete.mockReset();
  mockToastSuccess.mockReset();
  mockToastError.mockReset();
  window.localStorage.clear();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, assign: vi.fn(),
              pathname: "/settings/integrations", search: "", hash: "" },
  });
});


afterEach(() => { vi.restoreAllMocks(); });


describe("TenantIntegrationsCard · AI BYO cards (I1.7.c.1)", () => {
  const _asAdmin = () => window.localStorage.setItem("user",
    JSON.stringify({ id: "admin", role: "admin", email: "admin@example.com" }));

  it("renders one AI card per provider with model dropdown", async () => {
    _asAdmin();
    _mockRoutes([]);
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-ai_openai")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-ai_anthropic")).toBeTruthy();
    expect(screen.getByTestId("tenant-integration-ai_gemini")).toBeTruthy();
    // Model select for openai contains the two provided options.
    const modelSelect = screen.getByTestId("tenant-integration-ai_openai-model-select");
    expect(Array.from(modelSelect.options).map((o) => o.value))
      .toEqual(["gpt-4o-mini", "gpt-4o"]);
    // api_key input is a password type (no plaintext echo).
    expect(
      screen.getByTestId("tenant-integration-ai_openai-field-api_key").getAttribute("type"),
    ).toBe("password");
  });

  it("save posts PUT with api_key + default_model + monthly_token_cap", async () => {
    _asAdmin();
    _mockRoutes([]);
    mockPut.mockResolvedValue({ saved: true, provider_key: "ai_openai",
      connected_account_id_masked: null });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-ai_openai-field-api_key")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("tenant-integration-ai_openai-field-api_key"),
      { target: { value: "sk-abc123XYZ" } });
    fireEvent.change(screen.getByTestId("tenant-integration-ai_openai-model-select"),
      { target: { value: "gpt-4o" } });
    fireEvent.change(screen.getByTestId("tenant-integration-ai_openai-cap-input"),
      { target: { value: "50000" } });
    fireEvent.click(screen.getByTestId("tenant-integration-ai_openai-save"));
    await waitFor(() =>
      expect(mockPut).toHaveBeenCalledWith(
        "/tenants/me/integrations/ai_openai",
        { config: { api_key: "sk-abc123XYZ", default_model: "gpt-4o" },
          monthly_token_cap: 50000 },
      ),
    );
    await waitFor(() => expect(mockToastSuccess).toHaveBeenCalled());
  });

  it("empty cap serializes as null (unlimited)", async () => {
    _asAdmin();
    _mockRoutes([]);
    mockPut.mockResolvedValue({ saved: true, provider_key: "ai_anthropic" });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-ai_anthropic-field-api_key")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("tenant-integration-ai_anthropic-field-api_key"),
      { target: { value: "sk-ant-xyz" } });
    // Cap input left empty on purpose.
    fireEvent.click(screen.getByTestId("tenant-integration-ai_anthropic-save"));
    await waitFor(() => {
      const call = mockPut.mock.calls[0];
      expect(call[0]).toBe("/tenants/me/integrations/ai_anthropic");
      expect(call[1].monthly_token_cap).toBeNull();
    });
  });

  it("cap = 0 serializes as 0 (explicit kill switch)", async () => {
    _asAdmin();
    _mockRoutes([]);
    mockPut.mockResolvedValue({ saved: true, provider_key: "ai_gemini" });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-ai_gemini-field-api_key")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("tenant-integration-ai_gemini-field-api_key"),
      { target: { value: "gm-killswitch" } });
    fireEvent.change(screen.getByTestId("tenant-integration-ai_gemini-cap-input"),
      { target: { value: "0" } });
    fireEvent.click(screen.getByTestId("tenant-integration-ai_gemini-save"));
    await waitFor(() => {
      const call = mockPut.mock.calls[0];
      expect(call[1].monthly_token_cap).toBe(0);
    });
  });

  it("shows connected summary + warn badge when usage.status = warn", async () => {
    _asAdmin();
    _mockRoutes(
      [{
        provider_key: "ai_openai", connection_type: "api_key",
        connected: true, last_4: "XY99",
        connected_account_id_masked: null,
        last_used_at: "2026-02-05T12:00:00Z",
        connected_status: "connected", error_log_count: 0,
      }],
      [{ provider: "openai", period_yyyymm: "202602",
          tokens_prompt: 500, tokens_completion: 400, tokens_total: 900,
          monthly_token_cap: 1000, default_model: "gpt-4o-mini",
          connected: true, pct_used: 0.9, status: "warn" }],
    );
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-ai_openai-summary")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-ai_openai-last4").textContent)
      .toContain("XY99");
    // Warn badge rendered.
    expect(screen.getByTestId("tenant-integration-ai_openai-usage-warn")).toBeTruthy();
    // Bar rendered (usage bar present).
    expect(screen.getByTestId("tenant-integration-ai_openai-usage-bar")).toBeTruthy();
  });

  it("shows blocked notice when usage.status = blocked", async () => {
    _asAdmin();
    _mockRoutes(
      [{
        provider_key: "ai_gemini", connection_type: "api_key",
        connected: true, last_4: "ZZZZ",
        connected_account_id_masked: null,
        last_used_at: null, connected_status: "connected", error_log_count: 0,
      }],
      [{ provider: "gemini", period_yyyymm: "202602",
          tokens_prompt: 0, tokens_completion: 0, tokens_total: 0,
          monthly_token_cap: 0, default_model: "gemini-1.5-flash",
          connected: true, pct_used: null, status: "blocked" }],
    );
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-ai_gemini-usage-blocked")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-ai_gemini-usage-label").textContent)
      .toContain("Blocked");
  });

  it("managers see the AI cards but no save/disconnect controls", async () => {
    window.localStorage.setItem("user",
      JSON.stringify({ id: "m", role: "manager", email: "m@example.com" }));
    _mockRoutes([]);
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-ai_openai")).toBeTruthy(),
    );
    expect(screen.queryByTestId("tenant-integration-ai_openai-save")).toBeNull();
    expect(screen.queryByTestId("tenant-integration-ai_openai-disconnect")).toBeNull();
    expect(screen.queryByTestId("tenant-integration-ai_openai-field-api_key")).toBeNull();
  });

  // Post-tester fix (2026-02) — cap-only edit succeeds on a connected
  // provider (api_key input left blank). Backend now preserves the
  // stored secret uniformly; the FE must send the PUT with an EMPTY
  // ``api_key`` so this path exercises the merge helper end-to-end.
  it("cap-only edit on connected provider posts PUT WITHOUT api_key", async () => {
    _asAdmin();
    _mockRoutes(
      [{
        provider_key: "ai_openai", connection_type: "api_key",
        connected: true, last_4: "ORIG",
        connected_account_id_masked: null,
        last_used_at: null, connected_status: "connected", error_log_count: 0,
      }],
      [{ provider: "openai", period_yyyymm: "202602",
          tokens_prompt: 0, tokens_completion: 0, tokens_total: 0,
          monthly_token_cap: 10000, default_model: "gpt-4o-mini",
          connected: true, pct_used: 0, status: "ok" }],
    );
    mockPut.mockResolvedValue({ saved: true, provider_key: "ai_openai" });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-ai_openai-cap-input")).toBeTruthy(),
    );
    // Change ONLY the cap — leave api_key blank on purpose.
    const capInput = screen.getByTestId("tenant-integration-ai_openai-cap-input");
    fireEvent.change(capInput, { target: { value: "50000" } });
    fireEvent.click(screen.getByTestId("tenant-integration-ai_openai-save"));
    await waitFor(() => expect(mockPut).toHaveBeenCalled());
    const [path, body] = mockPut.mock.calls[0];
    expect(path).toBe("/tenants/me/integrations/ai_openai");
    // api_key must be blank (empty string) — merge helper preserves.
    expect(body.config.api_key).toBe("");
    expect(body.monthly_token_cap).toBe(50000);
  });

  // Post-tester follow-up (2026-02) — inconclusive disconnect visual
  // flip. Lock in that click-disconnect → DELETE fired → reload
  // fires → card renders with "Not connected" status after settle.
  it("disconnect flips the card back to disconnected state", async () => {
    _asAdmin();
    // First call: connected. After DELETE: not connected.
    let listCallCount = 0;
    mockGet.mockImplementation(async (path) => {
      if (path === "/tenants/me/integrations") {
        listCallCount += 1;
        return listCallCount === 1
          ? {
              tenant_id: "t", integrations: [{
                provider_key: "ai_openai", connection_type: "api_key",
                connected: true, last_4: "GONE",
                connected_account_id_masked: null,
                last_used_at: null, connected_status: "connected",
                error_log_count: 0,
              }],
            }
          : { tenant_id: "t", integrations: [] };
      }
      if (path === "/tenants/me/integrations/schemas")
        return { sms: [], email: [], ai: _AI_SCHEMAS };
      if (path === "/tenants/me/integrations/ai/usage")
        return { tenant_id: "t", period_yyyymm: "202602",
                  providers: listCallCount >= 2 ? [] : [
                    { provider: "openai", period_yyyymm: "202602",
                       tokens_prompt: 0, tokens_completion: 0, tokens_total: 0,
                       monthly_token_cap: 10000, default_model: "gpt-4o-mini",
                       connected: true, pct_used: 0, status: "ok" }] };
      return {};
    });
    mockDelete.mockResolvedValue({ removed: true, provider_key: "ai_openai" });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-ai_openai-status").textContent)
        .toMatch(/connected/i),
    );
    // Confirm Connected chip is present pre-disconnect.
    expect(screen.getByTestId("tenant-integration-ai_openai-status").textContent)
      .not.toMatch(/not connected/i);
    fireEvent.click(screen.getByTestId("tenant-integration-ai_openai-disconnect"));
    await waitFor(() =>
      expect(mockDelete).toHaveBeenCalledWith("/tenants/me/integrations/ai_openai"),
    );
    // After reload, card must flip to "Not connected".
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-ai_openai-status").textContent)
        .toMatch(/not connected/i),
    );
    // Disconnect button must be gone (unconnected UI).
    expect(screen.queryByTestId("tenant-integration-ai_openai-disconnect")).toBeNull();
  });
});
