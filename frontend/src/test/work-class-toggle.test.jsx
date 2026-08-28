/**
 * Feb 2026 · Color-coded Service / Repair TYPE toggle.
 *
 * Locking specs:
 *   * Default value renders Service in cyan/pool-family with
 *     ``data-tone="pool"`` and Repair inactive.
 *   * Clicking Repair flips the selection AND swaps the active
 *     tone to amber.
 *   * Active color-family primary passes WCAG AA large-text contrast
 *     against white (≥ 3:1) — enforced via the shared
 *     ``getContrastRatio`` helper.
 *   * Data-testids stack — the shared component supports a
 *     ``testIdPrefix`` so JobNew (jf-work-class-*) and
 *     ScheduleJobEditModal (schedule-job-edit-work-class-*) each
 *     get a namespaced set.
 */
import React, { useState } from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import WorkClassToggle from "@/components/jobs/WorkClassToggle";
import { colors } from "@/theme";
import { getContrastRatio } from "@/utils/serviceLineTheme";


function Harness({ initial = "service", onChange, testIdPrefix = "jf-work-class" }) {
  const [value, setValue] = useState(initial);
  return (
    <WorkClassToggle
      value={value}
      onChange={(v) => {
        setValue(v);
        onChange?.(v);
      }}
      testIdPrefix={testIdPrefix}
    />
  );
}


// Small helper — pull an inline-style property in a way that works
// with both jsdom's kebab-case DOM and React's camelCase style prop.
function bgOf(el) {
  return (
    el.style.backgroundColor
    || el.style.getPropertyValue("background-color")
    || ""
  );
}


describe("WorkClassToggle · Service / Repair color-coded segmented control", () => {
  it("renders Service selected by default, in pool/cyan tone", () => {
    render(<Harness />);
    const service = screen.getByTestId("jf-work-class-service");
    const repair = screen.getByTestId("jf-work-class-repair");
    expect(service.getAttribute("data-selected")).toBe("1");
    expect(service.getAttribute("data-tone")).toBe("pool");
    expect(repair.getAttribute("data-selected")).toBe("0");
    expect(repair.getAttribute("data-tone")).toBe("amber");
  });

  it("clicking Repair flips selection to amber, Service goes inactive", () => {
    render(<Harness />);
    fireEvent.click(screen.getByTestId("jf-work-class-repair"));
    const service = screen.getByTestId("jf-work-class-service");
    const repair = screen.getByTestId("jf-work-class-repair");
    expect(repair.getAttribute("data-selected")).toBe("1");
    expect(service.getAttribute("data-selected")).toBe("0");
  });

  it("clicking back to Service returns to cyan", () => {
    render(<Harness initial="repair" />);
    fireEvent.click(screen.getByTestId("jf-work-class-service"));
    expect(screen.getByTestId("jf-work-class-service").getAttribute("data-selected"))
      .toBe("1");
    expect(screen.getByTestId("jf-work-class-repair").getAttribute("data-selected"))
      .toBe("0");
  });

  it("active Service uses colors.pool[600]; active Repair uses colors.accent.amber[600]", () => {
    render(<Harness initial="service" />);
    const service = screen.getByTestId("jf-work-class-service");
    // Active service background = pool[600] = #0891B2.
    // jsdom emits ``rgb(8, 145, 178)`` for the hex.
    const serviceBg = bgOf(service).toLowerCase().replace(/\s/g, "");
    expect(serviceBg).toBe("rgb(8,145,178)");   // colors.pool[600]

    // Flip to Repair — background swaps to amber[600] = #D97706.
    fireEvent.click(screen.getByTestId("jf-work-class-repair"));
    const repairBg = bgOf(screen.getByTestId("jf-work-class-repair"))
      .toLowerCase().replace(/\s/g, "");
    expect(repairBg).toBe("rgb(217,119,6)");     // colors.accent.amber[600]
  });

  it("white text on active background passes WCAG AA large-text contrast (≥ 3:1)", () => {
    const poolRatio = getContrastRatio(colors.pool[600], "#FFFFFF");
    const amberRatio = getContrastRatio(colors.accent.amber[600], "#FFFFFF");
    // AA large-text threshold is 3.0; both must clear it.
    expect(poolRatio).toBeGreaterThanOrEqual(3.0);
    expect(amberRatio).toBeGreaterThanOrEqual(3.0);
  });

  it("onChange fires with the new value on each click", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByTestId("jf-work-class-repair"));
    expect(onChange).toHaveBeenLastCalledWith("repair");
    fireEvent.click(screen.getByTestId("jf-work-class-service"));
    expect(onChange).toHaveBeenLastCalledWith("service");
  });

  it("testIdPrefix namespaces IDs — same component reusable on ScheduleJobEditModal", () => {
    render(<Harness testIdPrefix="schedule-job-edit-work-class" />);
    expect(
      screen.getByTestId("schedule-job-edit-work-class-service")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("schedule-job-edit-work-class-repair")
    ).toBeInTheDocument();
  });

  it("aria-checked + role=radio are wired for a11y", () => {
    render(<Harness />);
    const service = screen.getByTestId("jf-work-class-service");
    const repair = screen.getByTestId("jf-work-class-repair");
    expect(service.getAttribute("role")).toBe("radio");
    expect(service.getAttribute("aria-checked")).toBe("true");
    expect(repair.getAttribute("aria-checked")).toBe("false");
  });
});
