/**
 * Feb-2026 · Consolidated Settings Hub — layout + sidebar tests.
 *
 * Verifies that:
 *   1. The 4 hub sections (general / branding / integrations /
 *      social) render as sidebar navlinks with their canonical
 *      testids and paths.
 *   2. No `migration` or `team` entries are rendered (dropped per
 *      user brief — no dead sidebar entries).
 *   3. The active-state semantics highlight the matching section
 *      based on the current pathname.
 *   4. The hub landing at `/settings` and `/settings/general`
 *      renders the `SettingsGeneral` card with quick-link tiles.
 *
 * We render the hub with `MemoryRouter` so the `NavLink`s resolve
 * without a real router.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import SettingsHub, { SettingsGeneral } from "@/layouts/SettingsHub";

function renderHubAt(pathname) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <Routes>
        <Route path="settings" element={<SettingsHub />}>
          <Route index element={<SettingsGeneral />} />
          <Route path="general" element={<SettingsGeneral />} />
          <Route path="branding" element={<div data-testid="stub-branding">B</div>} />
          <Route path="integrations" element={<div data-testid="stub-integrations">I</div>} />
          <Route path="social" element={<div data-testid="stub-social">S</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("SettingsHub · sidebar structure", () => {
  it("renders the hub shell with the four canonical sections", () => {
    renderHubAt("/settings");
    expect(screen.getByTestId("settings-hub")).toBeTruthy();
    expect(screen.getByTestId("settings-hub-title").textContent).toMatch(/Settings/);
    expect(screen.getByTestId("settings-tab-general")).toBeTruthy();
    expect(screen.getByTestId("settings-tab-branding")).toBeTruthy();
    expect(screen.getByTestId("settings-tab-integrations")).toBeTruthy();
    expect(screen.getByTestId("settings-tab-social")).toBeTruthy();
  });

  it("does NOT render legacy `migration` or `team` sidebar entries", () => {
    renderHubAt("/settings");
    // These were dropped Feb-2026 per user brief — no dead tabs.
    expect(screen.queryByTestId("settings-tab-migration")).toBeNull();
    expect(screen.queryByTestId("settings-tab-team")).toBeNull();
  });

  it("each sidebar link points to its canonical `/settings/<key>` route", () => {
    renderHubAt("/settings");
    const asHref = (id) => screen.getByTestId(id).getAttribute("href");
    expect(asHref("settings-tab-general")).toBe("/settings/general");
    expect(asHref("settings-tab-branding")).toBe("/settings/branding");
    expect(asHref("settings-tab-integrations")).toBe("/settings/integrations");
    expect(asHref("settings-tab-social")).toBe("/settings/social");
  });
});

describe("SettingsHub · active-state semantics", () => {
  it("landing `/settings` marks the General tab active", () => {
    renderHubAt("/settings");
    const general = screen.getByTestId("settings-tab-general");
    expect(general.getAttribute("data-active")).toBe("1");
  });

  it("`/settings/branding` marks the Branding tab active", () => {
    renderHubAt("/settings/branding");
    const branding = screen.getByTestId("settings-tab-branding");
    expect(branding.getAttribute("data-active")).toBe("1");
    // Others stay inactive.
    expect(screen.getByTestId("settings-tab-general")
      .getAttribute("data-active")).toBe("0");
    expect(screen.getByTestId("settings-tab-social")
      .getAttribute("data-active")).toBe("0");
  });

  it("`/settings/social` marks the Social tab active + renders the Social outlet", () => {
    renderHubAt("/settings/social");
    expect(screen.getByTestId("settings-tab-social")
      .getAttribute("data-active")).toBe("1");
    expect(screen.getByTestId("stub-social")).toBeTruthy();
  });
});

describe("SettingsGeneral · landing content", () => {
  it("renders the General card with quick-link tiles at `/settings`", () => {
    renderHubAt("/settings");
    expect(screen.getByTestId("settings-general-card")).toBeTruthy();
    // The General card ships a handful of quick-link tiles — at
    // least one of them must be present and clickable.
    expect(screen.getByTestId("settings-general-link-tenant")).toBeTruthy();
    expect(screen.getByTestId("settings-general-link-business-card")).toBeTruthy();
  });

  it("`/settings/general` also renders the General card", () => {
    renderHubAt("/settings/general");
    expect(screen.getByTestId("settings-general-card")).toBeTruthy();
  });
});
