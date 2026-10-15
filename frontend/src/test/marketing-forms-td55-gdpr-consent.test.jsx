/**
 * TD-55 · Feb-2026 — GDPR consent_checkbox field type.
 *
 * Phase 6 Commit 2 of the GDPR ship.
 *
 * Covers (12 cases):
 *
 * Admin canvas (6):
 *   1. consent_checkbox palette button exists with the operator-
 *      facing FIELD_TYPE_LABELS copy "GDPR consent checkbox".
 *   2. Adding consent_checkbox via the palette button appends a
 *      row of type=consent_checkbox.
 *   3. The row exposes the Privacy policy URL input (testid
 *      form-field-privacy-policy-url-{idx}).
 *   4. Privacy policy URL input is HIDDEN for every other field
 *      type — regression gate so operators don't see a dangling
 *      input on non-consent rows.
 *   5. The privacy_policy_url input writes to field.privacy_policy_url
 *      (not .placeholder / .label).
 *   6. The row still shows the Required toggle (consent_checkbox
 *      is value-carrying, NOT layout — the required-check
 *      enforces truthy consent).
 *
 * Widget bundle (6) — source-parse the vanilla JS.
 *   7. Widget renders consent_checkbox as a <label><input type=
 *      checkbox>…</label> composite.
 *   8. Widget attaches a 'Privacy policy ↗' link when
 *      f.privacy_policy_url is set.
 *   9. Privacy policy link opens in a new tab (target=_blank
 *      rel=noopener noreferrer).
 *  10. consent_checkbox rows skip the top-level <label> row —
 *      the checkbox + inline label is the full affordance.
 *  11. collectAnswers emits boolean true/false for the checkbox
 *      (reused logic — unchanged from checkbox type).
 *  12. Testids form-widget-input-{name} + form-widget-consent-
 *      privacy-link-{name} are stable for Playwright.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import fs from "fs";
import path from "path";


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
  id: "frm_td55",
  tenant_id: "t1",
  slug: "frm-td55",
  name: "TD-55 GDPR form",
  version: 1,
  submission_count: 0,
  active: true,
  fields: [
    { id: "f1", name: "existing", type: "text", label: "Existing", required: false },
  ],
  submit_button_label: "Send",
  success_message: "Thanks!",
  submit_config: {
    creates: "lead", admin_bell: true,
    confirmation_email_template_id: null,
    drip_sequence_id: null,
  },
  theme: {}, hero: {},
};


function _resetMocks() {
  _mocks.get.mockReset(); _mocks.post.mockReset();
  _mocks.patch.mockReset(); _mocks.del.mockReset();
  _mocks.get.mockImplementation((p) => {
    if (p === "/admin/forms") return Promise.resolve([_SAVED_FORM]);
    if (p === "/marketing/templates") return Promise.resolve([]);
    if (p === "/marketing/sequences") return Promise.resolve([]);
    if (p && p.startsWith("/admin/forms/frm_td55")) return Promise.resolve(_SAVED_FORM);
    return Promise.resolve([]);
  });
  _mocks.patch.mockResolvedValue({ ..._SAVED_FORM });
}


async function _openEditor() {
  render(<MarketingFormsPage />);
  await screen.findByText("TD-55 GDPR form");
  fireEvent.click(screen.getByText("TD-55 GDPR form"));
  return await screen.findByTestId("form-save-btn");
}


// ──────────────────────────────────────────────────────────────────
// Admin canvas
// ──────────────────────────────────────────────────────────────────
describe("MarketingFormsPage · TD-55 consent_checkbox admin canvas", () => {
  beforeEach(_resetMocks);
  afterEach(() => cleanup());

  it("palette button for consent_checkbox exists with operator-facing label", async () => {
    await _openEditor();
    const btn = screen.getByTestId("form-field-palette-consent_checkbox");
    expect(btn).toBeTruthy();
    expect(btn.textContent).toMatch(/GDPR consent checkbox/i);
  });

  it("clicking the palette button appends a consent_checkbox row", async () => {
    await _openEditor();
    fireEvent.click(
      screen.getByTestId("form-field-palette-consent_checkbox"),
    );
    await waitFor(() => {
      const selects = Array.from(document.querySelectorAll("select"))
        .filter((s) => s.value === "consent_checkbox");
      expect(selects.length).toBeGreaterThan(0);
    });
  });

  it("consent_checkbox row exposes a privacy_policy_url input", async () => {
    await _openEditor();
    fireEvent.click(
      screen.getByTestId("form-field-palette-consent_checkbox"),
    );
    await waitFor(() => {
      const url = document.querySelector(
        '[data-testid^="form-field-privacy-policy-url-"]',
      );
      expect(url).toBeTruthy();
    });
  });

  it("privacy_policy_url input is hidden on non-consent field types", async () => {
    await _openEditor();
    // Pre-existing row is type=text; the row's privacy_policy_url
    // input should NOT render.
    const url = document.querySelector(
      '[data-testid^="form-field-privacy-policy-url-"]',
    );
    expect(url).toBeNull();
  });

  it("privacy_policy_url input writes to field.privacy_policy_url (not label / placeholder)", async () => {
    await _openEditor();
    fireEvent.click(
      screen.getByTestId("form-field-palette-consent_checkbox"),
    );
    const url = await waitFor(() => {
      const el = document.querySelector(
        '[data-testid^="form-field-privacy-policy-url-"]',
      );
      if (!el) throw new Error("input not found");
      return el;
    });
    fireEvent.change(url, {
      target: { value: "https://example.com/privacy" },
    });
    // Save → PATCH payload should carry privacy_policy_url on the
    // new consent row.
    fireEvent.click(screen.getByTestId("form-save-btn"));
    await waitFor(() => expect(_mocks.patch).toHaveBeenCalled());
    const [, body] = _mocks.patch.mock.calls.pop();
    const consentRow = (body.fields || []).find(
      (f) => f.type === "consent_checkbox",
    );
    expect(consentRow).toBeTruthy();
    expect(consentRow.privacy_policy_url).toBe(
      "https://example.com/privacy",
    );
    // placeholder / label stay unaffected.
    expect(consentRow.placeholder || "").not.toBe(
      "https://example.com/privacy",
    );
  });

  it("consent_checkbox row shows the Required toggle (value-carrying, NOT layout)", async () => {
    await _openEditor();
    fireEvent.click(
      screen.getByTestId("form-field-palette-consent_checkbox"),
    );
    await waitFor(() => {
      // Required toggle testid is form-field-required-{idx}; must
      // exist on the newly-added consent row.
      const toggles = document.querySelectorAll(
        'input[data-testid^="form-field-required-"]',
      );
      // Pre-existing row + new consent row = 2 toggles.
      expect(toggles.length).toBeGreaterThanOrEqual(2);
    });
  });
});


// ──────────────────────────────────────────────────────────────────
// Widget bundle — source parse
// ──────────────────────────────────────────────────────────────────
describe("widget bundle · TD-55 consent_checkbox renderer", () => {
  const WIDGET = fs.readFileSync(
    path.resolve(__dirname, "../../public/widget/form.js"),
    "utf8",
  );

  it("switch case for 'consent_checkbox' is defined", () => {
    expect(WIDGET).toMatch(/case "consent_checkbox":/);
  });

  it("renders a 'Privacy policy ↗' link when privacy_policy_url is set", () => {
    expect(WIDGET.includes("f.privacy_policy_url")).toBe(true);
    expect(WIDGET.includes("Privacy policy")).toBe(true);
  });

  it("privacy policy link opens in a new tab with safe rel attrs", () => {
    // Locate the branch that renders the link.
    const start = WIDGET.indexOf("f.privacy_policy_url");
    expect(start).toBeGreaterThan(0);
    const slice = WIDGET.slice(start, start + 800);
    expect(slice.includes('target: "_blank"')).toBe(true);
    expect(slice.includes('rel: "noopener noreferrer"')).toBe(true);
  });

  it("consent_checkbox rows skip the top-level <label> row", () => {
    // The row-wrapping expression now gates on BOTH checkbox AND
    // consent_checkbox types to skip the label.
    expect(WIDGET).toMatch(
      /f\.type === "checkbox"\s*\|\|\s*f\.type === "consent_checkbox"/,
    );
  });

  it("collectAnswers emits boolean for checkbox inputs (shared with legacy checkbox type)", () => {
    expect(WIDGET.includes('out[input.name] = input.checked')).toBe(true);
  });

  it("stable testids form-widget-input-{name} + form-widget-consent-privacy-link-{name}", () => {
    expect(WIDGET.includes('"form-widget-input-" + name')).toBe(true);
    expect(WIDGET.includes('"form-widget-consent-privacy-link-" + name')).toBe(true);
    expect(WIDGET.includes('"form-widget-consent-wrap-" + name')).toBe(true);
    expect(WIDGET.includes('"form-widget-consent-text-" + name')).toBe(true);
  });
});
