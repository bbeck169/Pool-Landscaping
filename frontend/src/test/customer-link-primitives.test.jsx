/**
 * Feb-2026 · Clickable Customer Data · unit tests for the three
 * shared primitives (`<PhoneLink>`, `<AddressLink>`, `<CustomerLink>`)
 * plus the `isIOS` platform sniff.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { PhoneLink } from "@/components/customer/PhoneLink";
import { AddressLink } from "@/components/customer/AddressLink";
import { CustomerLink } from "@/components/customer/CustomerLink";
import { isIOS } from "@/services/platform/isIOS";


// ─── isIOS ─────────────────────────────────────────────────────────

describe("isIOS", () => {
  it("returns true for iPhone / iPad / iPod UAs", () => {
    expect(isIOS("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605")).toBe(true);
    expect(isIOS("Mozilla/5.0 (iPad; CPU OS 17_2) AppleWebKit/605")).toBe(true);
    expect(isIOS("Mozilla/5.0 (iPod touch; CPU iPhone 16_6)")).toBe(true);
  });

  it("returns false for Android / desktop / unknown UAs", () => {
    expect(isIOS("Mozilla/5.0 (Linux; Android 14; Pixel 8)")).toBe(false);
    expect(isIOS("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe(false);
    expect(isIOS("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2)")).toBe(false);
    expect(isIOS("")).toBe(false);
    expect(isIOS(undefined)).toBe(false);
  });

  it("reads from navigator when called with no argument", () => {
    const orig = Object.getOwnPropertyDescriptor(window.navigator, "userAgent");
    Object.defineProperty(window.navigator, "userAgent", {
      value: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
      configurable: true,
    });
    try {
      expect(isIOS()).toBe(true);
    } finally {
      if (orig) Object.defineProperty(window.navigator, "userAgent", orig);
    }
  });
});


// ─── PhoneLink ─────────────────────────────────────────────────────

describe("<PhoneLink />", () => {
  it("normalises a US 10-digit number to +1 and dials with tel:", () => {
    render(<PhoneLink phone="(480) 555-0177" />);
    const a = screen.getByTestId("customer-phone-link");
    expect(a.tagName).toBe("A");
    expect(a.getAttribute("href")).toBe("tel:+14805550177");
    // Display fallback formats to the (XXX) XXX-XXXX shape.
    expect(a.textContent).toBe("(480) 555-0177");
    expect(a.getAttribute("aria-label")).toBe("Call (480) 555-0177");
    expect(a.getAttribute("rel")).toBe("noopener");
  });

  it("normalises bare 10-digit US input", () => {
    render(<PhoneLink phone="4805550177" />);
    const a = screen.getByTestId("customer-phone-link");
    expect(a.getAttribute("href")).toBe("tel:+14805550177");
  });

  it("normalises +1XXXXXXXXXX (already E.164)", () => {
    render(<PhoneLink phone="+14805550177" />);
    const a = screen.getByTestId("customer-phone-link");
    expect(a.getAttribute("href")).toBe("tel:+14805550177");
    // Explicit E.164 keeps caller-provided formatting.
    expect(a.textContent).toBe("+14805550177");
  });

  it("keeps international shapes intact and E.164-dials", () => {
    render(<PhoneLink phone="+44 20 7946 0958" />);
    const a = screen.getByTestId("customer-phone-link");
    expect(a.getAttribute("href")).toBe("tel:+442079460958");
    // Non-US: preserve caller-provided formatting for display.
    expect(a.textContent).toBe("+44 20 7946 0958");
  });

  it("renders a plain span (no anchor) for empty or non-numeric input", () => {
    const { rerender } = render(<PhoneLink phone="" />);
    let node = screen.getByTestId("customer-phone-link");
    expect(node.tagName).toBe("SPAN");
    expect(node.getAttribute("data-invalid")).toBe("true");

    rerender(<PhoneLink phone={null} />);
    node = screen.getByTestId("customer-phone-link");
    expect(node.tagName).toBe("SPAN");

    rerender(<PhoneLink phone="no phone on file" />);
    node = screen.getByTestId("customer-phone-link");
    expect(node.tagName).toBe("SPAN");
    expect(node.textContent).toBe("no phone on file");
  });

  it("uses the ``children`` override for display when provided", () => {
    render(<PhoneLink phone="4805550177">Call me</PhoneLink>);
    const a = screen.getByTestId("customer-phone-link");
    expect(a.textContent).toBe("Call me");
    expect(a.getAttribute("href")).toBe("tel:+14805550177");
  });

  it("stops click propagation so row-level onClick does not fire", () => {
    const rowClick = vi.fn();
    render(
      <div onClick={rowClick} data-testid="row">
        <PhoneLink phone="4805550177" />
      </div>,
    );
    fireEvent.click(screen.getByTestId("customer-phone-link"));
    expect(rowClick).not.toHaveBeenCalled();
  });
});


// ─── AddressLink ───────────────────────────────────────────────────

describe("<AddressLink />", () => {
  it("emits a Google Maps URL by default (non-iOS UA)", () => {
    const orig = Object.getOwnPropertyDescriptor(window.navigator, "userAgent");
    Object.defineProperty(window.navigator, "userAgent", {
      value: "Mozilla/5.0 (Linux; Android 14)",
      configurable: true,
    });
    try {
      render(<AddressLink address="123 Palm Way, Peoria, AZ" />);
      const a = screen.getByTestId("customer-address-link");
      expect(a.tagName).toBe("A");
      expect(a.getAttribute("href")).toBe(
        "https://www.google.com/maps/search/?api=1&query="
          + encodeURIComponent("123 Palm Way, Peoria, AZ"),
      );
      expect(a.getAttribute("target")).toBe("_blank");
      expect(a.getAttribute("rel")).toBe("noopener noreferrer");
    } finally {
      if (orig) Object.defineProperty(window.navigator, "userAgent", orig);
    }
  });

  it("emits an Apple Maps URL on iOS UAs", () => {
    const orig = Object.getOwnPropertyDescriptor(window.navigator, "userAgent");
    Object.defineProperty(window.navigator, "userAgent", {
      value: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605",
      configurable: true,
    });
    try {
      render(<AddressLink address="1 Infinite Loop, Cupertino, CA" />);
      const a = screen.getByTestId("customer-address-link");
      expect(a.getAttribute("href")).toBe(
        "https://maps.apple.com/?q="
          + encodeURIComponent("1 Infinite Loop, Cupertino, CA"),
      );
    } finally {
      if (orig) Object.defineProperty(window.navigator, "userAgent", orig);
    }
  });

  it("assembles structured {line1, city, state, zip} objects", () => {
    render(
      <AddressLink
        address={{
          line1: "456 Oak Ln",
          line2: "Unit 3",
          city: "Peoria",
          state: "AZ",
          zip: "85345",
          country: "USA",
        }}
      />,
    );
    const a = screen.getByTestId("customer-address-link");
    const expected = "456 Oak Ln, Unit 3, Peoria, AZ, 85345, USA";
    expect(a.textContent).toBe(expected);
    expect(a.getAttribute("aria-label")).toBe(`Open in maps: ${expected}`);
  });

  it("filters empty / null parts out of structured input", () => {
    render(
      <AddressLink
        address={{ line1: "789 Elm Rd", line2: null, city: "Peoria",
                    state: "", zip: "85345" }}
      />,
    );
    const a = screen.getByTestId("customer-address-link");
    expect(a.textContent).toBe("789 Elm Rd, Peoria, 85345");
  });

  it("renders a plain span for empty / null / whitespace input", () => {
    const { rerender } = render(<AddressLink address="" />);
    let node = screen.getByTestId("customer-address-link");
    expect(node.tagName).toBe("SPAN");
    expect(node.getAttribute("data-invalid")).toBe("true");

    rerender(<AddressLink address={null} />);
    node = screen.getByTestId("customer-address-link");
    expect(node.tagName).toBe("SPAN");

    rerender(<AddressLink address={{ line1: "", city: "" }} />);
    node = screen.getByTestId("customer-address-link");
    expect(node.tagName).toBe("SPAN");
  });

  it("stops click propagation so row-level onClick does not fire", () => {
    const rowClick = vi.fn();
    render(
      <div onClick={rowClick} data-testid="row">
        <AddressLink address="123 Palm Way" />
      </div>,
    );
    // Prevent jsdom from actually navigating.
    fireEvent.click(screen.getByTestId("customer-address-link"),
                     { defaultPrevented: true });
    expect(rowClick).not.toHaveBeenCalled();
  });
});


// ─── CustomerLink ──────────────────────────────────────────────────

describe("<CustomerLink />", () => {
  const _wrap = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>);

  it("renders a Router link to /customers/{id} when id is present", () => {
    _wrap(<CustomerLink customerId="cust-1" name="Alice Adams" />);
    const a = screen.getByTestId("customer-name-link");
    expect(a.tagName).toBe("A");
    expect(a.getAttribute("href")).toBe("/customers/cust-1");
    expect(a.textContent).toBe("Alice Adams");
    expect(a.getAttribute("title")).toBe("Alice Adams");
  });

  it("uses ``children`` when ``name`` is not supplied", () => {
    _wrap(<CustomerLink customerId="cust-1">Bob Baker</CustomerLink>);
    const a = screen.getByTestId("customer-name-link");
    expect(a.textContent).toBe("Bob Baker");
  });

  it("renders a plain span when customerId is missing / empty", () => {
    const { rerender } = _wrap(<CustomerLink name="Cara Cole" />);
    let node = screen.getByTestId("customer-name-link");
    expect(node.tagName).toBe("SPAN");
    expect(node.getAttribute("data-invalid")).toBe("true");
    expect(node.textContent).toBe("Cara Cole");

    rerender(
      <MemoryRouter>
        <CustomerLink customerId="" name="Dan Doe" />
      </MemoryRouter>,
    );
    node = screen.getByTestId("customer-name-link");
    expect(node.tagName).toBe("SPAN");

    rerender(
      <MemoryRouter>
        <CustomerLink customerId={null} name="Eve East" />
      </MemoryRouter>,
    );
    node = screen.getByTestId("customer-name-link");
    expect(node.tagName).toBe("SPAN");
  });

  it("stops click propagation so row-level onClick does not fire", () => {
    const rowClick = vi.fn();
    render(
      <MemoryRouter>
        <div onClick={rowClick} data-testid="row">
          <CustomerLink customerId="cust-1" name="Alice" />
        </div>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("customer-name-link"));
    expect(rowClick).not.toHaveBeenCalled();
  });
});


// ─── Integration: one row rendering all three primitives ───────────

describe("primitive-in-row integration", () => {
  it("row renders name / phone / address with the expected testids", () => {
    // Force a known non-iOS UA so the address anchor lands on Google
    // Maps regardless of earlier tests that flipped ``navigator``.
    Object.defineProperty(window.navigator, "userAgent", {
      value: "Mozilla/5.0 (Linux; Android 14)",
      configurable: true,
    });
    render(
      <MemoryRouter>
        <table>
          <tbody>
            <tr data-testid="row" onClick={() => {}}>
              <td>
                <CustomerLink customerId="c-1" name="Alice Adams" />
              </td>
              <td><PhoneLink phone="(480) 555-0177" /></td>
              <td>
                <AddressLink
                  address={{ line1: "123 Palm Way", city: "Peoria",
                              state: "AZ", zip: "85345" }}
                />
              </td>
            </tr>
          </tbody>
        </table>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("customer-name-link").getAttribute("href"))
      .toBe("/customers/c-1");
    expect(screen.getByTestId("customer-phone-link").getAttribute("href"))
      .toBe("tel:+14805550177");
    expect(screen.getByTestId("customer-address-link").getAttribute("href"))
      .toContain("google.com/maps/search/?api=1&query=");
  });
});
