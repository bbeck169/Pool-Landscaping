/**
 * TD-74 · Feb-2026 — Portal home · "Next visit" overlay removed
 * from the hero image card.
 *
 * Operator-reported symptom: the hero image card on
 * ``/portal/home`` surfaced an inline "Next visit" overlay card
 * (title + tech avatar + scheduled date + "No upcoming visits
 * scheduled" fallback). Below the balance row, the Smart Portal
 * Tiles row ("NEXT POOL SERVICE" / Landscape / Filter Cleaning)
 * already renders the same info with richer per-service
 * eligibility gating — the hero overlay was redundant AND
 * overlapped the TD-73 "Edit profile" green pill at narrow
 * widths.
 *
 * Fix: delete the inline overlay JSX from the hero card. The
 * ``data`` fetch stays (its ``data.customer.first_name`` powers
 * the greeting + the Edit Profile modal). The Smart Tiles row
 * below is untouched.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");
const HOME_SRC = R("../pages/portal/PortalHome.jsx");


describe("TD-74 · Portal home hero · 'Next visit' overlay removed", () => {

  it("hero no longer renders the inline 'Next visit' card", () => {
    // The pre-TD-74 overlay matched this exact JSX pattern inside
    // the hero image card (the ``bg-white/15 backdrop-blur
    // rounded-xl p-4`` tile wrapping an uppercase "Next visit"
    // kicker + title + tech avatar + date).
    expect(HOME_SRC).not.toMatch(
      /<div\s+className="text-xs uppercase tracking-widest opacity-80">\s*Next visit\s*</,
    );
    // The old fallback "No upcoming visits scheduled." copy also
    // gone — operator-ruled the Smart Tiles row below is the
    // only canonical surface for this info.
    expect(HOME_SRC).not.toMatch(/No upcoming visits scheduled\./);
  });

  it("hero no longer references data.next_visit directly", () => {
    // Negative lock — the only ``data.next_visit`` reads were
    // inside the overlay. If a future refactor reintroduces the
    // overlay via a sub-component, this lock has to be updated
    // intentionally.
    expect(HOME_SRC).not.toMatch(/data\.next_visit\b/);
    expect(HOME_SRC).not.toMatch(/data\.next_visit\.title/);
    expect(HOME_SRC).not.toMatch(/data\.next_visit\.scheduled_date/);
    expect(HOME_SRC).not.toMatch(/data\.next_visit\.technician_name/);
  });

  it("the pre-TD-74 `portal-tech-avatar-next` testid is gone from the hero", () => {
    // The avatar inside the hero overlay carried this testid.
    // The ``portal-tech-avatar-last`` testid (last-visit tile
    // further down the page) is UNAFFECTED and still present.
    expect(HOME_SRC).not.toMatch(/portal-tech-avatar-next/);
    // Positive — the last-visit avatar still exists (regression
    // guard against accidental over-removal).
    expect(HOME_SRC).toMatch(/portal-tech-avatar-last/);
  });

  it("hero keeps the greeting + edit-profile pill (unchanged)", () => {
    // Hero shell still renders the ``Hi, {first} 👋`` greeting
    // and the TD-73 green Edit-profile pill.
    expect(HOME_SRC).toMatch(/Hi,\s*\{first\}/);
    expect(HOME_SRC).toMatch(/data-testid=\{?["']portal-hero-edit-profile-btn["']\}?/);
  });

  it("Smart Portal Tiles row (operator-canonical surface) is untouched", () => {
    // The "NEXT POOL SERVICE" / Landscape / Filter Cleaning tile
    // row — different data source (``/portal/dashboard/next-visits``,
    // plural, per-service-type) and different render path
    // (``NextVisitTile`` sub-component). Pin it so operator
    // scope-boundary ("keep this intact") stays enforced.
    expect(HOME_SRC).toMatch(/data-testid="next-visits-tile-row"/);
    expect(HOME_SRC).toMatch(/data-testid="next-visits-skeleton"/);
    expect(HOME_SRC).toMatch(/<NextVisitTile\b/);
  });

  it("`data` fetch stays — operator-ruled 'keep anything shared'", () => {
    // The ``data.customer.first_name`` chain still powers the
    // greeting + the Edit Profile modal (first_name / last_name
    // / phone / email seed). Confirm the fetch isn't accidentally
    // removed as part of the overlay cleanup.
    expect(HOME_SRC).toMatch(/api\.get\(["']\/portal\/home["']\)\.then\(setData\)/);
    expect(HOME_SRC).toMatch(/data\?\.customer\?\.first_name/);
  });

});
