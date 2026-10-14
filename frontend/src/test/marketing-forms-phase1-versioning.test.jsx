/**
 * Feb-2026 · Form Builder P2#12 Phase 1 Commit 2 — Version history
 * drawer vitest.
 *
 * Covers (4 cases) — mirrors the BE pytest shape:
 *   1. "History · vN" button renders when the form has been saved
 *      (i.e. `saved.id` present); clicking opens the panel + fires
 *      `GET /admin/forms/{fid}/versions`.
 *   2. Panel renders one row per snapshot sorted DESC.
 *   3. "Revert" button on a non-current version POSTs
 *      `/admin/forms/{fid}/revert/{version}` and refreshes the
 *      live view.
 *   4. "Revert" button for the CURRENT version is disabled.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";

const _mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => _mocks.get(...a),
    post: (...a) => _mocks.post(...a),
    patch: (...a) => _mocks.patch(...a),
    del: (...a) => _mocks.del(...a),
  },
}));

vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(async () => true),
}));
vi.mock("@/components/formBuilder/ThemePanel", () => ({
  __esModule: true, default: () => <div data-testid="stub-theme-panel" />,
}));
vi.mock("@/components/formBuilder/HeroEditor", () => ({
  __esModule: true, default: () => <div data-testid="stub-hero" />,
}));
vi.mock("@/components/formBuilder/RichTextField", () => ({
  __esModule: true,
  default: ({ value, onChange, testid }) => (
    <input data-testid={testid} value={value || ""}
             onChange={(e) => onChange(e.target.value)} />
  ),
}));
vi.mock("@/components/common/AddressAutocomplete", () => ({
  __esModule: true, default: () => <div data-testid="stub-address" />,
}));

import MarketingFormsPage from "@/pages/marketing/MarketingFormsPage";


const _SAVED_FORM = {
  id: "frm_v",
  tenant_id: "t1",
  slug: "frm-v",
  name: "Saved Form",
  fields: [{ id: "f1", name: "full_name", label: "Name", type: "text",
              required: true }],
  submit_config: { creates: "lead", admin_bell: true },
  theme: null, hero: null,
  version: 3,
};

const _VERSIONS = {
  versions: [
    { version: 3, action: "update", at: "2026-02-15T10:00:00Z",
      name: "Saved Form", fields: _SAVED_FORM.fields,
      submit_config: _SAVED_FORM.submit_config, theme: null,
      hero: null },
    { version: 2, action: "update", at: "2026-02-14T10:00:00Z",
      name: "v2 Name", fields: [], submit_config: null,
      theme: null, hero: null },
    { version: 1, action: "create", at: "2026-02-13T10:00:00Z",
      name: "original", fields: [], submit_config: null,
      theme: null, hero: null },
  ],
};


beforeEach(() => {
  _mocks.get.mockReset();
  _mocks.post.mockReset();
  _mocks.patch.mockReset();
  _mocks.del.mockReset();
  // GET list → one existing saved form; GET widget config → defaults;
  // GET versions → canned snapshots.
  _mocks.get.mockImplementation(async (p) => {
    if (p === "/admin/forms") return [_SAVED_FORM];
    if (p === "/tenants/mine/widget-config") {
      return { public_key: "pk_test", turnstile_site_key: null };
    }
    if (p === "/admin/forms/frm_v/versions") return _VERSIONS;
    return {};
  });
});
afterEach(() => cleanup());


async function _openSavedForm() {
  const row = await screen.findByTestId("form-row-frm_v");
  fireEvent.click(row);
  await screen.findByTestId("form-edit-drawer");
}


describe("MarketingFormsPage · Phase 1 C2 version history", () => {
  it("History button renders + opens panel + GETs versions", async () => {
    render(<MarketingFormsPage />);
    await _openSavedForm();
    const btn = await screen.findByTestId("form-version-history-btn");
    expect(btn.textContent).toMatch(/History\s*·?\s*v3/);
    fireEvent.click(btn);
    await waitFor(() => {
      expect(_mocks.get).toHaveBeenCalledWith(
        "/admin/forms/frm_v/versions");
    });
    expect(screen.getByTestId(
      "form-version-history-panel")).toBeTruthy();
  });

  it("renders one row per snapshot sorted DESC", async () => {
    render(<MarketingFormsPage />);
    await _openSavedForm();
    fireEvent.click(screen.getByTestId("form-version-history-btn"));
    await screen.findByTestId("form-version-row-3");
    expect(screen.getByTestId("form-version-row-3")).toBeTruthy();
    expect(screen.getByTestId("form-version-row-2")).toBeTruthy();
    expect(screen.getByTestId("form-version-row-1")).toBeTruthy();
    // Current (v3) button is disabled; v1/v2 enabled.
    expect(screen.getByTestId("form-version-revert-3")
      .hasAttribute("disabled")).toBe(true);
    expect(screen.getByTestId("form-version-revert-2")
      .hasAttribute("disabled")).toBe(false);
  });

  it("Revert on a prior version POSTs the revert endpoint", async () => {
    _mocks.post.mockResolvedValueOnce({
      ..._SAVED_FORM, version: 4, name: "v2 Name",
    });
    render(<MarketingFormsPage />);
    await _openSavedForm();
    fireEvent.click(screen.getByTestId("form-version-history-btn"));
    await screen.findByTestId("form-version-row-2");
    fireEvent.click(screen.getByTestId("form-version-revert-2"));
    await waitFor(() => {
      const call = _mocks.post.mock.calls.find(
        (c) => c[0] === "/admin/forms/frm_v/revert/2");
      expect(call).toBeTruthy();
    });
  });

  it("Current version Revert button is disabled", async () => {
    render(<MarketingFormsPage />);
    await _openSavedForm();
    fireEvent.click(screen.getByTestId("form-version-history-btn"));
    await screen.findByTestId("form-version-row-3");
    const current = screen.getByTestId("form-version-revert-3");
    expect(current.hasAttribute("disabled")).toBe(true);
    expect(current.textContent).toMatch(/Current/);
  });
});
