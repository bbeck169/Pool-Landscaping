/**
 * Phase PRICEBOOK-UNIFY · Feb-2026 — <PricebookItemPicker /> tests.
 *
 * Locks:
 *   1. Renders the input + placeholder verbatim.
 *   2. Typing (post-debounce) fires ``GET /api/items?search=…``.
 *   3. ArrowDown / ArrowUp move the highlight; Enter selects;
 *      Escape closes the dropdown.
 *   4. ``onSelect(item)`` fires with the FULL row object.
 *   5. Accessibility: wrapper is ``role="combobox"``, result rows
 *      are ``role="option"``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


const { apiGetSpy } = vi.hoisted(() => ({
  apiGetSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGetSpy(...a),
  },
}));


import PricebookItemPicker from "@/components/pricebook/PricebookItemPicker";


const _FIXTURE_ROWS = [
  {
    id: "it-1", name: "Muriatic acid — gal",
    description: "Pool pH-lowering acid, 1-gallon jug",
    unit_price: 12.50, category: "Chemical",
  },
  {
    id: "it-2", name: "Trichlor tab 3-inch",
    description: "Chlorine tablet, 3\" slow-dissolve",
    unit_price: 4.75, category: "Chemical",
  },
  {
    id: "it-3", name: "Filter cartridge C-1750",
    description: "Replacement filter cartridge",
    unit_price: 89.00, category: "Equipment",
  },
];


beforeEach(() => {
  apiGetSpy.mockReset();
  apiGetSpy.mockResolvedValue(_FIXTURE_ROWS);
});


function _Wrapper({ initial = "", onSelect = () => {}, ...rest }) {
  const [value, setValue] = React.useState(initial);
  return (
    <PricebookItemPicker
      value={value}
      onChange={setValue}
      onSelect={onSelect}
      {...rest}
    />
  );
}


describe("<PricebookItemPicker /> — rendering", () => {
  it("renders the input with the provided placeholder", () => {
    render(<_Wrapper placeholder="Search chemicals…" />);
    const input = screen.getByTestId("pricebook-picker-input");
    expect(input).toBeTruthy();
    expect(input.getAttribute("placeholder")).toBe("Search chemicals…");
  });

  it("wrapper carries role=combobox + aria-haspopup=listbox", () => {
    render(<_Wrapper />);
    const wrapper = screen.getByTestId("pricebook-picker-wrapper");
    expect(wrapper.getAttribute("role")).toBe("combobox");
    expect(wrapper.getAttribute("aria-haspopup")).toBe("listbox");
    expect(wrapper.getAttribute("aria-expanded")).toBe("false");
  });
});


describe("<PricebookItemPicker /> — search flow", () => {
  it("typing fires GET /api/items?search=… after the debounce", async () => {
    render(<_Wrapper />);
    const input = screen.getByTestId("pricebook-picker-input");
    fireEvent.change(input, { target: { value: "acid" } });
    // Debounce is 250ms real time.
    await waitFor(() => expect(apiGetSpy).toHaveBeenCalled(),
                        { timeout: 1500 });
    const url = apiGetSpy.mock.calls[0][0];
    expect(url).toContain("/items?");
    expect(url).toContain("search=acid");
    expect(url).toContain("active=true");
    expect(url).toContain("limit=50");
  });

  it("empty / whitespace value never fires a request", async () => {
    render(<_Wrapper />);
    const input = screen.getByTestId("pricebook-picker-input");
    fireEvent.change(input, { target: { value: "   " } });
    // Give the debounce a full window to prove NOTHING fires.
    await new Promise((r) => setTimeout(r, 600));
    expect(apiGetSpy).not.toHaveBeenCalled();
  });

  it("results dropdown renders as role=listbox with role=option rows",
    async () => {
      render(<_Wrapper />);
      const input = screen.getByTestId("pricebook-picker-input");
      fireEvent.change(input, { target: { value: "acid" } });
      const listbox = await waitFor(() =>
        screen.getByTestId("pricebook-picker-dropdown"),
      { timeout: 1500 });
      expect(listbox.getAttribute("role")).toBe("listbox");
      // Wait for the fetch → results → render cycle so the row
      // buttons are actually in the DOM (dropdown renders in
      // loading state first).
      const options = await screen.findAllByRole("option",
        undefined, { timeout: 1500 });
      expect(options.length).toBe(_FIXTURE_ROWS.length);
    });
});


describe("<PricebookItemPicker /> — keyboard nav + commit", () => {
  it("ArrowDown moves highlight; ArrowUp moves it back", async () => {
    render(<_Wrapper />);
    const input = screen.getByTestId("pricebook-picker-input");
    fireEvent.change(input, { target: { value: "acid" } });
    
    await waitFor(() =>
      expect(screen.queryByTestId("pricebook-picker-item-0")).toBeTruthy(),
    );
    // Row 0 is active by default (highlight resets on result change).
    expect(
      screen.getByTestId("pricebook-picker-item-0").getAttribute("data-active"),
    ).toBe("true");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(
      screen.getByTestId("pricebook-picker-item-1").getAttribute("data-active"),
    ).toBe("true");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(
      screen.getByTestId("pricebook-picker-item-0").getAttribute("data-active"),
    ).toBe("true");
  });

  it("Enter commits the highlighted row with the FULL item object",
    async () => {
      const onSelect = vi.fn();
      render(<_Wrapper onSelect={onSelect} />);
      const input = screen.getByTestId("pricebook-picker-input");
      fireEvent.change(input, { target: { value: "acid" } });
      
      await waitFor(() =>
        expect(screen.queryByTestId("pricebook-picker-item-0")).toBeTruthy(),
      );
      fireEvent.keyDown(input, { key: "ArrowDown" });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(onSelect).toHaveBeenCalledTimes(1);
      // The FULL row object — id, name, unit_price, category, etc.
      expect(onSelect).toHaveBeenCalledWith(_FIXTURE_ROWS[1]);
    });

  it("Escape closes the dropdown", async () => {
    render(<_Wrapper />);
    const input = screen.getByTestId("pricebook-picker-input");
    fireEvent.change(input, { target: { value: "acid" } });
    
    await waitFor(() =>
      expect(screen.queryByTestId("pricebook-picker-dropdown")).toBeTruthy(),
    );
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByTestId("pricebook-picker-dropdown")).toBeNull(),
    );
  });

  it("clicking a result row also commits", async () => {
    const onSelect = vi.fn();
    render(<_Wrapper onSelect={onSelect} />);
    const input = screen.getByTestId("pricebook-picker-input");
    fireEvent.change(input, { target: { value: "cart" } });
    
    const row = await waitFor(() =>
      screen.getByTestId("pricebook-picker-item-2"),
    );
    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledWith(_FIXTURE_ROWS[2]);
  });
});


describe("<PricebookItemPicker /> — testid namespacing", () => {
  it("honours a custom testidPrefix + inputTestid for K71 backwards-compat",
    () => {
      render(
        <_Wrapper
          testidPrefix="k71-pricebook-search"
          inputTestid="k71-input-item-3-input"
        />,
      );
      expect(
        screen.queryByTestId("k71-input-item-3-input"),
      ).toBeTruthy();
      expect(
        screen.queryByTestId("k71-pricebook-search-wrapper"),
      ).toBeTruthy();
    });

  it("wrapperTestid override wins over the ``${testidPrefix}-wrapper`` default",
    () => {
      // Feb-2026 · Phase PRICEBOOK-UNIFY follow-up — K71 renders one
      // picker per editable row and needs a per-row wrapper testid
      // (``k71-input-item-{index}``) so its legacy tests keep
      // resolving the row's outer combobox by index.
      render(
        <_Wrapper
          testidPrefix="k71-pricebook-search"
          wrapperTestid="k71-input-item-2"
          inputTestid="k71-input-item-2-input"
        />,
      );
      // Custom wrapper testid wins.
      const wrapper = screen.queryByTestId("k71-input-item-2");
      expect(wrapper).toBeTruthy();
      expect(wrapper.getAttribute("role")).toBe("combobox");
      // Legacy default is NOT rendered when the override is set —
      // otherwise a caller mixing default + override would end up
      // with two identical wrappers and duplicate assertions.
      expect(
        screen.queryByTestId("k71-pricebook-search-wrapper"),
      ).toBeNull();
      // The input's own testid follows the ``inputTestid`` override
      // and stays orthogonal to the wrapper override.
      expect(
        screen.queryByTestId("k71-input-item-2-input"),
      ).toBeTruthy();
    });

  it("wrapper defaults to ``${testidPrefix}-wrapper`` when wrapperTestid is omitted",
    () => {
      render(<_Wrapper testidPrefix="k71-pricebook-search" />);
      // Regression guard: unlike ``inputTestid`` which falls through
      // to ``${testidPrefix}-input``, the wrapper fallback keeps the
      // pre-Feb-2026 selector so existing consumers (Estimator,
      // QuoteInvoiceNew) don't need to plumb the new prop.
      expect(
        screen.queryByTestId("k71-pricebook-search-wrapper"),
      ).toBeTruthy();
    });
});
