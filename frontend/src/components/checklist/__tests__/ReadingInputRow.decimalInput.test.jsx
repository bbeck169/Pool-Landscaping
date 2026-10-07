/**
 * CHECKLIST-DECIMAL-INPUT-FIX · Feb-2026 — Pool Checklist
 * chemistry reading inputs must accept intermediate decimal
 * states ("7.", ".5") WITHOUT the trailing dot being stripped.
 *
 * Pre-fix, the input shipped ``type="number"`` which caused
 * Chrome/Firefox/iOS Safari to return ``e.target.value === ""``
 * for strings like "7." — HTML5 fails those intermediate states
 * per spec, so users were silently blanked out before they could
 * finish typing a decimal. Covers every chemistry reading key
 * (pH, chlorine, alkalinity, cyanuric_acid, salt) since they all
 * render through the same ``ReadingInputRow``.
 *
 * The fix switches to ``type="text"`` + ``inputMode="decimal"``
 * so the raw string flows through to ``_validateReading`` which
 * already handles the full set of intermediate states via the
 * ``/^\d*\.?\d*$/`` regex.
 */
import React, { useState } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor }
  from "@testing-library/react";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));

// Chemistry gate util is a bare-import in PoolChecklistForm — stub
// so this test doesn't drag the full chemistry pipeline.
vi.mock("@/utils/chemistryGate", () => ({
  CORE_KEYS: ["chlorine", "ph", "total_alkalinity", "cyanuric_acid"],
}));


import { ReadingInputRow }
  from "@/components/checklist/PoolChecklistForm";


afterEach(() => {
  cleanup();
});


function _mount({ testKey = "ph", initialValue = null,
                   locked = false, required = false } = {}) {
  const onChange = vi.fn();
  function Harness() {
    const [reading, setReading] = useState({
      name: testKey, value: initialValue, unit: "pH",
    });
    return (
      <ReadingInputRow
        testKey={testKey}
        reading={reading}
        previous={null}
        recent={[]}
        locked={locked}
        required={required}
        onChange={(v) => {
          onChange(v);
          setReading((r) => ({ ...r, value: v }));
        }}
      />
    );
  }
  render(<Harness />);
  return { onChange };
}


describe("ReadingInputRow · decimal input (CHECKLIST-DECIMAL-INPUT-FIX)",
         () => {
  it("input type is 'text' (not 'number') so intermediate decimal "
     + "states aren't stripped by the browser", () => {
    _mount({ testKey: "ph" });
    const input = screen.getByTestId("pool-reading-ph-input");
    expect(input.getAttribute("type")).toBe("text");
    expect(input.getAttribute("inputmode")).toBe("decimal");
  });

  it("typing '7' → '7.' → '7.4' preserves every keystroke (the "
     + "trailing-dot bug regression guard)", () => {
    _mount({ testKey: "ph" });
    const input = screen.getByTestId("pool-reading-ph-input");
    fireEvent.change(input, { target: { value: "7" } });
    expect(input.value).toBe("7");
    // The exact state that pre-fix got silently blanked by
    // ``type="number"`` → regression lock.
    fireEvent.change(input, { target: { value: "7." } });
    expect(input.value).toBe("7.");
    fireEvent.change(input, { target: { value: "7.4" } });
    expect(input.value).toBe("7.4");
  });

  it("blur with '7.4' commits numeric 7.4", () => {
    const { onChange } = _mount({ testKey: "ph" });
    const input = screen.getByTestId("pool-reading-ph-input");
    fireEvent.change(input, { target: { value: "7.4" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(7.4);
  });

  it("blur with trailing-dot '7.' commits numeric 7 (parseFloat "
     + "normalisation)", () => {
    const { onChange } = _mount({ testKey: "ph" });
    const input = screen.getByTestId("pool-reading-ph-input");
    fireEvent.change(input, { target: { value: "7." } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(7);
  });

  it("blur with leading-dot '.5' commits numeric 0.5", () => {
    const { onChange } = _mount({ testKey: "chlorine" });
    const input = screen.getByTestId("pool-reading-chlorine-input");
    fireEvent.change(input, { target: { value: ".5" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(0.5);
  });

  it("blur with empty string commits null (not-entered state)", () => {
    const { onChange } = _mount({ testKey: "ph", initialValue: 7.5 });
    const input = screen.getByTestId("pool-reading-ph-input");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("pasting letters 'abc' is rejected at keystroke, draft "
     + "stays empty", () => {
    _mount({ testKey: "ph" });
    const input = screen.getByTestId("pool-reading-ph-input");
    fireEvent.change(input, { target: { value: "abc" } });
    // Guard clause rejects — draft stays at the mount's initial "".
    expect(input.value).toBe("");
  });

  it("pasting '7.4.5' (two dots — invalid regex match) is rejected "
     + "at keystroke", () => {
    _mount({ testKey: "ph" });
    const input = screen.getByTestId("pool-reading-ph-input");
    fireEvent.change(input, { target: { value: "7.4" } });
    expect(input.value).toBe("7.4");
    // Simulate a second-dot paste that the regex rejects.
    fireEvent.change(input, { target: { value: "7.4.5" } });
    // Draft stays at the last-valid state ("7.4" from above).
    expect(input.value).toBe("7.4");
  });

  it("chlorine key accepts '2.75' end-to-end (parity with pH)",
    () => {
    const { onChange } = _mount({ testKey: "chlorine" });
    const input = screen.getByTestId("pool-reading-chlorine-input");
    fireEvent.change(input, { target: { value: "2" } });
    fireEvent.change(input, { target: { value: "2." } });
    fireEvent.change(input, { target: { value: "2.7" } });
    fireEvent.change(input, { target: { value: "2.75" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(2.75);
  });
});
