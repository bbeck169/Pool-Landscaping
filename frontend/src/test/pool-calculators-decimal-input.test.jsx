/**
 * CHECKLIST-DECIMAL-INPUT-FIX · PoolCalculators sweep · Feb-2026 —
 * every chemistry / dosing-calculator input on the ``/tech/pool-
 * calculators`` page previously rendered through two shared
 * helper components (``Field`` + ``AxisWithUnit``) that both used
 * ``type="number"`` + raw ``onChange(e.target.value)``.  Per the
 * HTML5 spec, Chrome / Firefox / iOS Safari all return
 * ``e.target.value === ""`` for intermediate decimal states like
 * ``"7."`` — the parent panel's ``setX`` then wrote that blank
 * into state, locking the user out of ever typing a decimal.
 *
 * 25 fields across six panels (LSI, Volume, Salt, Turnover,
 * Heater, Material) were simultaneously broken because every one
 * of them routed through the same two helpers.  Fix: single
 * component edit per helper → migrate to ``type="text"`` +
 * ``inputMode="decimal"`` + keystroke regex guard.  Live-string
 * state semantics preserved so Compute buttons click directly
 * after typing still see fresh values (no blur-vs-click race).
 *
 * These tests mount the full ``<PoolCalculators />`` surface and
 * drive the real tab switcher to prove the behavioural fix at the
 * parent-component level (not the helper-component level) — a
 * caller passing ``type="number"`` to ``Field`` would silently
 * reintroduce the bug on just that one call site, so the parent-
 * level harness is what actually locks the fix.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async () => ({})),
    post: vi.fn(async () => ({})),
  },
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));

import PoolCalculators from "@/pages/tech/PoolCalculators.jsx";


function _mount(initialRoute = "/tech/pool-calculators") {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <PoolCalculators />
    </MemoryRouter>,
  );
}


afterEach(() => cleanup());


describe("PoolCalculators · LSI panel · chemistry decimal input", () => {
  it.each([
    ["lsi-ph",   "7",    "7.",   "7.4"],
    ["lsi-temp", "80",   "80.",  "80.5"],
    ["lsi-ch",   "250",  "250.", "250.5"],
    ["lsi-ta",   "100",  "100.", "100.5"],
    ["lsi-tds",  "1500", "1500.", "1500.5"],
    ["lsi-cya",  "40",   "40.",  "40.5"],
  ])("%s keeps the trailing dot in state (typing %s → %s → %s is NOT blanked)",
    (testid, k1, k2, k3) => {
      _mount();
      const input = screen.getByTestId(testid);
      expect(input.getAttribute("type")).toBe("text");
      expect(input.getAttribute("inputmode")).toBe("decimal");

      fireEvent.change(input, { target: { value: k1 } });
      expect(input.value).toBe(k1);
      // Pre-fix regression lock: this was ``""`` because
      // ``type="number"`` returned an empty string for the invalid
      // HTML5 number literal, which ``setPh`` then wrote to state.
      fireEvent.change(input, { target: { value: k2 } });
      expect(input.value).toBe(k2);
      fireEvent.change(input, { target: { value: k3 } });
      expect(input.value).toBe(k3);
    });

  it("pH field rejects a letter paste at keystroke (regex guard)",
    () => {
      _mount();
      const input = screen.getByTestId("lsi-ph");
      fireEvent.change(input, { target: { value: "7.4" } });
      expect(input.value).toBe("7.4");
      fireEvent.change(input, { target: { value: "abc" } });
      expect(input.value).toBe("7.4");
    });
});


describe("PoolCalculators · Volume panel · dimension decimal input", () => {
  it.each([
    ["vol-length",   "20"],
    ["vol-width",    "40"],
    ["vol-avgdepth", "5"],
  ])("%s keeps a trailing dot in state (regression lock for the "
     + "``e.target.value === ''`` eating bug)", (testid, _initial) => {
      // Volume panel is on the Volume tab, not the default LSI.
      _mount();
      fireEvent.click(screen.getByTestId("calc-tab-volume"));
      const input = screen.getByTestId(testid);
      expect(input.getAttribute("type")).toBe("text");
      // Clear + retype a decimal.
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.change(input, { target: { value: "12" } });
      fireEvent.change(input, { target: { value: "12." } });
      expect(input.value).toBe("12.");
      fireEvent.change(input, { target: { value: "12.5" } });
      expect(input.value).toBe("12.5");
    });
});


describe("PoolCalculators · Salt panel · ppm decimal input", () => {
  it.each([
    ["salt-gal", "20000"],
    ["salt-cur", "2500"],
    ["salt-tgt", "3200"],
  ])("%s keeps a trailing dot in state (regression lock)",
    (testid, _initial) => {
      _mount();
      fireEvent.click(screen.getByTestId("calc-tab-salt"));
      const input = screen.getByTestId(testid);
      expect(input.getAttribute("type")).toBe("text");
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.change(input, { target: { value: "3450" } });
      fireEvent.change(input, { target: { value: "3450." } });
      expect(input.value).toBe("3450.");
      fireEvent.change(input, { target: { value: "3450.5" } });
      expect(input.value).toBe("3450.5");
    });

  it("salt-cur accepts a leading-dot entry ('.5' tenths of a ppm)",
    () => {
      _mount();
      fireEvent.click(screen.getByTestId("calc-tab-salt"));
      const input = screen.getByTestId("salt-cur");
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.change(input, { target: { value: "." } });
      expect(input.value).toBe(".");
      fireEvent.change(input, { target: { value: ".5" } });
      expect(input.value).toBe(".5");
    });
});


describe("PoolCalculators · Material panel · AxisWithUnit decimal input",
  () => {
    it("mat-length keeps a trailing dot (AxisWithUnit regression lock)",
      () => {
        _mount();
        fireEvent.click(screen.getByTestId("calc-tab-material"));
        const input = screen.getByTestId("mat-length-value");
        expect(input.getAttribute("type")).toBe("text");
        expect(input.getAttribute("inputmode")).toBe("decimal");

        fireEvent.change(input, { target: { value: "" } });
        fireEvent.change(input, { target: { value: "12" } });
        fireEvent.change(input, { target: { value: "12." } });
        expect(input.value).toBe("12.");
        fireEvent.change(input, { target: { value: "12.5" } });
        expect(input.value).toBe("12.5");
      });

    it("Material density override (Field callsite) retains a trailing "
       + "dot (negative allowed per Field regex)", () => {
      _mount();
      fireEvent.click(screen.getByTestId("calc-tab-material"));
      const input = screen.getByTestId("mat-density");
      expect(input.getAttribute("type")).toBe("text");
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.change(input, { target: { value: "1" } });
      fireEvent.change(input, { target: { value: "1." } });
      expect(input.value).toBe("1.");
      fireEvent.change(input, { target: { value: "1.4" } });
      expect(input.value).toBe("1.4");
      // Negative allowed per the ``/^-?\d*\.?\d*$/`` guard — Field is
      // the only Field callsite that could physically take a signed
      // delta (``-`` sign is dropped by AxisWithUnit's stricter regex).
      fireEvent.change(input, { target: { value: "-0.1" } });
      expect(input.value).toBe("-0.1");
    });
  });


describe("PoolCalculators · Turnover + Heater panels · parity", () => {
  it("turn-gpm (Turnover panel) keeps a trailing dot", () => {
    _mount();
    fireEvent.click(screen.getByTestId("calc-tab-turnover"));
    const input = screen.getByTestId("turn-gpm");
    expect(input.getAttribute("type")).toBe("text");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.change(input, { target: { value: "60" } });
    fireEvent.change(input, { target: { value: "60." } });
    expect(input.value).toBe("60.");
  });

  it("heat-hup (Heater panel · heat-up hours) keeps a trailing dot",
    () => {
      _mount();
      fireEvent.click(screen.getByTestId("calc-tab-heater"));
      const input = screen.getByTestId("heat-hup");
      expect(input.getAttribute("type")).toBe("text");
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.change(input, { target: { value: "4" } });
      fireEvent.change(input, { target: { value: "4." } });
      expect(input.value).toBe("4.");
      fireEvent.change(input, { target: { value: "4.5" } });
      expect(input.value).toBe("4.5");
    });
});
