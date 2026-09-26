/**
 * Feb-2026 · T2.5 · Material Calculator tab (web).
 *
 * Locks the ``MaterialPanel`` render + math wiring inside
 * ``PoolCalculators.jsx``:
 *   1. Renders 3 axis inputs (Length, Width, Depth), each paired
 *      with a unit selector (ft | in | yd).
 *   2. Material dropdown lists all 7 entries, each with a preset
 *      default density.
 *   3. Selecting a material prefills the density input to that
 *      material's default; the user can override, and the
 *      override is preserved across compute — but resets when the
 *      material changes.
 *   4. Compute POSTs to ``/calculators/material`` with the
 *      dimensional + material + density-override payload and
 *      renders 3 ``ResultBox``es (Cubic Feet, Cubic Yards, Tons)
 *      rounded to 2 decimals.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor, within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { apiPostSpy } = vi.hoisted(() => ({ apiPostSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: {
    post: (...args) => apiPostSpy(...args),
    get: vi.fn(),
  },
}));

// Hermetic theme mock — mirrors the values PoolCalculators reaches
// for (colors.brand / .background / .border / .muted / .onSurface).
vi.mock("@/theme", () => ({
  colors: {
    surface: "#FFFFFF",
    background: "#F8FAFC",
    border: "#E4E4E7",
    muted: "#71717A",
    onSurface: "#09090B",
    brand: "#0B4A6F",
  },
  font: {},
  gradients: {},
}));


import PoolCalculators from "@/pages/tech/PoolCalculators";


function renderCalc({ initialEntries = ["/tech/tools/calculators?tab=material"] } = {}) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <PoolCalculators />
    </MemoryRouter>,
  );
}

async function switchToMaterialTab() {
  const tab = await screen.findByTestId("calc-tab-material");
  fireEvent.click(tab);
  return screen.findByTestId("calc-panel-material");
}


beforeEach(() => {
  apiPostSpy.mockReset();
  apiPostSpy.mockResolvedValue({
    cubic_feet: 50.0,
    cubic_yards: 1.8519,
    total_tons: 2.5926,
    material: "gravel_dry",
    density_used: 1.4,
  });
});
afterEach(() => { cleanup(); });


// ═════════════════════════════════════════════════════════════════════
// Tab registration + initial-tab from ?tab=material
// ═════════════════════════════════════════════════════════════════════
describe("PoolCalculators · Material tab registration", () => {
  it("registers the Material tab button next to the existing 5 tabs", () => {
    renderCalc({ initialEntries: ["/tech/tools/calculators"] });
    expect(screen.getByTestId("calc-tab-material")).toBeTruthy();
    expect(screen.getByTestId("calc-tab-material").textContent).toContain("Material");
  });

  it("?tab=material query param opens the Material panel on mount", () => {
    renderCalc();  // default = ?tab=material
    expect(screen.getByTestId("calc-panel-material")).toBeTruthy();
    // LSI panel must NOT be rendered when ?tab=material.
    expect(screen.queryByTestId("calc-panel-lsi")).toBeNull();
  });

  it("unknown ?tab=xxx falls back to lsi (safe default)", () => {
    renderCalc({ initialEntries: ["/tech/tools/calculators?tab=xxx"] });
    expect(screen.getByTestId("calc-panel-lsi")).toBeTruthy();
    expect(screen.queryByTestId("calc-panel-material")).toBeNull();
  });
});


// ═════════════════════════════════════════════════════════════════════
// Rendering + inputs
// ═════════════════════════════════════════════════════════════════════
describe("MaterialPanel · rendering", () => {
  it("renders 3 axis inputs (Length, Width, Depth) with paired unit selectors", async () => {
    renderCalc();
    await switchToMaterialTab();
    for (const axis of ["length", "width", "depth"]) {
      expect(screen.getByTestId(`mat-${axis}-value`)).toBeTruthy();
      const unit = screen.getByTestId(`mat-${axis}-unit`);
      const opts = within(unit).getAllByRole("option").map((o) => o.value);
      expect(opts).toEqual(["ft", "in", "yd"]);
    }
  });

  it("renders material dropdown with all 7 options", () => {
    renderCalc();
    const sel = screen.getByTestId("mat-material");
    const opts = within(sel).getAllByRole("option").map((o) => o.value);
    expect(opts).toEqual([
      "gravel_dry", "gravel_wet_sand", "sand_dry",
      "topsoil", "mulch", "limestone", "concrete",
    ]);
  });

  it("density input prefills from the picked material", () => {
    renderCalc();
    expect(screen.getByTestId("mat-density").value).toBe("1.4");
    // Change → topsoil (default 1.1)
    fireEvent.change(screen.getByTestId("mat-material"), {
      target: { value: "topsoil" },
    });
    expect(screen.getByTestId("mat-density").value).toBe("1.1");
    // Concrete (2.0)
    fireEvent.change(screen.getByTestId("mat-material"), {
      target: { value: "concrete" },
    });
    expect(screen.getByTestId("mat-density").value).toBe("2");
  });

  it("editing density stops the material-change auto-refill until material changes again", () => {
    renderCalc();
    fireEvent.change(screen.getByTestId("mat-density"), {
      target: { value: "1.55" },
    });
    expect(screen.getByTestId("mat-density").value).toBe("1.55");
    // Density does NOT reset on the next re-render of the same material.
    fireEvent.change(screen.getByTestId("mat-length-value"), {
      target: { value: "999" },  // unrelated input change
    });
    expect(screen.getByTestId("mat-density").value).toBe("1.55");
    // Changing material resets density to that material's default.
    fireEvent.change(screen.getByTestId("mat-material"), {
      target: { value: "mulch" },
    });
    expect(screen.getByTestId("mat-density").value).toBe("0.5");
  });
});


// ═════════════════════════════════════════════════════════════════════
// Payload sent on compute + result rendering
// ═════════════════════════════════════════════════════════════════════
describe("MaterialPanel · compute payload + result rendering", () => {
  it("posts unit-tagged L/W/D + material to /calculators/material and shows 3 ResultBoxes rounded to 2 decimals", async () => {
    renderCalc();
    // Set inputs → 12.5 ft × 8 ft × 6 in / gravel_dry (defaults)
    fireEvent.change(screen.getByTestId("mat-length-value"),
                       { target: { value: "12.5" } });
    fireEvent.change(screen.getByTestId("mat-width-value"),
                       { target: { value: "8" } });
    fireEvent.change(screen.getByTestId("mat-depth-value"),
                       { target: { value: "6" } });
    fireEvent.change(screen.getByTestId("mat-depth-unit"),
                       { target: { value: "in" } });
    fireEvent.click(screen.getByTestId("mat-compute"));

    await waitFor(() => expect(apiPostSpy).toHaveBeenCalledTimes(1));
    const [path, body] = apiPostSpy.mock.calls[0];
    expect(path).toBe("/calculators/material");
    expect(body).toEqual({
      length: { value: 12.5, unit: "ft" },
      width: { value: 8, unit: "ft" },
      depth: { value: 6, unit: "in" },
      material: "gravel_dry",
      density_override: null,   // user didn't touch density
    });

    // Result boxes render each measure rounded to 2 decimals.
    await screen.findByTestId("mat-result-ft3");
    expect(screen.getByTestId("mat-result-ft3").textContent).toContain("50.00 ft³");
    expect(screen.getByTestId("mat-result-yd3").textContent).toContain("1.85 yd³");
    expect(screen.getByTestId("mat-result-tons").textContent).toContain("2.59 t");
  });

  it("includes density_override in the payload once the density input has been touched", async () => {
    renderCalc();
    fireEvent.change(screen.getByTestId("mat-length-value"),
                       { target: { value: "3" } });
    fireEvent.change(screen.getByTestId("mat-width-value"),
                       { target: { value: "3" } });
    fireEvent.change(screen.getByTestId("mat-depth-value"),
                       { target: { value: "3" } });
    fireEvent.change(screen.getByTestId("mat-density"),
                       { target: { value: "1.62" } });

    apiPostSpy.mockResolvedValueOnce({
      cubic_feet: 27, cubic_yards: 1, total_tons: 1.62,
      material: "gravel_dry", density_used: 1.62,
    });
    fireEvent.click(screen.getByTestId("mat-compute"));

    await waitFor(() => expect(apiPostSpy).toHaveBeenCalledTimes(1));
    const body = apiPostSpy.mock.calls[0][1];
    expect(body.density_override).toBeCloseTo(1.62, 5);
    expect(body.material).toBe("gravel_dry");
  });
});
