/**
 * Phase P52 · Feb-2026 — Global Settings Default Language dropdown.
 *
 * Locks the BusinessSettings language picker slice (timezone
 * picker was pre-existing; user's Q1 held pending):
 *   1. Dropdown renders under settings-default-locale-select
 *      testid with exactly 3 options — en / es / fr.
 *   2. Each option carries its own settings-default-locale-option-
 *      <code> testid.
 *   3. Selecting an option fires PATCH /tenants/mine/settings with
 *      {default_locale: <code>}.
 *   4. On success, localStorage.tenant_default_locale is primed
 *      optimistically so the current-boot detector reflects the
 *      new value (auth.jsx still owns the authoritative write on
 *      the next /auth/me refresh).
 *   5. A ``tenant:settings-updated`` CustomEvent fires with the
 *      new locale in the detail payload — schedule + dashboard
 *      surfaces already listen for this event (P15).
 *
 * Mount pattern: proven-working for BusinessSettings (grep for the
 * shipped ``bs-tenant-timezone-picker`` mount tests uses the same
 * technique).  Mocks: @/api for network, sonner for toasts,
 * TimezoneSelect stub so we don't pull in the full curated-tz UI.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, act, fireEvent,
} from "@testing-library/react";

// ── Mocks ────────────────────────────────────────────────────────
const apiGet = vi.fn();
const apiPatch = vi.fn();
vi.mock("@/api", async () => {
  const actual = await vi.importActual("@/api");
  return {
    ...actual,
    api: {
      get: (...a) => apiGet(...a),
      patch: (...a) => apiPatch(...a),
      post: vi.fn().mockResolvedValue({}),
      del: vi.fn().mockResolvedValue({}),
    },
  };
});
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));
vi.mock("@/components/settings/TimezoneSelect", () => ({
  TimezoneSelect: ({ testid }) => (
    <div data-testid={testid || "bs-tenant-timezone-picker-stub"} />
  ),
}));
vi.mock("@/components/settings/PaymentProvidersCard", () => ({
  default: () => null,
}));

async function tick(n = 6) {
  await act(async () => {
    for (let i = 0; i < n; i += 1) await Promise.resolve();
  });
}


beforeEach(() => {
  apiGet.mockReset();
  apiPatch.mockReset();
  // Default responses — business-settings + tenants/mine/settings.
  apiGet.mockImplementation((url) => {
    if (url === "/tenants/mine/settings") {
      return Promise.resolve({
        timezone: "America/Phoenix",
        default_locale: "en",
      });
    }
    if (url === "/tenants/me/business-settings") {
      return Promise.resolve({
        stored: {}, effective: {},
      });
    }
    return Promise.resolve({});
  });
  apiPatch.mockResolvedValue({
    timezone: "America/Phoenix",
    default_locale: "es",
  });
  try { window.localStorage.removeItem("tenant_default_locale"); }
  catch { /* jsdom */ }
});


async function mount() {
  const { default: BusinessSettings } =
    await import("@/pages/settings/BusinessSettings");
  const utils = render(<BusinessSettings />);
  await tick();
  return utils;
}


describe("P52 · Global Settings · Default Language dropdown", () => {
  it("renders the dropdown with exactly three options (en / es / " +
     "fr) after the tenant document loads", async () => {
    const { unmount } = await mount();
    const select = screen.getByTestId("settings-default-locale-select");
    expect(select).toBeInTheDocument();
    const options = select.querySelectorAll("option");
    expect(options.length).toBe(3);
    expect(
      screen.getByTestId("settings-default-locale-option-en"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("settings-default-locale-option-es"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("settings-default-locale-option-fr"),
    ).toBeInTheDocument();
    unmount();
  });

  it("hydrates from the tenant document — landing on ``es`` " +
     "shows the ES option selected", async () => {
    apiGet.mockImplementation((url) => {
      if (url === "/tenants/mine/settings") {
        return Promise.resolve({
          timezone: "America/Phoenix",
          default_locale: "es",
        });
      }
      if (url === "/tenants/me/business-settings") {
        return Promise.resolve({ stored: {}, effective: {} });
      }
      return Promise.resolve({});
    });
    const { unmount } = await mount();
    const select = screen.getByTestId("settings-default-locale-select");
    expect(select.value).toBe("es");
    unmount();
  });

  it("selecting FR fires PATCH /tenants/mine/settings with " +
     "{default_locale: 'fr'} + primes " +
     "localStorage.tenant_default_locale + broadcasts the " +
     "tenant:settings-updated event", async () => {
    apiPatch.mockImplementation((url, body) => {
      expect(url).toBe("/tenants/mine/settings");
      expect(body).toEqual({ default_locale: "fr" });
      return Promise.resolve({
        timezone: "America/Phoenix", default_locale: "fr",
      });
    });
    let receivedEvent = null;
    const listener = (e) => { receivedEvent = e.detail; };
    window.addEventListener("tenant:settings-updated", listener);

    try {
      const { unmount } = await mount();
      const select = screen.getByTestId("settings-default-locale-select");

      await act(async () => {
        fireEvent.change(select, { target: { value: "fr" } });
      });
      await tick();

      // PATCH fired with the correct payload — assertion happens
      // inside the mockImplementation above.  Also verify the
      // localStorage prime + the event dispatch.
      expect(apiPatch).toHaveBeenCalledTimes(1);
      expect(window.localStorage.getItem("tenant_default_locale"))
        .toBe("fr");
      expect(receivedEvent).toEqual({ default_locale: "fr" });
      // Select shows the new value.
      expect(select.value).toBe("fr");

      unmount();
    } finally {
      window.removeEventListener("tenant:settings-updated", listener);
    }
  });

  it("dropdown constrains choices to en/es/fr - a user cannot " +
     "type-select an unsupported locale value (there is no such " +
     "<option>, so the browser rejects the assignment)", async () => {
    const { unmount } = await mount();
    const select = screen.getByTestId("settings-default-locale-select");
    // ``fireEvent.change`` with an unsupported value doesn't create
    // an option — the browser silently keeps the previous value.
    // We prove the shape by asserting the option count + values.
    const values = Array.from(select.querySelectorAll("option"))
      .map((o) => o.value)
      .sort();
    expect(values).toEqual(["en", "es", "fr"]);
    unmount();
  });
});
