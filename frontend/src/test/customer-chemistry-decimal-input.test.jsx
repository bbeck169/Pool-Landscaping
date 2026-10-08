/**
 * CHECKLIST-DECIMAL-INPUT-FIX · follow-up · Feb-2026 — AI Dosing
 * Recommendation panel in ``CustomerChemistry`` must preserve
 * intermediate decimal keystrokes ("7.", ".5") on every chemistry
 * reading (FC / pH / TA / CYA / Salt) + pool volume.
 *
 * Pre-fix: inputs rendered ``type="number"`` so Chrome / Firefox /
 * iOS Safari returned ``e.target.value === ""`` for strings like
 * ``"7."`` — the ``setReadings`` call blanked the input before the
 * user could finish typing a decimal, effectively locking the panel
 * into integer entry.  The AI dosing endpoint was then called with
 * rounded integers that are chemically meaningless for pH / FC.
 *
 * Post-fix guarantees:
 *   * The input renders ``type="text"`` + ``inputMode="decimal"``
 *     so the raw string flows through to React state intact.
 *   * The keystroke-level ``/^\d*\.?\d*$/`` guard still rejects
 *     paste of letters / multi-dot cases.
 *   * ``Number("7.")`` → 7 happens later via the Recommend handler,
 *     so the server never sees a trailing-dot string.
 */
import React from "react";
import { describe, it, expect, vi, afterEach, beforeEach }
  from "vitest";
import {
  render, screen, cleanup, fireEvent,
} from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (p) => {
      if (p && p.startsWith("/customers/")) {
        return { id: "cx1", name: "Test Customer" };
      }
      if (p === "/chemicals/catalog") return [];
      return null;
    }),
    post: vi.fn(async () => ({ ok: true })),
  },
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));

import CustomerChemistry
  from "@/pages/customers/CustomerChemistry.jsx";


function _mountAt(route = "/customers/cx1/chemistry") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/customers/:id/chemistry" element={<CustomerChemistry />} />
      </Routes>
    </MemoryRouter>,
  );
}


afterEach(() => {
  cleanup();
});


beforeEach(() => {
  // Flush between tests — the component useEffect-fetches via the
  // mocked api on mount, so each render is deterministic.
});


describe("CustomerChemistry · AI Dosing · intermediate decimal states",
         () => {
  it.each([
    ["cx-reading-fc", "fc"],
    ["cx-reading-ph", "ph"],
    ["cx-reading-ta", "ta"],
    ["cx-reading-cya", "cya"],
    ["cx-reading-salt", "salt"],
  ])("%s keeps a trailing dot in state (typing '7.' is NOT blanked)",
    async (testid, _key) => {
      _mountAt();
      const input = await screen.findByTestId(testid);
      // ``type="text"`` is the whole point of the fix — any
      // ``number`` here would re-eat the trailing dot across every
      // major browser.
      expect(input.getAttribute("type")).toBe("text");
      expect(input.getAttribute("inputmode")).toBe("decimal");

      fireEvent.change(input, { target: { value: "7" } });
      expect(input.value).toBe("7");
      fireEvent.change(input, { target: { value: "7." } });
      // Regression lock: pre-fix this was ``""`` because the
      // browser returned an empty string for the invalid HTML5
      // number literal, which setReadings then wrote to state.
      expect(input.value).toBe("7.");
      fireEvent.change(input, { target: { value: "7.4" } });
      expect(input.value).toBe("7.4");
    });

  it("pool volume keeps a trailing dot in state (regression lock)",
    async () => {
      _mountAt();
      const input = await screen.findByTestId("cx-volume");
      expect(input.getAttribute("type")).toBe("text");
      expect(input.getAttribute("inputmode")).toBe("decimal");

      // Start from the component's initial ``15000`` default — the
      // user clears + retypes a decimal volume.
      fireEvent.change(input, { target: { value: "" } });
      fireEvent.change(input, { target: { value: "1" } });
      fireEvent.change(input, { target: { value: "15" } });
      fireEvent.change(input, { target: { value: "15." } });
      expect(input.value).toBe("15.");
      fireEvent.change(input, { target: { value: "15.5" } });
      expect(input.value).toBe("15.5");
    });

  it("leading-dot entry ('.5') survives the keystroke regex guard",
    async () => {
      _mountAt();
      const input = await screen.findByTestId("cx-reading-fc");
      fireEvent.change(input, { target: { value: "." } });
      expect(input.value).toBe(".");
      fireEvent.change(input, { target: { value: ".5" } });
      expect(input.value).toBe(".5");
    });

  it("pasting letters is rejected at keystroke, state stays untouched",
    async () => {
      _mountAt();
      const input = await screen.findByTestId("cx-reading-ph");
      fireEvent.change(input, { target: { value: "7.4" } });
      expect(input.value).toBe("7.4");
      // Second-dot paste fails the regex and is dropped — state
      // holds at the last-valid snapshot.
      fireEvent.change(input, { target: { value: "7.4.5" } });
      expect(input.value).toBe("7.4");
      // Pure letters fail the regex and are dropped.
      fireEvent.change(input, { target: { value: "abc" } });
      expect(input.value).toBe("7.4");
    });

  it("salt reading accepts the common one-decimal ppm format "
     + "('3450.5') — tenths of a ppm matter on salt cells",
    async () => {
      _mountAt();
      const input = await screen.findByTestId("cx-reading-salt");
      fireEvent.change(input, { target: { value: "3450" } });
      expect(input.value).toBe("3450");
      fireEvent.change(input, { target: { value: "3450." } });
      expect(input.value).toBe("3450.");
      fireEvent.change(input, { target: { value: "3450.5" } });
      expect(input.value).toBe("3450.5");
    });
});
