/**
 * Phase 28 · Feb-2026 — Admin CustomerDetail identity header reposition.
 *
 * The 10-field identity card (customer name + address + phone +
 * email + pool + gate code + tags + VIP badge + Active toggle +
 * Customer-Since) was MOVED from its post-tabs position to render
 * ABOVE the Phase-20 command strip so the customer's identity is
 * the first thing visible after the breadcrumb.  Chassis was
 * recoloured to Phase-27 dark-navy tokens for visual coherence
 * with the rest of the admin profile.
 *
 * Source-inspection pattern — same style as the Phase 24 / 27
 * regression tests — no React mount, no provider plumbing.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const SRC = readFileSync(resolve(
  __dirname, "../pages/customers/CustomerDetail.jsx"), "utf8");


// Anchor the identity-card slice via its ``cd-identity-header``
// testid (new in Phase 28) + the next-sibling comment that marks
// the start of the Portal-Access / Top-action-stack region.  Both
// are stable sentinels that survive future unrelated edits.
const ID_IDX = SRC.indexOf('data-testid="cd-identity-header"');
const ID_WRAPPER_START = SRC.lastIndexOf("<div", ID_IDX);
const NEXT_SIBLING_IDX = SRC.indexOf(
  "{/* Feb-2026 · Top action stack", ID_IDX);
const ID_SLICE = SRC.slice(ID_WRAPPER_START, NEXT_SIBLING_IDX);


describe("Phase 28 · identity header renders ABOVE the Phase-20 command strip", () => {
  it("source order — Header card precedes cd-command-strip", () => {
    const headerCardIdx = SRC.indexOf("{/* Header card */}");
    const stripIdx = SRC.indexOf('data-testid="cd-command-strip"');
    const tabsStripIdx = SRC.indexOf('data-testid="cd-command-strip-tabs"');
    expect(headerCardIdx).toBeGreaterThan(-1);
    expect(stripIdx).toBeGreaterThan(-1);
    expect(tabsStripIdx).toBeGreaterThan(-1);
    expect(headerCardIdx).toBeLessThan(stripIdx);
    expect(headerCardIdx).toBeLessThan(tabsStripIdx);
  });

  it("source order — Header card precedes the Phase-27 KPI tile grid + Quick Actions grid", () => {
    const headerCardIdx = SRC.indexOf("{/* Header card */}");
    const kpiIdx = SRC.indexOf("<KPITileGrid");
    const qaIdx = SRC.indexOf("<QuickActionTileGrid");
    expect(headerCardIdx).toBeGreaterThan(-1);
    expect(headerCardIdx).toBeLessThan(kpiIdx);
    expect(headerCardIdx).toBeLessThan(qaIdx);
  });

  it("source order — Header card renders immediately after the 'All customers' back button", () => {
    const backBtnIdx = SRC.indexOf("All customers");
    const headerCardIdx = SRC.indexOf("{/* Header card */}");
    expect(backBtnIdx).toBeGreaterThan(-1);
    expect(backBtnIdx).toBeLessThan(headerCardIdx);
    // No other render block should sit between the back button
    // and the Header card (except whitespace / blank lines).
    const between = SRC.slice(
      SRC.indexOf("All customers") + "All customers".length, headerCardIdx);
    expect(between).not.toContain("<PortalInviteQuickAction");
    expect(between).not.toContain("cd-command-strip");
  });
});


describe("Phase 28 · all 10 identity fields present in the Header card", () => {
  it("customer name H1 (``customer-detail-inline-h1``)", () => {
    expect(ID_SLICE).toContain('data-testid="customer-detail-inline-h1"');
  });

  it("address rendering — primary-property address link + <CustomerGeocodeInfo>", () => {
    // Phase 28 · address is rendered as an inline anchor to Google
    // Maps directions (``customer-primary-address`` testid + a
    // ``<MapPin>`` icon) — NOT via a shared ``<AddressLink>``
    // component.  The sibling ``<CustomerGeocodeInfo />`` renders
    // the geocode / lat-lng line directly below.
    expect(ID_SLICE).toContain('data-testid="customer-primary-address"');
    expect(ID_SLICE).toContain("<CustomerGeocodeInfo");
  });

  it("phone / mobiles tile (``customer-mobiles-display``)", () => {
    expect(ID_SLICE).toContain('testid: "customer-mobiles-display"');
  });

  it("email tile (``customer-emails-display``)", () => {
    expect(ID_SLICE).toContain('testid: "customer-emails-display"');
  });

  it("pool tile (``customer-pool-gallons-display``)", () => {
    expect(ID_SLICE).toContain('testid: "customer-pool-gallons-display"');
  });

  it("gate code tile (``cd-stat-gate-code``)", () => {
    expect(ID_SLICE).toContain('testid: "cd-stat-gate-code"');
  });

  it("tags picker (<CustomerTagPicker>)", () => {
    expect(ID_SLICE).toContain("<CustomerTagPicker");
  });

  it("VIP toggle (``customer-vip-toggle``) + toggleVip handler reference preserved", () => {
    expect(ID_SLICE).toContain('data-testid="customer-vip-toggle"');
    expect(ID_SLICE).toMatch(
      /onClick=\{\(\)\s*=>\s*toggleVip\(!customer\.is_vip\)\}/);
    expect(ID_SLICE).toMatch(/customer\.is_vip\s*\?\s*"VIP"\s*:\s*"Flag as VIP"/);
  });

  it("Active toggle (<ActivationControl>) wiring preserved byte-for-byte", () => {
    expect(ID_SLICE).toContain("<ActivationControl");
    expect(ID_SLICE).toMatch(/customer=\{customer\}/);
    expect(ID_SLICE).toMatch(
      /onOptimisticFlip=\{\(next\)\s*=>\s*setCustomer/);
  });

  it("Customer-since chip (``customer-since-label``)", () => {
    expect(ID_SLICE).toContain('data-testid="customer-since-label"');
    expect(ID_SLICE).toMatch(/Customer since \$\{new Date\(customer\.customer_since\)/);
  });
});


describe("Phase 28 · dark navy chassis tokens", () => {
  it("outer chassis pins ``#03002e`` background + ``#1E293B`` border + light text", () => {
    // Grep the exact inline style string on the identity-card
    // wrapper — byte-strict so future unrelated edits can't
    // silently drift the chassis back to light theme.
    expect(ID_SLICE).toMatch(
      /style=\{\{\s*backgroundColor:\s*"#03002e",\s*border:\s*"1px solid #1E293B",\s*color:\s*"#F1F5F9"\s*\}\}/,
    );
  });

  it("H1 pins ``#F1F5F9`` (Phase-27 near-white) for readability on dark chassis", () => {
    const h1Idx = ID_SLICE.indexOf('data-testid="customer-detail-inline-h1"');
    // Look backward from the testid to the enclosing <h1 ...> tag.
    const h1OpenIdx = ID_SLICE.lastIndexOf("<h1", h1Idx);
    const h1Slice = ID_SLICE.slice(h1OpenIdx, h1Idx);
    expect(h1Slice).toMatch(/color:\s*"#F1F5F9"/);
  });

  it("stat-tile inner bg uses ``#0a0940`` (slightly lighter navy for depth)", () => {
    expect(ID_SLICE).toMatch(/backgroundColor:\s*"#0a0940"/);
    // Phase-28 recolour also updates the stat-tile labels from
    // ``colors.muted`` → ``rgba(255,255,255,0.7)`` for contrast.
    expect(ID_SLICE).toMatch(/rgba\(255,255,255,0\.7\)/);
  });

  it("the pre-Phase-28 light tokens on the chassis are GONE", () => {
    // Regression lock — a future refactor that reverts to
    // ``colors.surface`` + ``colors.border`` on the identity
    // chassis would silently un-dark the card.  Pin the gap.
    expect(ID_SLICE).not.toMatch(
      /style=\{\{\s*backgroundColor:\s*colors\.surface,\s*border:\s*`1px solid \$\{colors\.border\}`/,
    );
  });
});


describe("Phase 28 · regression locks — Phase 20 / 22 / 27 contracts preserved", () => {
  it("Phase 20 testids all present in locked relative order", () => {
    const ids = ["cd-command-strip", "cd-action-row",
                   "cd-command-strip-tabs", "cd-tabs-row",
                   "cd-tabs-dropdown-shell"];
    let cursor = -1;
    for (const id of ids) {
      const idx = SRC.indexOf(`data-testid="${id}"`);
      expect(idx, `missing Phase-20 testid: ${id}`).toBeGreaterThan(-1);
      expect(idx, `Phase-20 testid out of order: ${id}`).toBeGreaterThan(cursor);
      cursor = idx;
    }
    // The ``CustomerActionDropdowns`` component tag + the
    // ``ResponsiveTabs`` component tag still live inside the
    // cd-tabs-row block.
    const tabsRowIdx = SRC.indexOf('data-testid="cd-tabs-row"');
    const tabsRowEnd = SRC.indexOf(
      "{/* Feb-2026 · Tabs — the standalone", tabsRowIdx);
    const tabsRowSlice = SRC.slice(tabsRowIdx, tabsRowEnd);
    expect(tabsRowSlice).toContain("<CustomerActionDropdowns");
    expect(tabsRowSlice).toContain("<ResponsiveTabs");
  });

  it("Phase 22 skeleton loader testid still present + still gates on !customer", () => {
    expect(SRC).toContain('data-testid="customer-detail-skeleton"');
    // Guard — the loader must still fire during the no-customer
    // render path.  Phase-28 moved the identity card so the file
    // grew; split the guard into two independent proximity checks
    // rather than one hard-bounded regex.
    const notCustomerIdx = SRC.indexOf("if (!customer) {");
    const skeletonTestidIdx = SRC.indexOf(
      'data-testid="customer-detail-skeleton"', notCustomerIdx);
    expect(notCustomerIdx).toBeGreaterThan(-1);
    expect(skeletonTestidIdx).toBeGreaterThan(notCustomerIdx);
    // The skeleton testid lands inside the ``if (!customer)``
    // block — within a 3000-char window of the guard.
    expect(skeletonTestidIdx - notCustomerIdx).toBeLessThan(3000);
  });

  it("Phase 27 KPI tile grid + Quick Actions grid still render BELOW cd-tabs-row", () => {
    const tabsRowIdx = SRC.indexOf('data-testid="cd-tabs-row"');
    const kpiIdx = SRC.indexOf("<KPITileGrid");
    const qaIdx  = SRC.indexOf("<QuickActionTileGrid");
    expect(tabsRowIdx).toBeLessThan(kpiIdx);
    expect(kpiIdx).toBeLessThan(qaIdx);
  });

  it("Phase 27 dynamic colour math constants unchanged (CD_DANGER_BG + CD_SUCCESS_BG)", () => {
    expect(SRC).toMatch(/CD_DANGER_BG\s*=\s*"#7F1D1D"/);
    expect(SRC).toMatch(/CD_SUCCESS_BG\s*=\s*"#064E3B"/);
  });
});


describe("Phase 28 · 2 render variants — chassis stays dark across any field permutation", () => {
  it("render variant 1: ``is_vip = true`` — VIP chip toggle logic preserved on dark chassis", () => {
    // The VIP chip is an inline button that flips its own
    // background between ``#FEF3C7`` (vip amber) and
    // ``colors.surfaceSecondary`` (non-vip neutral).  Phase 28
    // did NOT touch this logic — the amber state must still
    // appear on dark chassis (yellow-on-navy, high contrast).
    expect(ID_SLICE).toMatch(/customer\.is_vip\s*\?\s*"#FEF3C7"/);
  });

  it("render variant 2: ``is_vip = false`` — Flag-as-VIP neutral state preserved", () => {
    // Same ternary, non-vip branch.
    expect(ID_SLICE).toMatch(/customer\.is_vip\s*\?[\s\S]{0,120}:\s*colors\.surfaceSecondary/);
  });
});
