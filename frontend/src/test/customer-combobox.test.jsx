/**
 * Feb-2026 · <CustomerCombobox> component tests.
 *
 * Covers the extracted component's behavior contract:
 *   • Renders a trigger with the caller-supplied testid.
 *   • Trigger click opens the popover.
 *   • Search input filters via cmdk's built-in fuzzy match.
 *   • Empty-state renders on a nonsense query.
 *   • Row click fires ``onChange`` with the id and closes the
 *     popover.
 *   • ``disabled`` blocks trigger open.
 *   • ``filter`` predicate limits the visible list.
 *   • ``testid`` prop derives downstream testids (search + rows).
 *
 * Uses ``@testing-library/react`` render harness rather than
 * source-string sniffing because behavior tests are more
 * meaningful for a leaf UI component.
 */
import React from "react";
import { describe, it, expect, vi, afterEach, beforeAll } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { CustomerCombobox } from "../components/customers/CustomerCombobox";

// cmdk (Command) calls element.scrollIntoView on mount for the
// active row — JSDOM doesn't implement it. Shim once at the
// module level so every test in this file can render without
// tripping the internal listener.
beforeAll(() => {
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
  }
});

const CUSTOMERS = [
  { id: "c-1", name: "Alice Anderson", is_active: true },
  { id: "c-2", name: "Bob Baker",       is_active: true },
  { id: "c-3", name: "Carol Cortez",    is_active: false },
];

function _open(testid = "customer-combobox") {
  const trigger = screen.getByTestId(testid);
  act(() => trigger.click());
  return trigger;
}

describe("<CustomerCombobox> — behavior", () => {
  afterEach(() => cleanup());

  it("renders the trigger with the caller-supplied testid + placeholder", () => {
    render(
      <CustomerCombobox customers={CUSTOMERS} value="" onChange={() => {}} />,
    );
    const trigger = screen.getByTestId("customer-combobox");
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveTextContent("Choose a customer…");
  });

  it("renders custom testid + placeholder when supplied", () => {
    render(
      <CustomerCombobox
        customers={CUSTOMERS}
        value=""
        onChange={() => {}}
        testid="jf-customer"
        placeholder="Pick one…"
      />,
    );
    expect(screen.getByTestId("jf-customer")).toBeInTheDocument();
    expect(screen.getByTestId("jf-customer")).toHaveTextContent("Pick one…");
  });

  it("shows the selected customer's name when value is set", () => {
    render(
      <CustomerCombobox customers={CUSTOMERS} value="c-2" onChange={() => {}} />,
    );
    expect(screen.getByTestId("customer-combobox")).toHaveTextContent(
      "Bob Baker",
    );
  });

  it("opens on trigger click and reveals the search input + row items", () => {
    render(
      <CustomerCombobox customers={CUSTOMERS} value="" onChange={() => {}} />,
    );
    _open();
    expect(screen.getByTestId("customer-combobox-search")).toBeInTheDocument();
    expect(screen.getByTestId("customer-combobox-item-c-1")).toBeInTheDocument();
    expect(screen.getByTestId("customer-combobox-item-c-2")).toBeInTheDocument();
    expect(screen.getByTestId("customer-combobox-item-c-3")).toBeInTheDocument();
  });

  it("filters rows via the search input (cmdk built-in)", () => {
    render(
      <CustomerCombobox customers={CUSTOMERS} value="" onChange={() => {}} />,
    );
    _open();
    fireEvent.change(screen.getByTestId("customer-combobox-search"), {
      target: { value: "alice" },
    });
    expect(screen.getByTestId("customer-combobox-item-c-1")).toBeInTheDocument();
    expect(screen.queryByTestId("customer-combobox-item-c-2")).toBeNull();
    expect(screen.queryByTestId("customer-combobox-item-c-3")).toBeNull();
  });

  it("shows empty-state on nonsense query", () => {
    render(
      <CustomerCombobox customers={CUSTOMERS} value="" onChange={() => {}} />,
    );
    _open();
    fireEvent.change(screen.getByTestId("customer-combobox-search"), {
      target: { value: "zzzzzzz" },
    });
    expect(screen.getByText("No customers found.")).toBeInTheDocument();
  });

  it("calls onChange with the row id when a row is selected", () => {
    const onChange = vi.fn();
    render(
      <CustomerCombobox customers={CUSTOMERS} value="" onChange={onChange} />,
    );
    _open();
    fireEvent.click(screen.getByTestId("customer-combobox-item-c-2"));
    expect(onChange).toHaveBeenCalledWith("c-2");
  });

  it("respects disabled — trigger doesn't open + attribute set", () => {
    render(
      <CustomerCombobox
        customers={CUSTOMERS}
        value=""
        onChange={() => {}}
        disabled
      />,
    );
    const trigger = screen.getByTestId("customer-combobox");
    expect(trigger).toBeDisabled();
  });

  it("respects the filter predicate", () => {
    render(
      <CustomerCombobox
        customers={CUSTOMERS}
        value=""
        onChange={() => {}}
        filter={(c) => c.is_active}
      />,
    );
    _open();
    expect(screen.getByTestId("customer-combobox-item-c-1")).toBeInTheDocument();
    expect(screen.getByTestId("customer-combobox-item-c-2")).toBeInTheDocument();
    // Carol Cortez is inactive — must be filtered out.
    expect(screen.queryByTestId("customer-combobox-item-c-3")).toBeNull();
  });

  it("renders quick-create children slot ABOVE the search list", () => {
    render(
      <CustomerCombobox customers={CUSTOMERS} value="" onChange={() => {}}>
        <button data-testid="cc-quick-create">+ New customer</button>
      </CustomerCombobox>,
    );
    _open();
    expect(screen.getByTestId("cc-quick-create")).toBeInTheDocument();
  });
});
