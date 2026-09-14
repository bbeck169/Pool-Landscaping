/**
 * Feb-2026 · P0 · Lead form address autofill — AddressAutocomplete
 * component unit tests.
 *
 * Locks the acceptance contract per the P0 dispatch:
 *   1. Suggestions list is capped at 5 rows even when the API
 *      returns 6+.
 *   2. Selecting a row invokes ``onChange`` with the parsed
 *      components + ``latitude`` / ``longitude`` from the details
 *      endpoint.
 *   3. Keyboard nav (ArrowDown → ArrowUp → Enter) selects the
 *      right suggestion.
 *   4. Escape closes the dropdown.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import AddressAutocomplete from "@/components/common/AddressAutocomplete";


const _stubAutocomplete = (n) =>
  Array.from({ length: n }).map((_, i) => ({
    place_id: `pid-${i}`,
    description: `${100 + i} Main St, Peoria, AZ, USA`,
    main_text: `${100 + i} Main St`,
    secondary_text: "Peoria, AZ, USA",
  }));

const _stubDetails = {
  street: "123 Main St",
  city: "Peoria",
  state: "AZ",
  zip: "85383",
  country: "US",
  latitude: 33.7654,
  longitude: -112.2381,
};


beforeEach(() => {
  global.fetch = vi.fn().mockImplementation((url) => {
    const s = String(url);
    if (s.includes("/api/public/places/autocomplete")) {
      return Promise.resolve({ ok: true, json: async () => _stubAutocomplete(8) });
    }
    if (s.includes("/api/public/places/details")) {
      return Promise.resolve({ ok: true, json: async () => _stubDetails });
    }
    return Promise.resolve({ ok: true, json: async () => ({}) });
  });
});
afterEach(() => { vi.clearAllMocks(); });


// Wait past the component's 250ms debounce plus jsdom scheduling.
const _flushDebounce = () => new Promise((r) => setTimeout(r, 320));

async function _typeAndFlush(input, value) {
  await act(async () => {
    fireEvent.change(input, { target: { value } });
    await _flushDebounce();
  });
}


describe("AddressAutocomplete", () => {
  it("caps suggestions to 5 rows even when the API returns more", async () => {
    render(<AddressAutocomplete onChange={() => {}} testId="addr-t1" />);
    const input = screen.getByTestId("addr-t1");
    await _typeAndFlush(input, "123 Main");
    await waitFor(() => expect(screen.getByTestId("addr-t1-listbox")).toBeTruthy());
    const options = screen.getAllByTestId(/^addr-t1-option-\d+$/);
    expect(options.length).toBe(5);
  });

  it("selecting a suggestion invokes onChange with parsed fields + lat/lng", async () => {
    const onChange = vi.fn();
    render(<AddressAutocomplete onChange={onChange} testId="addr-t2" />);
    const input = screen.getByTestId("addr-t2");
    await _typeAndFlush(input, "123 Main");
    await waitFor(() => expect(screen.getByTestId("addr-t2-listbox")).toBeTruthy());
    const firstOption = screen.getByTestId("addr-t2-option-0");
    await act(async () => {
      fireEvent.mouseDown(firstOption);
      // Details fetch resolves in the microtask queue.
      await new Promise((r) => setTimeout(r, 20));
    });
    // The last onChange invocation carries the resolved fields.
    const calls = onChange.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const final = calls[calls.length - 1][0];
    expect(final.street).toBe("123 Main St");
    expect(final.city).toBe("Peoria");
    expect(final.state).toBe("AZ");
    expect(final.zip).toBe("85383");
    expect(final.latitude).toBeCloseTo(33.7654);
    expect(final.longitude).toBeCloseTo(-112.2381);
    expect(final.formatted).toBe("123 Main St, Peoria, AZ, 85383");
  });

  it("keyboard nav ↓ ↓ ↑ Enter selects the second suggestion (idx 1)", async () => {
    render(<AddressAutocomplete onChange={() => {}} testId="addr-t3" />);
    const input = screen.getByTestId("addr-t3");
    await _typeAndFlush(input, "123 Main");
    await waitFor(() => expect(screen.getByTestId("addr-t3-listbox")).toBeTruthy());
    // Rendered order: activeIdx starts at 0 after the fetch settles.
    // ↓ → 1, ↓ → 2, ↑ → 1, Enter → select idx 1.
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
      await new Promise((r) => setTimeout(r, 20));
    });
    const detailsCall = global.fetch.mock.calls
      .find(([u]) => String(u).includes("/api/public/places/details"));
    expect(detailsCall).toBeTruthy();
    expect(String(detailsCall[0])).toContain("place_id=pid-1");
  });

  it("Escape closes the dropdown", async () => {
    render(<AddressAutocomplete onChange={() => {}} testId="addr-t4" />);
    const input = screen.getByTestId("addr-t4");
    await _typeAndFlush(input, "123 Main");
    await waitFor(() => expect(screen.getByTestId("addr-t4-listbox")).toBeTruthy());
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByTestId("addr-t4-listbox")).toBeNull(),
    );
  });
});
