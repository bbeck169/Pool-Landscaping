/**
 * Phase P14 · Feb-2026 · Item 5 — Interactive components smoke tests.
 *
 * Mounts each of the three reusable components with a matrix of
 * valid, missing, and malformed inputs to lock in the fallback
 * shape (plain <span>, no anchor) that the row-click hijack
 * mitigation depends on.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { ClickableName } from "@/components/interactive/ClickableName";
import { ClickablePhone } from "@/components/interactive/ClickablePhone";
import { ClickableAddress } from "@/components/interactive/ClickableAddress";
import { coerceAddressToStr } from "@/utils/address";


// ─── ClickableName ─────────────────────────────────────────────────
describe("Phase P14 · ClickableName", () => {
  const wrap = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>);

  it("customer with id + name renders as <Link> to /customers/:id", () => {
    wrap(<ClickableName
      id="c-1" name="Alpha Corp"
      entityType="customer"
      testid="cn-a"
    />);
    const el = screen.getByTestId("cn-a");
    expect(el.tagName).toBe("A");
    expect(el.getAttribute("href")).toBe("/customers/c-1");
    expect(el.textContent).toBe("Alpha Corp");
  });

  it("technician links to /technician/:id (singular per App.js route)", () => {
    wrap(<ClickableName
      id="t-1" name="Mike"
      entityType="technician"
      testid="cn-t"
    />);
    expect(screen.getByTestId("cn-t").getAttribute("href")).toBe("/technician/t-1");
  });

  it("user entityType renders plain <span> (no /users/:id route today)", () => {
    wrap(<ClickableName
      id="u-1" name="Someone"
      entityType="user"
      testid="cn-u"
    />);
    const el = screen.getByTestId("cn-u");
    expect(el.tagName).toBe("SPAN");
    expect(el.textContent).toBe("Someone");
  });

  it("missing id → plain <span>", () => {
    wrap(<ClickableName
      id={null} name="Ghost"
      entityType="customer"
      testid="cn-g"
    />);
    expect(screen.getByTestId("cn-g").tagName).toBe("SPAN");
  });

  it("empty name → plain <span> with empty text", () => {
    wrap(<ClickableName
      id="c-1" name=""
      entityType="customer"
      testid="cn-e"
    />);
    expect(screen.getByTestId("cn-e").tagName).toBe("SPAN");
    expect(screen.getByTestId("cn-e").textContent).toBe("");
  });

  it("unknown entityType → plain <span> (safe fallback)", () => {
    wrap(<ClickableName
      id="x-1" name="Whatever"
      entityType="alien"
      testid="cn-x"
    />);
    expect(screen.getByTestId("cn-x").tagName).toBe("SPAN");
  });
});


// ─── ClickablePhone ────────────────────────────────────────────────
describe("Phase P14 · ClickablePhone", () => {
  it("normalizes ``(555) 123-4567`` to ``tel:5551234567``", () => {
    render(<ClickablePhone phone="(555) 123-4567" testid="cp-1" />);
    const el = screen.getByTestId("cp-1");
    expect(el.tagName).toBe("A");
    expect(el.getAttribute("href")).toBe("tel:5551234567");
    // Visible text unchanged.
    expect(el.textContent).toBe("(555) 123-4567");
  });

  it("preserves a leading + (E.164)", () => {
    render(<ClickablePhone phone="+1 (555) 987-6543" testid="cp-2" />);
    expect(screen.getByTestId("cp-2").getAttribute("href")).toBe("tel:+15559876543");
  });

  it("empty / whitespace → plain <span>", () => {
    render(<ClickablePhone phone="   " testid="cp-e" />);
    expect(screen.getByTestId("cp-e").tagName).toBe("SPAN");
  });

  it("no-digits string → plain <span>", () => {
    render(<ClickablePhone phone="call me" testid="cp-nd" />);
    expect(screen.getByTestId("cp-nd").tagName).toBe("SPAN");
  });

  it("null phone → plain <span> (empty text)", () => {
    render(<ClickablePhone phone={null} testid="cp-null" />);
    expect(screen.getByTestId("cp-null").tagName).toBe("SPAN");
  });

  it("click stops propagation so a row-nav parent isn't hijacked", () => {
    const parentClick = vi.fn();
    render(
      <div onClick={parentClick} data-testid="row">
        <ClickablePhone phone="555-1234" testid="cp-stop" />
      </div>
    );
    fireEvent.click(screen.getByTestId("cp-stop"));
    expect(parentClick).not.toHaveBeenCalled();
  });
});


// ─── ClickableAddress ──────────────────────────────────────────────
describe("Phase P14 · ClickableAddress", () => {
  it("string address renders <a href='...maps.google.com...'>", () => {
    render(<ClickableAddress
      address="42 Palm Ln, Chandler, AZ 85224"
      testid="ca-1"
    />);
    const el = screen.getByTestId("ca-1");
    expect(el.tagName).toBe("A");
    expect(el.getAttribute("target")).toBe("_blank");
    expect(el.getAttribute("rel")).toContain("noopener");
    expect(el.getAttribute("href")).toContain(
      "google.com/maps/search/?api=1&query=",
    );
    expect(el.getAttribute("href")).toContain(
      encodeURIComponent("42 Palm Ln, Chandler, AZ 85224"),
    );
  });

  it("dict-shaped address is coerced to a string via utils/address", () => {
    render(<ClickableAddress
      address={{ street: "500 5th Ave", city: "Scottsdale",
                  state: "AZ", zip: "85251" }}
      testid="ca-2"
    />);
    const el = screen.getByTestId("ca-2");
    expect(el.tagName).toBe("A");
    expect(el.textContent).toBe("500 5th Ave, Scottsdale, AZ 85251");
  });

  it("formatted key wins on the dict fast-path", () => {
    render(<ClickableAddress
      address={{ formatted: "77 W Adams, Phoenix, AZ 85003",
                  street: "wrong-street" }}
      testid="ca-3"
    />);
    expect(screen.getByTestId("ca-3").textContent)
      .toBe("77 W Adams, Phoenix, AZ 85003");
  });

  it("empty / null address → plain <span>", () => {
    render(<ClickableAddress address={null} testid="ca-null" />);
    expect(screen.getByTestId("ca-null").tagName).toBe("SPAN");
  });

  it("empty dict → plain <span>", () => {
    render(<ClickableAddress address={{}} testid="ca-empty" />);
    expect(screen.getByTestId("ca-empty").tagName).toBe("SPAN");
  });

  it("click stops propagation (row-nav mitigation)", () => {
    const parentClick = vi.fn();
    render(
      <div onClick={parentClick} data-testid="row">
        <ClickableAddress address="1 Main St" testid="ca-stop" />
      </div>
    );
    fireEvent.click(screen.getByTestId("ca-stop"));
    expect(parentClick).not.toHaveBeenCalled();
  });
});


// ─── utils/address unit tests ──────────────────────────────────────
describe("Phase P14 · utils/address · coerceAddressToStr", () => {
  it("null / undefined → empty", () => {
    expect(coerceAddressToStr(null)).toBe("");
    expect(coerceAddressToStr(undefined)).toBe("");
  });

  it("string is trimmed", () => {
    expect(coerceAddressToStr("  a  ")).toBe("a");
  });

  it("dict with formatted (has comma) wins", () => {
    expect(coerceAddressToStr({ formatted: "a, b", line1: "wrong" }))
      .toBe("a, b");
  });

  it("dict concat: street + city + state + zip", () => {
    expect(coerceAddressToStr({
      street: "1 Elm", city: "Mesa", state: "AZ", zip: "85201",
    })).toBe("1 Elm, Mesa, AZ 85201");
  });

  it("dict concat with postal_code alias", () => {
    expect(coerceAddressToStr({
      street: "1 Elm", city: "Mesa", state: "AZ", postal_code: "85201",
    })).toBe("1 Elm, Mesa, AZ 85201");
  });

  it("dict with only street", () => {
    expect(coerceAddressToStr({ street: "77 W Adams" })).toBe("77 W Adams");
  });

  it("non-dict non-string → empty", () => {
    expect(coerceAddressToStr(123)).toBe("");
    expect(coerceAddressToStr([1, 2, 3])).toBe("");
    expect(coerceAddressToStr(true)).toBe("");
  });
});
