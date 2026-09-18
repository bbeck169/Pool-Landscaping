/**
 * Sprint 3b · Feb-2026 · Chemistry Configuration UI Vitest coverage.
 *
 * Locks the acceptance behaviour on the new SettingsHub tab:
 *   1. Non-admins see the "Admin access required" card, no editors.
 *   2. Admins load defaults from GET and render the 6 target rows +
 *      the 3 gate-mode radios.
 *   3. Editing min/max and clicking Save fires a targets PATCH.
 *   4. Clicking a gate-mode radio fires a gate_mode PATCH.
 *   5. Expanding the Dosing Formulas section fetches formulas.
 *   6. The cheat-sheet renders; "Test formula" hits /dose/preview.
 *   7. Formula save invokes the correct PATCH endpoint.
 *   8. Formula PATCH error surfaces inline (no cascading failure).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("sonner", () => {
  const _toast = Object.assign(vi.fn(), {
    success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn(),
  });
  return { toast: _toast, Toaster: () => null };
});

vi.mock("@/api", () => {
  const _api = {
    get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn(),
  };
  return { api: _api };
});

const _authState = { user: { role: "admin", id: "u1" } };
vi.mock("@/auth", () => ({ useAuth: () => _authState }));

import ChemistryConfigurationSettings from "@/pages/settings/ChemistryConfigurationSettings";
import { api } from "@/api";
import { toast } from "sonner";


const DEFAULT_CHEM = {
  targets: {
    free_chlorine:    { min: 1.0, max: 3.0,  unit: "ppm" },
    ph:               { min: 7.2, max: 7.6,  unit: "" },
    alkalinity:       { min: 80,  max: 120,  unit: "ppm" },
    cyanuric_acid:    { min: 30,  max: 50,   unit: "ppm" },
    calcium_hardness: { min: 200, max: 400,  unit: "ppm" },
    salt:             { min: 2700, max: 3400, unit: "ppm" },
  },
  gate_mode: "strict",
  outer_bounds: {
    free_chlorine: [0, 10], ph: [0, 14], alkalinity: [0, 500],
    cyanuric_acid: [0, 300], calcium_hardness: [0, 1000],
    salt: [0, 6000],
  },
};

const DEFAULT_FORMULAS = {
  formulas: {
    free_chlorine:       { tenant_formula: "", default_formula: "round(max(0, (avg_target - current) * volume_gallons / 256000), 2)", using_default: true },
    ph_up:               { tenant_formula: "", default_formula: "round(max(0, (avg_target - current) * volume_gallons * 3 / 16000), 1)", using_default: true },
    ph_down:             { tenant_formula: "", default_formula: "round(max(0, (current - avg_target) * volume_gallons / 32000), 2)", using_default: true },
    alkalinity_up:       { tenant_formula: "", default_formula: "round(max(0, (avg_target - current) * volume_gallons * 21 / 1600000), 1)", using_default: true },
    cyanuric_acid_up:    { tenant_formula: "", default_formula: "round(max(0, (avg_target - current) * volume_gallons * 13 / 100000), 1)", using_default: true },
    calcium_hardness_up: { tenant_formula: "", default_formula: "round(max(0, (avg_target - current) * volume_gallons / 10000), 1)", using_default: true },
    salt_up:             { tenant_formula: "", default_formula: "round(max(0, (avg_target - current) * volume_gallons / 120000), 1)", using_default: true },
  },
  allowed_names:     ["current", "min_target", "max_target", "avg_target", "volume_gallons", "delta"],
  allowed_functions: ["abs", "min", "max", "round"],
  max_length: 200,
};


beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  api.post.mockReset();
  Object.values(toast).forEach((fn) => {
    if (typeof fn === "function") fn.mockReset?.();
  });
  _authState.user = { role: "admin", id: "u1" };
});
afterEach(() => vi.clearAllMocks());


describe("ChemistryConfigurationSettings · Sprint 3b", () => {
  it("non-admin sees forbidden card, no editors", async () => {
    _authState.user = { role: "technician", id: "u2" };
    render(<ChemistryConfigurationSettings />);
    expect(screen.getByTestId("chemistry-config-forbidden")).toBeTruthy();
    expect(screen.queryByTestId("chem-target-row-free_chlorine")).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("admin loads defaults from GET and renders 6 target rows + 3 gate modes", async () => {
    api.get.mockResolvedValue(DEFAULT_CHEM);
    render(<ChemistryConfigurationSettings />);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/tenants/mine/settings/chemistry");
    });
    expect(screen.getByTestId("chem-target-row-free_chlorine")).toBeTruthy();
    expect(screen.getByTestId("chem-target-row-ph")).toBeTruthy();
    expect(screen.getByTestId("chem-target-row-alkalinity")).toBeTruthy();
    expect(screen.getByTestId("chem-target-row-cyanuric_acid")).toBeTruthy();
    expect(screen.getByTestId("chem-target-row-calcium_hardness")).toBeTruthy();
    expect(screen.getByTestId("chem-target-row-salt")).toBeTruthy();
    expect(screen.getByTestId("chem-gate-mode-strict")).toBeTruthy();
    expect(screen.getByTestId("chem-gate-mode-warn_only")).toBeTruthy();
    expect(screen.getByTestId("chem-gate-mode-off")).toBeTruthy();
    // Salt inputs are pre-filled with the 2700-3400 default.
    expect(screen.getByTestId("chem-target-min-salt").value).toBe("2700");
    expect(screen.getByTestId("chem-target-max-salt").value).toBe("3400");
  });

  it("editing min/max + Save fires the correct PATCH", async () => {
    api.get.mockResolvedValue(DEFAULT_CHEM);
    api.patch.mockResolvedValue({
      ...DEFAULT_CHEM,
      targets: { ...DEFAULT_CHEM.targets,
                  free_chlorine: { min: 1.5, max: 4.0, unit: "ppm" } },
    });
    render(<ChemistryConfigurationSettings />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("chem-target-min-free_chlorine"),
                      { target: { value: "1.5" } });
    fireEvent.change(screen.getByTestId("chem-target-max-free_chlorine"),
                      { target: { value: "4.0" } });
    fireEvent.click(screen.getByTestId("chem-target-save-free_chlorine"));
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        "/tenants/mine/settings/chemistry",
        { targets: { free_chlorine: { min: 1.5, max: 4.0 } } },
      );
    });
    expect(toast.success).toHaveBeenCalled();
  });

  it("selecting a gate mode fires a gate_mode PATCH", async () => {
    api.get.mockResolvedValue(DEFAULT_CHEM);
    api.patch.mockResolvedValue({ ...DEFAULT_CHEM, gate_mode: "warn_only" });
    render(<ChemistryConfigurationSettings />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("chem-gate-mode-warn_only"));
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        "/tenants/mine/settings/chemistry", { gate_mode: "warn_only" },
      );
    });
  });

  it("PATCH failure surfaces a toast error", async () => {
    api.get.mockResolvedValue(DEFAULT_CHEM);
    api.patch.mockRejectedValueOnce({
      response: { data: { detail: {
        detail: "chemistry_target_out_of_bounds",
        message: "free_chlorine range 0-25 outside allowed 0-10",
      } } },
    });
    render(<ChemistryConfigurationSettings />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("chem-target-max-free_chlorine"),
                      { target: { value: "25" } });
    fireEvent.click(screen.getByTestId("chem-target-save-free_chlorine"));
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled();
    });
  });

  it("expanding Dosing Formulas fetches + renders cheat-sheet + 7 rows", async () => {
    api.get
      .mockResolvedValueOnce(DEFAULT_CHEM)
      .mockResolvedValueOnce(DEFAULT_FORMULAS);
    render(<ChemistryConfigurationSettings />);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("chem-formulas-toggle"));
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        "/tenants/mine/settings/chemistry/dosing-formulas",
      );
    });
    expect(screen.getByTestId("chem-formulas-cheatsheet")).toBeTruthy();
    for (const key of ["free_chlorine", "ph_up", "ph_down",
                        "alkalinity_up", "cyanuric_acid_up",
                        "calcium_hardness_up", "salt_up"]) {
      expect(screen.getByTestId(`chem-formula-row-${key}`)).toBeTruthy();
    }
  });

  it("clicking Test formula invokes /chemistry/dose/preview", async () => {
    api.get
      .mockResolvedValueOnce(DEFAULT_CHEM)
      .mockResolvedValueOnce(DEFAULT_FORMULAS);
    api.post.mockResolvedValue({
      recommended_dose_oz: 1.3,
      formula_used: "max(0, (avg_target - current) * volume_gallons * 0.00013)",
      evaluation_ok: true,
      source: "tenant",
    });
    render(<ChemistryConfigurationSettings />);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("chem-formulas-toggle"));
    await waitFor(() =>
      expect(screen.getByTestId("chem-formula-row-free_chlorine")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("chem-formula-input-free_chlorine"),
                      { target: { value: "max(0, (avg_target - current) * volume_gallons * 0.00013)" } });
    fireEvent.click(screen.getByTestId("chem-formula-test-free_chlorine"));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/chemistry/dose/preview",
        expect.objectContaining({
          chemical: "free_chlorine",
          current: 1.0,
          volume_gallons: 10000,
          formula: "max(0, (avg_target - current) * volume_gallons * 0.00013)",
        }),
      );
    });
    // Preview result is displayed inline.
    await waitFor(() =>
      expect(screen.getByTestId("chem-formula-preview-free_chlorine")).toBeTruthy(),
    );
  });

  it("saving a formula fires PATCH to /dosing-formulas", async () => {
    api.get
      .mockResolvedValueOnce(DEFAULT_CHEM)
      .mockResolvedValueOnce(DEFAULT_FORMULAS);
    api.patch.mockResolvedValue({
      ...DEFAULT_FORMULAS,
      formulas: {
        ...DEFAULT_FORMULAS.formulas,
        ph_up: { tenant_formula: "1 + 2", default_formula: "...", using_default: false },
      },
    });
    render(<ChemistryConfigurationSettings />);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("chem-formulas-toggle"));
    await waitFor(() =>
      expect(screen.getByTestId("chem-formula-row-ph_up")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("chem-formula-input-ph_up"),
                      { target: { value: "1 + 2" } });
    fireEvent.click(screen.getByTestId("chem-formula-save-ph_up"));
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        "/tenants/mine/settings/chemistry/dosing-formulas",
        { ph_up: "1 + 2" },
      );
    });
    expect(toast.success).toHaveBeenCalled();
  });

  it("formula PATCH error renders inline error message", async () => {
    api.get
      .mockResolvedValueOnce(DEFAULT_CHEM)
      .mockResolvedValueOnce(DEFAULT_FORMULAS);
    api.patch.mockRejectedValueOnce({
      response: { data: { detail: {
        detail: "chemistry_formula_invalid",
        field: "ph_up",
        error: "bad_syntax: unexpected EOF",
      } } },
    });
    render(<ChemistryConfigurationSettings />);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("chem-formulas-toggle"));
    await waitFor(() =>
      expect(screen.getByTestId("chem-formula-row-ph_up")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("chem-formula-input-ph_up"),
                      { target: { value: "(2 + )" } });
    fireEvent.click(screen.getByTestId("chem-formula-save-ph_up"));
    await waitFor(() =>
      expect(screen.getByTestId("chem-formula-error-ph_up")).toBeTruthy(),
    );
    expect(toast.error).toHaveBeenCalled();
  });
});
