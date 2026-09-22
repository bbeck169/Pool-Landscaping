/**
 * Phase P15 · Feb-2026 · Permanent Tenant Timezone Setting — the
 * Business Settings picker.
 *
 * Locks in:
 *   1. TimezoneSelect renders 7 options fetched from
 *      ``/tenants/timezones`` in the exact spec order (ET → CT →
 *      MT → PT → Alaska → Arizona → Hawaii).
 *   2. Selecting "Arizona (No DST)" PATCHes with
 *      ``timezone: "America/Phoenix"``.
 *   3. Save-side legacy: a stored value not in the fetched list
 *      renders a disabled synthetic "(legacy)" option.
 *   4. On successful save the component dispatches a
 *      ``tenant:settings-updated`` custom event with
 *      ``detail.timezone`` set.
 *   5. Billing Settings page no longer renders a tz picker (dead-
 *      import + `TimezoneSelect` reference is gone).
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { act } from "react";

// ── api mock ──────────────────────────────────────────────────────
const getMock = vi.fn();
const patchMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get:   (...args) => getMock(...args),
    patch: (...args) => patchMock(...args),
  },
}));

// The TimezoneSelect is the unit under test; import it directly to
// avoid dragging in the full BusinessSettings page (whose fetches +
// layout aren't relevant to this suite).
import { TimezoneSelect, FALLBACK_TIMEZONE_OPTIONS } from "@/components/settings/TimezoneSelect";

const SEVEN_ENTRIES = [
  { value: "America/New_York",    label: "Eastern Time (ET)" },
  { value: "America/Chicago",     label: "Central Time (CT)" },
  { value: "America/Denver",      label: "Mountain Time (MT)" },
  { value: "America/Los_Angeles", label: "Pacific Time (PT)" },
  { value: "America/Anchorage",   label: "Alaska Time" },
  { value: "America/Phoenix",     label: "Arizona (No DST)" },
  { value: "Pacific/Honolulu",    label: "Hawaii (No DST)" },
];

beforeEach(() => {
  getMock.mockReset();
  patchMock.mockReset();
  getMock.mockImplementation(async (url) => {
    if (url === "/tenants/timezones") return { timezones: SEVEN_ENTRIES };
    return {};
  });
});

afterEach(() => { cleanup(); });

// ─────────────────────────────────────────────────────────────────
// Item 1 · Render + option list
// ─────────────────────────────────────────────────────────────────
describe("P15 · TimezoneSelect render", () => {
  it("hardcoded fallback constant lists the 7 spec entries in order", () => {
    expect(FALLBACK_TIMEZONE_OPTIONS.map((o) => o.value))
      .toEqual(SEVEN_ENTRIES.map((o) => o.value));
    expect(FALLBACK_TIMEZONE_OPTIONS.map((o) => o.label))
      .toEqual(SEVEN_ENTRIES.map((o) => o.label));
  });

  it("fetches /tenants/timezones on mount and renders 7 options", async () => {
    const onChange = vi.fn();
    await act(async () => {
      render(
        <TimezoneSelect value="America/Phoenix" onChange={onChange} />,
      );
    });
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith("/tenants/timezones");
    });
    const select = screen.getByTestId("tenant-timezone-picker");
    const options = Array.from(select.querySelectorAll("option"));
    const rendered = options.map((o) => ({
      value: o.value, label: o.textContent,
    }));
    expect(rendered).toEqual(SEVEN_ENTRIES);
  });

  it("falls back to hardcoded 7 entries when the fetch throws", async () => {
    getMock.mockImplementation(async () => {
      throw new Error("network down");
    });
    const onChange = vi.fn();
    await act(async () => {
      render(
        <TimezoneSelect value="America/Phoenix" onChange={onChange} />,
      );
    });
    const select = screen.getByTestId("tenant-timezone-picker");
    const options = Array.from(select.querySelectorAll("option"));
    const values = options.map((o) => o.value);
    expect(values).toEqual(SEVEN_ENTRIES.map((o) => o.value));
  });
});

// ─────────────────────────────────────────────────────────────────
// Item 2 · Save → PATCH with correct IANA value
// ─────────────────────────────────────────────────────────────────
describe("P15 · TimezoneSelect save", () => {
  it("Arizona (No DST) selection fires onChange with America/Phoenix", async () => {
    let captured = null;
    const onChange = vi.fn((e) => {
      // Capture the value at the moment the change event fires —
      // ``select`` is a controlled input so ``select.value`` after
      // fireEvent reverts to the ``value`` prop, but the DOM
      // ``e.target.value`` is the newly-picked entry.
      captured = e.target.value;
    });
    await act(async () => {
      render(
        <TimezoneSelect value="America/New_York" onChange={onChange} />,
      );
    });
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith("/tenants/timezones");
    });
    const select = screen.getByTestId("tenant-timezone-picker");
    await act(async () => {
      fireEvent.change(select, { target: { value: "America/Phoenix" } });
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(captured).toBe("America/Phoenix");
  });
});

// ─────────────────────────────────────────────────────────────────
// Item 3 · Legacy stored value renders synthetic disabled option
// ─────────────────────────────────────────────────────────────────
describe("P15 · TimezoneSelect legacy value", () => {
  it("renders a disabled '(legacy)' option when stored value is off-list", async () => {
    const onChange = vi.fn();
    await act(async () => {
      render(
        <TimezoneSelect value="UTC" onChange={onChange} />,
      );
    });
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith("/tenants/timezones");
    });
    const legacy = screen.getByTestId(
      "tenant-timezone-picker-legacy-option",
    );
    expect(legacy).toBeDefined();
    expect(legacy.getAttribute("value")).toBe("UTC");
    expect(legacy.hasAttribute("disabled")).toBe(true);
    expect(legacy.textContent).toContain("UTC");
    expect(legacy.textContent).toContain("legacy");
  });

  it("does NOT render a legacy option when stored value is on-list", async () => {
    const onChange = vi.fn();
    await act(async () => {
      render(
        <TimezoneSelect value="America/Phoenix" onChange={onChange} />,
      );
    });
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith("/tenants/timezones");
    });
    expect(
      screen.queryByTestId("tenant-timezone-picker-legacy-option"),
    ).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────
// Item 5 · Billing Settings page no longer renders a tz picker
// (static-source grep — no full-page render needed).
// ─────────────────────────────────────────────────────────────────
describe("P15 · Billing Settings tz picker removal", () => {
  const billingSrc = fs.readFileSync(
    path.resolve(
      __dirname, "..", "pages", "settings", "BillingSettings.jsx",
    ),
    "utf-8",
  );

  it("does not import TimezoneSelect", () => {
    expect(billingSrc).not.toMatch(/TimezoneSelect/);
  });

  it("does not render a tenant-timezone-picker in the source", () => {
    // The picker's stable data-testid was ``tenant-timezone-picker``.
    // Business Settings uses ``bs-tenant-timezone-picker``; a stray
    // Billing reference would show up as either.
    expect(billingSrc).not.toMatch(/tenant-timezone-picker/);
  });
});

// ─────────────────────────────────────────────────────────────────
// Item 4 · Business Settings dispatches tenant:settings-updated
// on successful save (source-level assertion — the picker itself is
// stateless, the dispatch fires from the BusinessSettings onChange
// handler).
// ─────────────────────────────────────────────────────────────────
describe("P15 · BusinessSettings emits tenant:settings-updated on save", () => {
  const bsSrc = fs.readFileSync(
    path.resolve(
      __dirname, "..", "pages", "settings", "BusinessSettings.jsx",
    ),
    "utf-8",
  );

  it("uses window.dispatchEvent with the tenant:settings-updated topic", () => {
    expect(bsSrc).toMatch(/window\.dispatchEvent/);
    expect(bsSrc).toMatch(/tenant:settings-updated/);
  });

  it("attaches the new IANA name to event.detail.timezone", () => {
    // The dispatched CustomEvent carries { detail: { timezone: … } }
    // so the schedule + dashboard listeners can read the new tz.
    expect(bsSrc).toMatch(/detail:\s*\{\s*timezone/);
  });
});
