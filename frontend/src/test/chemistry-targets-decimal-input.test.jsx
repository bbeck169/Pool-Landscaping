/**
 * CHECKLIST-DECIMAL-INPUT-FIX · ChemistryConfigurationSettings sweep
 * · Feb-2026 — tenant admins editing per-chemistry target ranges
 * (pH 7.2–7.8, alkalinity 80–120, etc.) in the Chemistry
 * Configuration settings tab previously could not type decimal
 * values into either the Min or Max input: both rendered
 * ``type="number"`` + raw ``onChange(e.target.value)``, so the
 * browser blanked ``"7."`` before the user could finish typing
 * ``"7.4"``.
 *
 * Fix mirrors ``CustomerChemistry`` / ``PoolCalculators`` — switch
 * to ``type="text"`` + ``inputMode="decimal"`` + keystroke regex
 * guard (``/^\d*\.?\d*$/`` — positive-only because chemistry
 * targets are physical readings), preserve live-string state so
 * the parent's ``dirty`` flag and the Save button enablement
 * continue to work per-keystroke.
 *
 * The regression test mounts the real settings component with an
 * admin ``useAuth`` mock + a stubbed API that returns the
 * canonical shape of ``/tenants/mine/settings/chemistry`` so the
 * inputs render.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u1", name: "Admin" } }),
}));

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (p) => {
      if (p === "/tenants/mine/settings/chemistry") {
        // Return a canonical shape so Target Ranges renders rows.
        return {
          targets: {
            chlorine:        { min: 1,  max: 3,  unit: "ppm" },
            ph:              { min: 7.2, max: 7.8, unit: "pH" },
            alkalinity:      { min: 80, max: 120, unit: "ppm" },
            cyanuric_acid:   { min: 30, max: 50,  unit: "ppm" },
            calcium_hardness:{ min: 200, max: 400, unit: "ppm" },
            salt:            { min: 2700, max: 3400, unit: "ppm" },
          },
          outer_bounds: {
            chlorine:        [0, 10],
            ph:              [6, 8.5],
            alkalinity:      [0, 240],
            cyanuric_acid:   [0, 150],
            calcium_hardness:[0, 1000],
            salt:            [0, 6000],
          },
          gate_mode: "strict",
        };
      }
      return {};
    }),
    patch: vi.fn(async () => ({ ok: true })),
    post:  vi.fn(async () => ({ ok: true })),
  },
  TOKEN_KEY: "token",
}));


import ChemistryConfigurationSettings
  from "@/pages/settings/ChemistryConfigurationSettings.jsx";


afterEach(() => cleanup());


async function _mount() {
  render(<ChemistryConfigurationSettings />);
  // Wait for the admin-gated card body to appear (``cfg`` populates
  // via the mocked ``api.get`` on mount).
  await waitFor(() =>
    expect(screen.getByTestId("chemistry-targets-section"))
      .toBeInTheDocument(),
  );
}


describe("ChemistryConfigurationSettings · target min/max · "
         + "decimal keystroke-safe", () => {
  it("chem-target-min-ph (pH min) keeps a trailing dot in state "
     + "(regression lock — pre-fix this was '' because type=number "
     + "ate the invalid intermediate HTML5 number literal)",
    async () => {
      await _mount();
      const input = screen.getByTestId("chem-target-min-ph");
      expect(input.getAttribute("type")).toBe("text");
      expect(input.getAttribute("inputmode")).toBe("decimal");

      // Simulate the user clearing the prefilled 7.2 and retyping.
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.change(input, { target: { value: "7" } });
      expect(input.value).toBe("7");
      fireEvent.change(input, { target: { value: "7." } });
      expect(input.value).toBe("7.");
      fireEvent.change(input, { target: { value: "7.4" } });
      expect(input.value).toBe("7.4");
    });

  it("chem-target-max-ph (pH max) keeps a trailing dot in state",
    async () => {
      await _mount();
      const input = screen.getByTestId("chem-target-max-ph");
      expect(input.getAttribute("type")).toBe("text");
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.change(input, { target: { value: "7" } });
      fireEvent.change(input, { target: { value: "7." } });
      expect(input.value).toBe("7.");
      fireEvent.change(input, { target: { value: "7.6" } });
      expect(input.value).toBe("7.6");
    });

  it("chem-target-min-alkalinity (alkalinity min) keeps a trailing dot",
    async () => {
      await _mount();
      const input = screen.getByTestId("chem-target-min-alkalinity");
      expect(input.getAttribute("type")).toBe("text");
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.change(input, { target: { value: "80" } });
      fireEvent.change(input, { target: { value: "80." } });
      expect(input.value).toBe("80.");
      fireEvent.change(input, { target: { value: "80.5" } });
      expect(input.value).toBe("80.5");
    });

  it("chem-target-max-alkalinity (alkalinity max) rejects a letter "
     + "paste at keystroke (regex guard)", async () => {
      await _mount();
      const input = screen.getByTestId("chem-target-max-alkalinity");
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.change(input, { target: { value: "120" } });
      expect(input.value).toBe("120");
      fireEvent.change(input, { target: { value: "120a" } });
      // Pre-fix the number input would have let the browser silently
      // drop the ``a``. Post-fix the regex guard also drops it, but
      // via our own code path — ``input.value`` holds at ``"120"``.
      expect(input.value).toBe("120");
    });

  it("chem-target-min-salt accepts a leading-dot entry ('.5' as "
     + "tenths of a ppm — matches the SALT-DECIMALS-FOLLOWUP contract)",
    async () => {
      await _mount();
      const input = screen.getByTestId("chem-target-min-salt");
      expect(input.getAttribute("type")).toBe("text");
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.change(input, { target: { value: "." } });
      expect(input.value).toBe(".");
      fireEvent.change(input, { target: { value: ".5" } });
      expect(input.value).toBe(".5");
    });
});
