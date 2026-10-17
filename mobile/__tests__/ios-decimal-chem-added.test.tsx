/**
 * TD-65 Phase 2a — iOS comma-locale decimal entry on the 3 chemistry
 * surfaces missed by 09b0bcb78 / 55c96ee3b:
 *   M6 ChemicalDropdownStack · M7 ChemicalPickerSheet · M8 MaintenanceLog.
 *
 * iOS `decimal-pad` on de/fr/es/pt-BR devices emits ",". Before this fix
 * the chemical rows stripped it ("0,5" → "05" = 10× dose) and the
 * maintenance log stored "7,6" raw (parseFloat → 7). All three now route
 * keystrokes through `sanitizeDecimalInput`.
 */
import React from "react";
import { render, fireEvent, act } from "@testing-library/react-native";

import ChemicalDropdownStack from "@/src/components/checklist/ChemicalDropdownStack";
import ChemicalPickerSheet from "@/src/components/checklist/ChemicalPickerSheet";
import MaintenanceLog from "@/src/components/job/MaintenanceLog";
import { offlineWrite } from "@/src/services/offlineWrite";

jest.mock("@/src/api", () => ({ api: { post: jest.fn(), get: jest.fn() } }));
jest.mock("@/src/services/offlineWrite", () => ({
  offlineWrite: jest.fn(async () => ({ data: { id: "j1" }, queued: false })),
}));
jest.mock("react-native-safe-area-context", () => ({
  ...jest.requireActual("react-native-safe-area-context"),
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("expo-image-picker", () => ({
  requestMediaLibraryPermissionsAsync: jest.fn(async () => ({ granted: false })),
  launchImageLibraryAsync: jest.fn(),
}));

const lastChem = (onChange: jest.Mock, slug: string) => {
  const calls = onChange.mock.calls;
  const list = calls[calls.length - 1][0].chemicals_added as any[];
  return list.find((c) => c.slug === slug);
};

// ─── M6 · ChemicalDropdownStack ─────────────────────────────────────
describe("M6 ChemicalDropdownStack", () => {
  const setup = (chemicalsAdded: any[] = []) => {
    const onChange = jest.fn();
    const q = render(<ChemicalDropdownStack chemicalsAdded={chemicalsAdded} onChange={onChange} />);
    const input = (slug: string) => q.getByTestId(`chemicals-row-${slug}-input`);
    return { q, onChange, input };
  };

  it("muriatic acid (decimal) iOS '0,5' → stored as '0.5' → commits 0.5 gal (not 5)", () => {
    const { input, onChange } = setup();
    expect(input("muriatic_acid").props.keyboardType).toBe("decimal-pad");
    fireEvent.changeText(input("muriatic_acid"), "0,5");
    expect(input("muriatic_acid").props.value).toBe("0.5");
    fireEvent(input("muriatic_acid"), "blur");
    expect(lastChem(onChange, "muriatic_acid")).toMatchObject({ quantity: 0.5, amount: "0.5", unit: "gal" });
  });

  it("chlorine tabs (integer) iOS '7,6' → '76' (same as US '7.6' with dot stripped)", () => {
    const { input } = setup();
    expect(input("chlorine_tabs").props.keyboardType).toBe("number-pad");
    fireEvent.changeText(input("chlorine_tabs"), "7,6");
    expect(input("chlorine_tabs").props.value).toBe("76");
    fireEvent.changeText(input("chlorine_tabs"), "7.6");
    expect(input("chlorine_tabs").props.value).toBe("76");
  });

  it("US-locale regression: '7.6' unchanged on a decimal row", () => {
    const { input, onChange } = setup();
    fireEvent.changeText(input("liquid_chlorine"), "7.6");
    expect(input("liquid_chlorine").props.value).toBe("7.6");
    fireEvent(input("liquid_chlorine"), "blur");
    expect(lastChem(onChange, "liquid_chlorine")).toMatchObject({ quantity: 7.6 });
  });

  it("'7..6' second dot rejected (keeps '7.')", () => {
    const { input } = setup();
    fireEvent.changeText(input("muriatic_acid"), "7.");
    fireEvent.changeText(input("muriatic_acid"), "7..6");
    expect(input("muriatic_acid").props.value).toBe("7.");
  });

  it("'' clears → commit removes the chemical", () => {
    const { input, onChange } = setup([{ slug: "muriatic_acid", name: "Muriatic Acid", quantity: 0.5 }]);
    expect(input("muriatic_acid").props.value).toBe("0.5");
    fireEvent.changeText(input("muriatic_acid"), "");
    expect(input("muriatic_acid").props.value).toBe("");
    fireEvent(input("muriatic_acid"), "blur");
    expect(lastChem(onChange, "muriatic_acid")).toBeUndefined();
  });

  it("rejected keystroke on a saved row keeps the saved value (never blanks it)", () => {
    const { input } = setup([{ slug: "muriatic_acid", name: "Muriatic Acid", quantity: 0.5 }]);
    fireEvent.changeText(input("muriatic_acid"), "0.5.");
    expect(input("muriatic_acid").props.value).toBe("0.5");
  });
});

// ─── M7 · ChemicalPickerSheet ───────────────────────────────────────
describe("M7 ChemicalPickerSheet", () => {
  const setup = (chemicalsAdded: any[] = []) => {
    const onChange = jest.fn();
    const q = render(
      <ChemicalPickerSheet visible onClose={jest.fn()} chemicalsAdded={chemicalsAdded} onChange={onChange} />,
    );
    const input = (slug: string) => q.getByTestId(`chem-input-${slug}`);
    return { q, onChange, input };
  };

  it("muriatic acid iOS '0,25' → stored as '0.25' → commits 0.25", () => {
    const { input, onChange } = setup();
    expect(input("muriatic_acid").props.keyboardType).toBe("decimal-pad");
    fireEvent.changeText(input("muriatic_acid"), "0,25");
    expect(input("muriatic_acid").props.value).toBe("0.25");
    fireEvent(input("muriatic_acid"), "blur");
    expect(lastChem(onChange, "muriatic_acid")).toMatchObject({ quantity: 0.25, amount: "0.25" });
  });

  it("chlorine tabs (integer) iOS '7,6' → '76'", () => {
    const { input } = setup();
    fireEvent.changeText(input("chlorine_tabs"), "7,6");
    expect(input("chlorine_tabs").props.value).toBe("76");
  });

  it("US-locale regression: '7.6' unchanged", () => {
    const { input, onChange } = setup();
    fireEvent.changeText(input("liquid_chlorine"), "7.6");
    expect(input("liquid_chlorine").props.value).toBe("7.6");
    fireEvent(input("liquid_chlorine"), "blur");
    expect(lastChem(onChange, "liquid_chlorine")).toMatchObject({ quantity: 7.6 });
  });

  it("'7..6' second dot rejected (keeps '7.')", () => {
    const { input } = setup();
    fireEvent.changeText(input("liquid_chlorine"), "7.");
    fireEvent.changeText(input("liquid_chlorine"), "7..6");
    expect(input("liquid_chlorine").props.value).toBe("7.");
  });

  it("'' clears → commit removes the chemical", () => {
    const { input, onChange } = setup([{ slug: "muriatic_acid", name: "Muriatic Acid", quantity: 0.25 }]);
    fireEvent.changeText(input("muriatic_acid"), "");
    expect(input("muriatic_acid").props.value).toBe("");
    fireEvent(input("muriatic_acid"), "blur");
    expect(lastChem(onChange, "muriatic_acid")).toBeUndefined();
  });

  it("rejected keystroke on a saved row keeps the saved value", () => {
    const { input } = setup([{ slug: "muriatic_acid", name: "Muriatic Acid", quantity: 0.25 }]);
    fireEvent.changeText(input("muriatic_acid"), "0.25a");
    expect(input("muriatic_acid").props.value).toBe("0.25");
  });
});

// ─── M8 · MaintenanceLog ────────────────────────────────────────────
describe("M8 MaintenanceLog", () => {
  beforeEach(() => (offlineWrite as jest.Mock).mockClear());
  const setup = (mtype: "filter" | "salt_cell", maintenance: any = {}) =>
    render(
      <MaintenanceLog job={{ id: "j1", maintenance }} mtype={mtype} readOnly={false} online onSaved={jest.fn()} />,
    );
  const savedPayload = () => (offlineWrite as jest.Mock).mock.calls[0][0].payload;

  it("PSI iOS '15,5' → stored as '15.5' → POSTs psi 15.5", async () => {
    const q = setup("filter");
    const psi = () => q.getByTestId("maint-psi-input");
    expect(psi().props.keyboardType).toBe("decimal-pad");
    fireEvent.changeText(psi(), "15,5");
    expect(psi().props.value).toBe("15.5");
    await act(async () => { fireEvent.press(q.getByTestId("maint-save")); });
    expect(savedPayload().psi).toBe(15.5);
  });

  it("salt_ppm iOS '3200,5' → stored as '3200.5' → POSTs salt_ppm 3200.5", async () => {
    const q = setup("salt_cell");
    const salt = () => q.getByTestId("maint-salt-input");
    expect(salt().props.keyboardType).toBe("decimal-pad");
    fireEvent.changeText(salt(), "3200,5");
    expect(salt().props.value).toBe("3200.5");
    await act(async () => { fireEvent.press(q.getByTestId("maint-save")); });
    expect(savedPayload().salt_ppm).toBe(3200.5);
  });

  it("US-locale regression: PSI '7.6' and salt '7.6' unchanged", () => {
    const f = setup("filter");
    fireEvent.changeText(f.getByTestId("maint-psi-input"), "7.6");
    expect(f.getByTestId("maint-psi-input").props.value).toBe("7.6");
    const s = setup("salt_cell");
    fireEvent.changeText(s.getByTestId("maint-salt-input"), "7.6");
    expect(s.getByTestId("maint-salt-input").props.value).toBe("7.6");
  });

  it("'7..6' second dot rejected (keeps '7.')", () => {
    const q = setup("filter");
    fireEvent.changeText(q.getByTestId("maint-psi-input"), "7.");
    fireEvent.changeText(q.getByTestId("maint-psi-input"), "7..6");
    expect(q.getByTestId("maint-psi-input").props.value).toBe("7.");
  });

  it("'' clears → POSTs psi null", async () => {
    const q = setup("filter", { psi: 12 });
    expect(q.getByTestId("maint-psi-input").props.value).toBe("12");
    fireEvent.changeText(q.getByTestId("maint-psi-input"), "");
    expect(q.getByTestId("maint-psi-input").props.value).toBe("");
    await act(async () => { fireEvent.press(q.getByTestId("maint-save")); });
    expect(savedPayload().psi).toBeNull();
  });
});
