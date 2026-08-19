/**
 * Feb-2026 · Customer profile — primary-property address line under
 * the name. Source-inspection + pure-helper tests (same pattern as
 * ``customer-detail-action-row.test.jsx``).
 *
 * Locks in:
 *   1. ``getPrimaryPropertyAddress`` selects the ``is_primary`` row,
 *      falls back to first-in-list, and formats a clean one-line
 *      ``street, city, state zip`` string (no double commas / trailing
 *      commas when parts are missing).
 *   2. When no property has a usable address, returns ``null`` (the
 *      page renders the muted "No address on file" placeholder).
 *   3. The CustomerDetail page renders the address between the h1
 *      row and the chips row, with the Google Maps directions link.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

import { getPrimaryPropertyAddress } from "../pages/customers/CustomerDetail.jsx";


const PAGE_PATH = resolve(__dirname, "../pages/customers/CustomerDetail.jsx");
const pageSrc = readFileSync(PAGE_PATH, "utf8");


describe("Customer primary-property address — helper", () => {
  it("picks the is_primary property when one is flagged", () => {
    const props = [
      { id: "p1", sort_order: 0, address: { line1: "1 First St", city: "A", state: "AZ", postal_code: "10000" } },
      { id: "p2", sort_order: 1, is_primary: true, address: { line1: "22 Real Rd", city: "Real", state: "AZ", postal_code: "85383" } },
    ];
    expect(getPrimaryPropertyAddress(props)).toBe("22 Real Rd, Real, AZ 85383");
  });

  it("falls back to the first property when no is_primary flag", () => {
    const props = [
      { id: "p1", address: { line1: "3 Alpha Ave", city: "Alpha", state: "CA", postal_code: "90210" } },
      { id: "p2", address: { line1: "4 Beta Blvd" } },
    ];
    expect(getPrimaryPropertyAddress(props)).toBe("3 Alpha Ave, Alpha, CA 90210");
  });

  it("skips empty parts cleanly — no double commas, no trailing comma", () => {
    expect(getPrimaryPropertyAddress([{ address: { line1: "Line only" } }]))
      .toBe("Line only");
    expect(getPrimaryPropertyAddress([{ address: { city: "Peoria", state: "AZ" } }]))
      .toBe("Peoria, AZ");
    expect(getPrimaryPropertyAddress([{ address: { state: "AZ", postal_code: "85383" } }]))
      .toBe("AZ 85383");
  });

  it("returns null when no properties or all addresses empty", () => {
    expect(getPrimaryPropertyAddress([])).toBeNull();
    expect(getPrimaryPropertyAddress(null)).toBeNull();
    expect(getPrimaryPropertyAddress(undefined)).toBeNull();
    expect(getPrimaryPropertyAddress([{ address: {} }])).toBeNull();
    expect(getPrimaryPropertyAddress([{}])).toBeNull();
  });

  it("also honors the legacy ``primary: true`` flag (older records)", () => {
    const props = [
      { address: { line1: "First" } },
      { primary: true, address: { line1: "Legacy primary" } },
    ];
    expect(getPrimaryPropertyAddress(props)).toBe("Legacy primary");
  });
});


describe("Customer primary-property address — page wiring", () => {
  it("fetches customer properties alongside the customer + jobs", () => {
    expect(pageSrc).toMatch(/api\.get\(`\/customers\/\$\{id\}\/properties`\)/);
    expect(pageSrc).toMatch(/setProperties\(/);
  });

  it("renders the address element between the h1 row and the chips row", () => {
    const h1Idx  = pageSrc.indexOf('className="text-3xl font-bold"');
    const chipsIdx = pageSrc.indexOf('<CustomerTagPicker');
    const addrIdx = pageSrc.indexOf('data-testid="customer-primary-address"');
    expect(h1Idx).toBeGreaterThan(-1);
    expect(chipsIdx).toBeGreaterThan(-1);
    expect(addrIdx).toBeGreaterThan(h1Idx);
    expect(addrIdx).toBeLessThan(chipsIdx);
  });

  it("renders the muted empty state with its own testid", () => {
    expect(pageSrc).toContain('data-testid="customer-primary-address-empty"');
    expect(pageSrc).toContain("No address on file");
  });

  it("clickable path builds a Google Maps directions link + safe target/rel", () => {
    expect(pageSrc).toContain("google.com/maps/dir/?api=1&destination=");
    expect(pageSrc).toMatch(/target="_blank"/);
    expect(pageSrc).toMatch(/rel="noopener noreferrer"/);
  });

  it("uses a lucide MapPin icon (already imported at the top)", () => {
    // The icon is already imported at line 3; assert the address
    // element actually renders one.
    const addrIdx = pageSrc.indexOf('data-testid="customer-primary-address"');
    const addrBlock = pageSrc.slice(addrIdx - 1200, addrIdx + 1200);
    expect(addrBlock).toMatch(/<MapPin\s+size=/);
  });

  it("truncates long addresses with ellipsis + ``title`` tooltip", () => {
    const addrIdx = pageSrc.indexOf('data-testid="customer-primary-address"');
    const addrBlock = pageSrc.slice(addrIdx - 400, addrIdx + 2000);
    expect(addrBlock).toContain('className="truncate"');
    expect(addrBlock).toMatch(/title=\{oneLine\}|title="No address on file"/);
  });
});
