/**
 * Feb-2026 · Timezone Finalization — TimezoneSelect shared component test.
 *
 * Confirms:
 *   1. Option list is exactly the 6 canonical zones (5 US + UTC).
 *   2. Value prop drives the selected option.
 *   3. onChange fires with the raw event so callers can PATCH the tenant.
 *   4. data-testid is stable at ``tenant-timezone-picker`` (default).
 *   5. Disabled prop dims + disables the select.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { TimezoneSelect, TIMEZONE_OPTIONS } from
  "@/components/settings/TimezoneSelect";


describe("TimezoneSelect (shared)", () => {
  it("renders exactly the canonical 6-option list", () => {
    const { getByTestId } = render(
      <TimezoneSelect value="America/Phoenix" onChange={() => {}} />,
    );
    const sel = getByTestId("tenant-timezone-picker");
    const opts = sel.querySelectorAll("option");
    expect(opts.length).toBe(6);
    const values = Array.from(opts).map((o) => o.value);
    expect(values).toEqual([
      "America/Phoenix", "America/Los_Angeles", "America/Denver",
      "America/Chicago", "America/New_York", "UTC",
    ]);
  });

  it("TIMEZONE_OPTIONS export is frozen and canonical", () => {
    expect(TIMEZONE_OPTIONS.map((o) => o.value)).toEqual([
      "America/Phoenix", "America/Los_Angeles", "America/Denver",
      "America/Chicago", "America/New_York", "UTC",
    ]);
    expect(Object.isFrozen(TIMEZONE_OPTIONS)).toBe(true);
  });

  it("value prop drives the initial selection", () => {
    const { getByTestId } = render(
      <TimezoneSelect value="America/New_York" onChange={() => {}} />,
    );
    const sel = getByTestId("tenant-timezone-picker");
    expect(sel.value).toBe("America/New_York");
  });

  it("onChange fires when the user picks a different zone", () => {
    let capturedValue = null;
    const onChange = vi.fn((e) => { capturedValue = e.target.value; });
    const { getByTestId } = render(
      <TimezoneSelect value="America/Phoenix" onChange={onChange} />,
    );
    fireEvent.change(getByTestId("tenant-timezone-picker"),
                       { target: { value: "America/Los_Angeles" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    // Read the value captured at the moment onChange fired — the
    // synthetic event pool releases target.value after the handler
    // returns, so we capture it inline.
    expect(capturedValue).toBe("America/Los_Angeles");
  });

  it("disabled prop dims + disables the select", () => {
    const { getByTestId } = render(
      <TimezoneSelect value="UTC" onChange={() => {}} disabled />,
    );
    const sel = getByTestId("tenant-timezone-picker");
    expect(sel.disabled).toBe(true);
    expect(sel.style.opacity).toBe("0.6");
  });

  it("accepts a custom testid so a page hosting multiple pickers can disambiguate", () => {
    const { getByTestId, queryByTestId } = render(
      <TimezoneSelect value="UTC" onChange={() => {}} testid="my-custom-picker" />,
    );
    expect(getByTestId("my-custom-picker")).toBeTruthy();
    expect(queryByTestId("tenant-timezone-picker")).toBeNull();
  });

  it("nullish value falls back to America/Phoenix as the initial selection", () => {
    const { getByTestId } = render(
      <TimezoneSelect value={null} onChange={() => {}} />,
    );
    expect(getByTestId("tenant-timezone-picker").value).toBe("America/Phoenix");
  });
});
