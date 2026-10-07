/**
 * SALT-DECIMALS-FOLLOWUP · Feb-2026 — salt reading rule flipped
 * from ``decimals: 0`` (integer-only) → ``decimals: 1`` so field
 * techs can log tenths of a ppm (common on salt-cell readings
 * like ``3450.5``).  Paired with CHECKLIST-DECIMAL-INPUT-FIX
 * which already fixed the keystroke-level ``type="number"``
 * trailing-dot bug; this ticket closes the on-blur validation
 * gap so the ``.5`` actually commits.
 */
import React, { useState } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));

vi.mock("@/utils/chemistryGate", () => ({
  CORE_KEYS: ["chlorine", "ph", "total_alkalinity", "cyanuric_acid"],
}));


import { ReadingInputRow }
  from "@/components/checklist/PoolChecklistForm";


afterEach(() => cleanup());


function _mount({ initialValue = null } = {}) {
  const onChange = vi.fn();
  function Harness() {
    const [reading, setReading] = useState({
      name: "salt", value: initialValue, unit: "ppm",
    });
    return (
      <ReadingInputRow
        testKey="salt"
        reading={reading}
        previous={null}
        recent={[]}
        locked={false}
        required={false}
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


describe("ReadingInputRow · salt accepts one decimal "
         + "(SALT-DECIMALS-FOLLOWUP)", () => {
  it("entering '3450.5' commits 3450.5 (NOT null, NOT rejected "
     + "as out-of-decimals)", () => {
    const { onChange } = _mount();
    const input = screen.getByTestId("pool-reading-salt-input");
    fireEvent.change(input, { target: { value: "3450.5" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(3450.5);
  });

  it("entering an integer '3450' still commits 3450 (no "
     + "forced-decimal regression)", () => {
    const { onChange } = _mount();
    const input = screen.getByTestId("pool-reading-salt-input");
    fireEvent.change(input, { target: { value: "3450" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(3450);
  });

  it("entering two decimals '3450.55' is REJECTED (decimals=1 "
     + "cap enforced — guards against float noise)", () => {
    const { onChange } = _mount();
    const input = screen.getByTestId("pool-reading-salt-input");
    fireEvent.change(input, { target: { value: "3450.55" } });
    fireEvent.blur(input);
    // Invalid → commit short-circuits, onChange NOT called with
    // a numeric value.  Empty-string path IS allowed to call
    // onChange(null); but a non-empty invalid input should NOT.
    const numericCalls = onChange.mock.calls.filter(
      ([v]) => typeof v === "number",
    );
    expect(numericCalls).toHaveLength(0);
  });
});
