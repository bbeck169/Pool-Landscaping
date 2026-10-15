/**
 * TD-51 · Feb-2026 — Form Builder submit-config ``creates`` dropdown
 * widened from 3 options (lead / customer / both) to 6, adding:
 *   • booking        — operator triage queue (db.job_requests)
 *   • service_log    — tech-adjacent log entry (db.service_reports
 *                      with source=marketing_form marker)
 *   • quote_request  — quote-prep queue (db.lead_requests)
 *
 * Covers (8 cases):
 *   1. Six options render in the select, each with the matching
 *      per-option data-testid (kept backward-compatible with the
 *      pre-TD-51 scheme ``form-submit-config-creates-{v}``).
 *   2. Default selection is "lead" (pre-TD-51 default preserved).
 *   3. Switching to each new destination updates submitCfg.creates
 *      and the save payload (PATCH).
 *   4. Helper-copy caption changes per selection + mentions the
 *      destination's downstream collection or admin surface so
 *      operators can self-serve.
 *   5. Legacy values (lead / customer / both) still work byte-
 *      identically — selection + save round-trip unchanged.
 *   6. CREATES_HELPER_COPY has an entry for all 6 keys (prevents a
 *      future enum addition from shipping without helper copy).
 *   7. Unknown creates value renders a defensive empty helper line
 *      — handled by the ``|| "lead"`` default; this test locks
 *      that fallback.
 *   8. The 3 pre-existing testid handles for lead/customer/both
 *      still exist (regression gate for any Playwright scripts
 *      targeting the pre-TD-51 radios).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";


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

import MarketingFormsPage, { CREATES_HELPER_COPY } from
  "@/pages/marketing/MarketingFormsPage";


const _SAVED_FORM = {
  id: "frm_td51",
  tenant_id: "t1",
  slug: "frm-td51",
  name: "TD-51 form",
  version: 1,
  submission_count: 0,
  active: true,
  fields: [{ id: "f1", name: "email", type: "email", label: "Email", required: true }],
  submit_button_label: "Send",
  success_message: "Thanks!",
  submit_config: {
    creates: "lead",
    admin_bell: true,
    confirmation_email_template_id: null,
    drip_sequence_id: null,
  },
  theme: {},
  hero: {},
};


function _resetMocks() {
  _mocks.get.mockReset(); _mocks.post.mockReset();
  _mocks.patch.mockReset(); _mocks.del.mockReset();
  // Default: list returns one form so the editor can open.
  _mocks.get.mockImplementation((path) => {
    if (path === "/admin/forms") return Promise.resolve([_SAVED_FORM]);
    if (path === "/marketing/templates") return Promise.resolve([]);
    if (path === "/marketing/sequences") return Promise.resolve([]);
    if (path && path.startsWith("/admin/forms/frm_td51")) {
      return Promise.resolve(_SAVED_FORM);
    }
    return Promise.resolve([]);
  });
  _mocks.patch.mockResolvedValue({ ..._SAVED_FORM });
}


async function _openEditor() {
  render(<MarketingFormsPage />);
  await screen.findByText("TD-51 form");
  fireEvent.click(screen.getByText("TD-51 form"));
  // The submit-config select is TD-51's new control.
  return await screen.findByTestId("form-submit-config-creates-select");
}


describe("MarketingFormsPage · TD-51 submission destinations", () => {
  beforeEach(_resetMocks);
  afterEach(() => cleanup());

  // ─────────────────────────────────────────────────────────────
  // 1. All six option testids render
  // ─────────────────────────────────────────────────────────────
  it("renders all 6 creates options with per-option data-testids", async () => {
    await _openEditor();
    for (const v of [
      "lead", "customer", "both",
      "booking", "service_log", "quote_request",
    ]) {
      expect(
        screen.getByTestId(`form-submit-config-creates-${v}`),
      ).toBeTruthy();
    }
  });

  // ─────────────────────────────────────────────────────────────
  // 2. Default selection preserved
  // ─────────────────────────────────────────────────────────────
  it("defaults to 'lead' when the saved form has creates=lead", async () => {
    const select = await _openEditor();
    expect(select.value).toBe("lead");
  });

  // ─────────────────────────────────────────────────────────────
  // 3. Switching to each new destination updates state + payload
  // ─────────────────────────────────────────────────────────────
  it.each(["booking", "service_log", "quote_request"])(
    "switches to '%s' and persists via PATCH",
    async (dest) => {
      const select = await _openEditor();
      fireEvent.change(select, { target: { value: dest } });
      expect(select.value).toBe(dest);

      // Click Save (the editor's save button).
      const saveBtn = screen.getByTestId("form-save-btn");
      fireEvent.click(saveBtn);
      await waitFor(() => expect(_mocks.patch).toHaveBeenCalled());
      // Last PATCH call carried creates=<dest> in submit_config.
      const [path, body] = _mocks.patch.mock.calls.pop();
      expect(path).toMatch(/\/admin\/forms\/frm_td51/);
      expect(body.submit_config.creates).toBe(dest);
    },
  );

  // ─────────────────────────────────────────────────────────────
  // 4. Helper caption changes per selection + mentions the surface
  // ─────────────────────────────────────────────────────────────
  it("renders a destination-specific helper caption that updates on change", async () => {
    const select = await _openEditor();
    const helper = await screen.findByTestId(
      "form-submit-config-creates-helper",
    );
    expect(helper.textContent).toBe(CREATES_HELPER_COPY.lead);

    fireEvent.change(select, { target: { value: "booking" } });
    expect(helper.textContent).toBe(CREATES_HELPER_COPY.booking);
    // Mentions the operator surface so the admin can navigate.
    expect(helper.textContent).toMatch(/job-requests/i);

    fireEvent.change(select, { target: { value: "service_log" } });
    expect(helper.textContent).toBe(CREATES_HELPER_COPY.service_log);
    expect(helper.textContent).toMatch(/service-reports/i);

    fireEvent.change(select, { target: { value: "quote_request" } });
    expect(helper.textContent).toBe(CREATES_HELPER_COPY.quote_request);
    expect(helper.textContent).toMatch(/lead-requests/i);
  });

  // ─────────────────────────────────────────────────────────────
  // 5. Legacy values round-trip identically
  // ─────────────────────────────────────────────────────────────
  it.each(["lead", "customer", "both"])(
    "legacy '%s' selection still saves correctly",
    async (dest) => {
      const select = await _openEditor();
      fireEvent.change(select, { target: { value: dest } });
      fireEvent.click(screen.getByTestId("form-save-btn"));
      await waitFor(() => expect(_mocks.patch).toHaveBeenCalled());
      const [, body] = _mocks.patch.mock.calls.pop();
      expect(body.submit_config.creates).toBe(dest);
    },
  );

  // ─────────────────────────────────────────────────────────────
  // 6. Helper copy map covers all 6 enum values
  // ─────────────────────────────────────────────────────────────
  it("CREATES_HELPER_COPY defines a non-empty caption for every enum member", () => {
    const expected = [
      "lead", "customer", "both",
      "booking", "service_log", "quote_request",
    ];
    expect(Object.keys(CREATES_HELPER_COPY).sort()).toEqual(expected.sort());
    for (const k of expected) {
      expect(CREATES_HELPER_COPY[k]).toBeTruthy();
      // Must be a substantive sentence, not a placeholder.
      expect(CREATES_HELPER_COPY[k].length).toBeGreaterThan(20);
    }
  });

  // ─────────────────────────────────────────────────────────────
  // 7. Fallback on unknown value — defensive ``|| "lead"``
  // ─────────────────────────────────────────────────────────────
  it("falls back to 'lead' helper when creates is unexpectedly empty", async () => {
    _mocks.get.mockImplementation((path) => {
      if (path === "/admin/forms") {
        return Promise.resolve([{
          ..._SAVED_FORM, submit_config: { ..._SAVED_FORM.submit_config, creates: "" },
        }]);
      }
      if (path === "/marketing/templates") return Promise.resolve([]);
      if (path === "/marketing/sequences") return Promise.resolve([]);
      if (path && path.startsWith("/admin/forms/frm_td51")) {
        return Promise.resolve({
          ..._SAVED_FORM, submit_config: { ..._SAVED_FORM.submit_config, creates: "" },
        });
      }
      return Promise.resolve([]);
    });
    const select = await _openEditor();
    // ``|| "lead"`` fallback: when creates is "", the SELECT's
    // value prop coerces to "lead" at render time.
    expect(select.value).toBe("lead");
    const helper = screen.getByTestId(
      "form-submit-config-creates-helper",
    );
    expect(helper.textContent).toBe(CREATES_HELPER_COPY.lead);
  });

  // ─────────────────────────────────────────────────────────────
  // 8. Pre-TD-51 testids preserved for Playwright scripts
  // ─────────────────────────────────────────────────────────────
  it("pre-TD-51 testids form-submit-config-creates-{lead,customer,both} still resolve", async () => {
    await _openEditor();
    // Each option element should carry the pre-TD-51 testid even
    // though the control is now a select instead of a radio.
    expect(
      screen.getByTestId("form-submit-config-creates-lead"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("form-submit-config-creates-customer"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("form-submit-config-creates-both"),
    ).toBeTruthy();
  });
});
