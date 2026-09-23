/**
 * Phase P39 · Feb-2026 — TenantIntegrationsCard telematics section tests.
 *
 * Seven scenarios per the P39 brief (5 original + 2 for Change 2):
 *   1. test_telematics_section_renders_two_provider_tabs
 *   2. test_webhook_url_field_shows_signed_url
 *   3. test_vehicle_link_add_calls_post
 *   4. test_vehicle_link_delete_calls_delete
 *   5. test_unmapped_vehicles_list_renders
 *   6. test_mgmt_table_shows_last_seen_and_unmapped_count
 *   7. test_backfill_checkbox_defaults_to_checked_and_sends_flag
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/* ── Hoisted mocks ─────────────────────────────────────────────── */

const _h = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPut: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...args) => _h.apiGet(...args),
    put: (...args) => _h.apiPut(...args),
    post: (...args) => _h.apiPost(...args),
    delete: (...args) => _h.apiDelete(...args),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...args) => _h.toastSuccess(...args),
    error: (...args) => _h.toastError(...args),
  },
}));

// Bypass clipboard access in jsdom.
vi.mock("@/theme", () => ({
  colors: {
    border: "#ddd", onSurface: "#111", onSurfaceSecondary: "#555",
    brand: "#00f", searchIcon: "#888", muted: "#999", destructive: "#DC2626",
  },
}));

/* ── Fixture payloads ──────────────────────────────────────────── */

const TELEMATICS_SCHEMAS = [
  {
    provider_key: "telematics_mojio",
    kind: "telematics",
    connection_type: "api_key",
    fields: [
      { name: "api_key", required: true, secret: true, label: "API key" },
      { name: "account_id", required: true, secret: false, label: "Account ID" },
      { name: "webhook_secret", required: true, secret: true, label: "Webhook secret" },
    ],
  },
  {
    provider_key: "telematics_geotab",
    kind: "telematics",
    connection_type: "api_key",
    fields: [
      { name: "api_key", required: true, secret: true, label: "API key" },
      { name: "account_id", required: true, secret: false, label: "Database name" },
      { name: "webhook_secret", required: true, secret: true, label: "Shared secret" },
      { name: "server_url", required: false, secret: false, label: "Server host" },
    ],
  },
];

const LINK_ROWS = [
  {
    id: "lk-1",
    tenant_id: "t-1",
    external_vehicle_id: "veh-A",
    technician_user_id: "u-1",
    created_at: "2026-02-01T00:00:00Z",
    updated_at: "2026-02-01T00:00:00Z",
    last_seen_at: "2026-02-16T09:00:00Z",
    unmapped_pings_count: 12,
  },
];

const UNMAPPED_ROWS = [
  {
    external_vehicle_id: "veh-Z",
    last_seen_at: "2026-02-16T10:30:00Z",
    unmapped_pings_count: 5,
  },
];

const TECHNICIANS = [{ id: "u-1", name: "Alice Tech" }];

function _installApiHandlers() {
  _h.apiGet.mockImplementation((path) => {
    if (path === "/tenants/me/integrations") {
      return Promise.resolve({ integrations: [], health: {} });
    }
    if (path === "/tenants/me/integrations/schemas") {
      return Promise.resolve({
        sms: [], email: [], ai: [], maps: [], calendars: [], payments: [],
        telematics: TELEMATICS_SCHEMAS,
      });
    }
    if (path === "/tenants/me/integrations/ai/usage") return Promise.resolve({ providers: [] });
    if (path === "/tenants/me/integrations/maps/usage") return Promise.resolve({ providers: [] });
    if (path === "/tenants/me/integrations/calendars/usage") return Promise.resolve({ providers: [], technicians: [] });
    if (path === "/tenants/me/integrations/payments/usage") return Promise.resolve({ providers: [] });
    if (path.startsWith("/users")) return Promise.resolve(TECHNICIANS);
    if (path === "/tenants/me/integrations/telematics/vehicle-links") {
      return Promise.resolve({ links: LINK_ROWS });
    }
    if (path === "/tenants/me/integrations/telematics/unmapped-vehicles") {
      return Promise.resolve({ vehicles: UNMAPPED_ROWS });
    }
    if (path.startsWith("/tenants/me/integrations/telematics/webhook-url")) {
      const u = new URL("http://x" + path);
      const prov = u.searchParams.get("provider") || "mojio";
      return Promise.resolve({
        provider: prov,
        provider_key: `telematics_${prov}`,
        url: `https://api.example.test/api/tenants/me/integrations/telematics_${prov}/webhook?tid=t-1&t=abc123`,
        origin_source: "env",
      });
    }
    return Promise.resolve({});
  });
  _h.apiPost.mockResolvedValue({
    link: { ...LINK_ROWS[0], id: "lk-new" },
    backfilled: 5,
  });
  _h.apiDelete.mockResolvedValue({ removed: true });
  _h.apiPut.mockResolvedValue({ saved: true });
}

/* ── Test helpers ──────────────────────────────────────────────── */

beforeEach(() => {
  vi.resetAllMocks();
  _installApiHandlers();
  try {
    window.localStorage.setItem("user", JSON.stringify({ id: "u-admin", role: "admin" }));
  } catch {}
});

afterEach(() => {
  try { window.localStorage.clear(); } catch {}
});

async function renderCard() {
  const { default: TenantIntegrationsCard } = await import(
    "@/components/settings/TenantIntegrationsCard"
  );
  return render(<TenantIntegrationsCard />);
}

/* ── Tests ─────────────────────────────────────────────────────── */

describe("P39 · TenantIntegrationsCard · Telematics section", () => {
  it("renders BOTH provider cards (Mojio + Geotab)", async () => {
    await renderCard();
    await waitFor(() => {
      expect(screen.getByTestId("tenant-integration-telematics_mojio")).toBeTruthy();
      expect(screen.getByTestId("tenant-integration-telematics_geotab")).toBeTruthy();
    });
  });

  it("shows the signed webhook URL from GET /webhook-url", async () => {
    await renderCard();
    await waitFor(() => {
      const el = screen.getByTestId("tenant-integration-telematics_mojio-webhook-url");
      expect(el.textContent).toMatch(/webhook\?tid=t-1&t=abc123/);
    });
  });

  it("POSTs to /vehicle-links when the operator adds a mapping", async () => {
    const user = userEvent.setup();
    await renderCard();
    await waitFor(() => {
      expect(screen.getByTestId("telematics-vehicle-link-add-input")).toBeTruthy();
    });
    await user.type(
      screen.getByTestId("telematics-vehicle-link-add-input"),
      "veh-NEW",
    );
    fireEvent.change(
      screen.getByTestId("telematics-vehicle-link-add-tech-select"),
      { target: { value: "u-1" } },
    );
    await user.click(screen.getByTestId("telematics-vehicle-link-add-submit"));
    await waitFor(() => {
      expect(_h.apiPost).toHaveBeenCalledWith(
        "/tenants/me/integrations/telematics/vehicle-links",
        expect.objectContaining({
          external_vehicle_id: "veh-NEW",
          technician_user_id: "u-1",
          backfill: true,
        }),
      );
    });
  });

  it("DELETEs to /vehicle-links/{id} when the operator clicks the trash icon", async () => {
    const user = userEvent.setup();
    await renderCard();
    await waitFor(() => {
      expect(screen.getByTestId("telematics-vehicle-link-lk-1-delete")).toBeTruthy();
    });
    await user.click(screen.getByTestId("telematics-vehicle-link-lk-1-delete"));
    await waitFor(() => {
      expect(_h.apiDelete).toHaveBeenCalledWith(
        "/tenants/me/integrations/telematics/vehicle-links/lk-1",
      );
    });
  });

  it("renders the unmapped-vehicles diagnostic list", async () => {
    await renderCard();
    await waitFor(() => {
      const el = screen.getByTestId("telematics-unmapped-veh-Z");
      expect(el.textContent).toMatch(/veh-Z/);
    });
  });

  it("Change 2 · shows last_seen_at + unmapped_pings_count on each mgmt-table row", async () => {
    await renderCard();
    await waitFor(() => {
      const row = screen.getByTestId("telematics-vehicle-link-lk-1");
      // Row text carries both the pings count AND some timestamp render.
      expect(row.textContent).toMatch(/12/);
      // The last_seen_at timestamp renders in the row somewhere.
      const lastSeen = screen.getByTestId("telematics-vehicle-link-lk-1-last-seen");
      expect(lastSeen.textContent).toBeTruthy();
    });
  });

  it("Change 2 · backfill checkbox defaults CHECKED and the flag propagates to POST", async () => {
    const user = userEvent.setup();
    await renderCard();
    await waitFor(() => {
      expect(screen.getByTestId("telematics-vehicle-link-add-backfill")).toBeTruthy();
    });
    const cb = screen.getByTestId("telematics-vehicle-link-add-backfill");
    expect(cb.checked).toBe(true);

    // Uncheck + submit → payload MUST carry backfill:false.
    await user.click(cb);
    expect(cb.checked).toBe(false);
    await user.type(
      screen.getByTestId("telematics-vehicle-link-add-input"),
      "veh-OFF",
    );
    fireEvent.change(
      screen.getByTestId("telematics-vehicle-link-add-tech-select"),
      { target: { value: "u-1" } },
    );
    await user.click(screen.getByTestId("telematics-vehicle-link-add-submit"));
    await waitFor(() => {
      expect(_h.apiPost).toHaveBeenCalledWith(
        "/tenants/me/integrations/telematics/vehicle-links",
        expect.objectContaining({
          external_vehicle_id: "veh-OFF",
          backfill: false,
        }),
      );
    });
  });
});
