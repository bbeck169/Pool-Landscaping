/**
 * P2 #11 · Phase 2 · Feb-2026 — vitest for the drag-and-drop email
 * builder Phase 2 additions.
 *
 * Covers (6 cases):
 *   TD-42 · Nested columns
 *     1. "flat HTML" badge renders for a `columns_2` block with no
 *        `children` array, and the "→ Nested" migration button is
 *        enabled.
 *     2. Clicking "→ Nested" migrates the slot's flat HTML into a
 *        new nested `[{type:"text", props:{html}}]` child while
 *        leaving the sibling slot's flat HTML untouched. After
 *        migration the "+ Text" affordance appears.
 *
 *   TD-43 · Preview-text (preheader)
 *     3. The preview-text input hydrates from the loaded template's
 *        `preview_text` field and the counter reads "N / 150".
 *     4. Saving sends the current preview text in the
 *        `updateEmailTemplate` payload.
 *
 *   TD-44 · UTM admin modal
 *     5. "UTM link settings" button opens the modal, hydrates from
 *        `GET /comms/tenants/current/email-utm`, and surfaces the
 *        link-wrapping toggle.
 *     6. Saving the modal issues a `PATCH /comms/tenants/current/
 *        email-utm` with the operator's values + wrapping flag.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, cleanup } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";


// ─── Mocks ─────────────────────────────────────────────────────────
// api.get/patch/post declared BEFORE the component import so Vitest
// hoists the mock above the ES module graph. The two UTM endpoints
// (`GET` + `PATCH /comms/tenants/current/email-utm`) land on
// ``api.get`` / ``api.patch``; the tenants brand fetch
// (`/tenants/current`) also lands on ``api.get``.
const _apiGet = vi.fn();
const _apiPatch = vi.fn();
const _apiPost = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...args) => _apiGet(...args),
    post: (...args) => _apiPost(...args),
    patch: (...args) => _apiPatch(...args),
    del: vi.fn(async () => ({})),
  },
}));


const _mocks = {
  getEmailTemplate: vi.fn(),
  updateEmailTemplate: vi.fn(),
  previewEmailTemplate: vi.fn(),
  testSendEmailTemplate: vi.fn(),
};

vi.mock("@/api/comms", () => ({
  listEmailTemplates: vi.fn(async () => []),
  getEmailTemplate: (...args) => _mocks.getEmailTemplate(...args),
  updateEmailTemplate: (...args) => _mocks.updateEmailTemplate(...args),
  createEmailTemplate: vi.fn(async () => ({})),
  deleteEmailTemplate: vi.fn(async () => ({})),
  duplicateEmailTemplate: vi.fn(async () => ({})),
  previewEmailTemplate: (...args) => _mocks.previewEmailTemplate(...args),
  testSendEmailTemplate: (...args) => _mocks.testSendEmailTemplate(...args),
  listSmsTemplates: vi.fn(async () => []),
  getSmsTemplate: vi.fn(async () => ({})),
  createSmsTemplate: vi.fn(async () => ({})),
  updateSmsTemplate: vi.fn(async () => ({})),
  deleteSmsTemplate: vi.fn(async () => ({})),
  duplicateSmsTemplate: vi.fn(async () => ({})),
  previewSmsTemplate: vi.fn(async () => ({})),
  listAutomations: vi.fn(async () => []),
  createAutomation: vi.fn(async () => ({})),
  updateAutomation: vi.fn(async () => ({})),
  deleteAutomation: vi.fn(async () => ({})),
  testFireAutomation: vi.fn(async () => ({})),
  listSends: vi.fn(async () => []),
  getSend: vi.fn(async () => ({})),
  smsMetrics: () => ({ chars: 0, encoding: "GSM-7", segments: 0 }),
  TRIGGER_EVENTS: [],
}));

vi.mock("@/components/comms/TokenPickerModal", () => ({
  __esModule: true, default: () => null,
}));
vi.mock("@/components/bulk-select/BulkSelectToolkit", () => ({
  useBulkSelect: () => ({ selected: new Set(), toggle: () => undefined,
                           reset: () => undefined, isAllSelected: false }),
  BulkSelectAll: () => null, BulkSelectRow: () => null,
  BulkActionBar: () => null, BulkConfirmModal: () => null,
  LockedPill: () => null,
}));
vi.mock("@/components/customers/CustomerCombobox", () => ({
  __esModule: true, default: () => null,
}));

import { CommsEmailBuilder } from "@/pages/comms/CommsPages";


// Template fixture: flat columns_2 block + preview_text.
const _TPL_WITH_COLUMNS = {
  code: "ph2-tpl",
  name: "Phase 2 Fixture",
  subject: "Hi {{customer.first_name}}",
  preview_text: "This should land in your inbox preview.",
  blocks_json: [
    { type: "columns_2",
      left_html: "<p>Left flat</p>",
      right_html: "<p>Right flat</p>",
      padding: "12px 24px" },
  ],
  is_system: false,
};


function _renderBuilder({ route = "/admin/comms/email/ph2-tpl" } = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/admin/comms/email/:code"
                element={<CommsEmailBuilder />} />
      </Routes>
    </MemoryRouter>,
  );
}


async function _flushAsync() {
  await act(async () => {
    await Promise.resolve(); await Promise.resolve();
    await Promise.resolve();
  });
}


beforeEach(() => {
  cleanup();
  _apiGet.mockReset(); _apiPatch.mockReset(); _apiPost.mockReset();
  Object.values(_mocks).forEach((m) => m.mockReset?.());
  // tenants/current → brand hex (byte-identical to the Phase 1 fixture).
  // tenants/current/email-utm → defaults envelope (TD-44 endpoint).
  _apiGet.mockImplementation(async (p) => {
    if (p === "/tenants/current") {
      return { brand_primary: "#AB1234",
                branding: { brand_primary: "#AB1234" } };
    }
    if (p === "/comms/tenants/current/email-utm") {
      return {
        utm_defaults: { utm_source: "newsletter",
                         utm_medium: "email" },
        link_wrapping_enabled: true,
        defaults_source: "tenant_override",
      };
    }
    return {};
  });
  _apiPatch.mockResolvedValue({ ok: true });
  _mocks.getEmailTemplate.mockResolvedValue(
    JSON.parse(JSON.stringify(_TPL_WITH_COLUMNS)));
  _mocks.updateEmailTemplate.mockResolvedValue({ ..._TPL_WITH_COLUMNS });
  _mocks.previewEmailTemplate.mockResolvedValue({
    subject: "Hi Alex", html: "<html><body>Preview</body></html>",
  });
});


describe("CommsEmailBuilder · Phase 2", () => {
  // ──────────────────────────────────────────────────────────────
  // TD-42 · Nested columns — migration surface
  // ──────────────────────────────────────────────────────────────
  it("TD-42 · columns block renders flat badge + → Nested button per slot", async () => {
    _renderBuilder();
    await _flushAsync();
    // Select the only block so the inspector surfaces column controls.
    fireEvent.click(screen.getByTestId("comms-email-block-0"));
    await _flushAsync();
    // "→ Nested" migration button present for each slot (left=0,
    // right=1).
    expect(screen.getByTestId("comms-email-column-convert-0-0")).toBeTruthy();
    expect(screen.getByTestId("comms-email-column-convert-0-1")).toBeTruthy();
    // Flat badge rendered via the "flat HTML" copy next to each slot.
    const texts = screen.getAllByText(/flat HTML/i);
    expect(texts.length).toBeGreaterThanOrEqual(2);
  });

  it("TD-42 · clicking → Nested migrates the slot's flat HTML to children", async () => {
    _renderBuilder();
    await _flushAsync();
    fireEvent.click(screen.getByTestId("comms-email-block-0"));
    await _flushAsync();
    // Migrate the LEFT slot. The RIGHT slot's flat HTML must survive.
    fireEvent.click(screen.getByTestId("comms-email-column-convert-0-0"));
    await _flushAsync();
    // Post-migration: left slot renders the "+ Text" add-child button;
    // right slot still renders its "→ Nested" migration button.
    expect(screen.getByTestId("comms-email-column-add-0-0")).toBeTruthy();
    expect(screen.getByTestId("comms-email-column-convert-0-1")).toBeTruthy();
    // Save → inspect the payload. The server-shipped block should
    // now have a non-null `children` array where index 0 carries
    // the migrated text node; index 1 stays an empty array.
    fireEvent.click(screen.getByTestId("comms-email-save"));
    await _flushAsync();
    expect(_mocks.updateEmailTemplate).toHaveBeenCalled();
    const payload = _mocks.updateEmailTemplate.mock.calls[0][1];
    const col = payload.blocks_json[0];
    expect(Array.isArray(col.children)).toBe(true);
    expect(col.children.length).toBe(2);
    const leftKids = col.children[0];
    expect(Array.isArray(leftKids)).toBe(true);
    expect(leftKids[0].type).toBe("text");
    // The migrated HTML should be preserved verbatim.
    const migrated = leftKids[0].props?.html ?? leftKids[0].html;
    expect(migrated).toContain("Left flat");
    // Right slot was untouched → stays flat (empty nested array).
    expect(col.children[1]).toEqual([]);
    expect(col.right_html).toBe("<p>Right flat</p>");
  });

  // ──────────────────────────────────────────────────────────────
  // TD-43 · Preview-text (preheader)
  // ──────────────────────────────────────────────────────────────
  it("TD-43 · preview-text input hydrates from the loaded template", async () => {
    _renderBuilder();
    await _flushAsync();
    const input = screen.getByTestId("comms-email-preview-text");
    expect(input.value).toBe(
      "This should land in your inbox preview.");
    // Counter format: "N / 150".
    const counter = screen.getByTestId(
      "comms-email-preview-text-counter");
    expect(counter.textContent).toMatch(/\/ 150/);
    expect(counter.textContent).toMatch(/^\s*39 \/ 150\s*$/);
  });

  it("TD-43 · save sends preview_text in the update payload", async () => {
    _renderBuilder();
    await _flushAsync();
    const input = screen.getByTestId("comms-email-preview-text");
    fireEvent.change(input, { target: { value: "New preheader copy" } });
    fireEvent.click(screen.getByTestId("comms-email-save"));
    await _flushAsync();
    expect(_mocks.updateEmailTemplate).toHaveBeenCalled();
    const payload = _mocks.updateEmailTemplate.mock.calls[0][1];
    expect(payload.preview_text).toBe("New preheader copy");
  });

  // ──────────────────────────────────────────────────────────────
  // TD-44 · UTM admin modal
  // ──────────────────────────────────────────────────────────────
  it("TD-44 · UTM link settings button opens the modal + hydrates", async () => {
    _renderBuilder();
    await _flushAsync();
    fireEvent.click(screen.getByTestId("comms-email-utm-settings"));
    await _flushAsync();
    expect(screen.getByTestId("comms-email-utm-modal")).toBeTruthy();
    // Hydrated: link-wrapping toggle reflects `link_wrapping_enabled: true`.
    const toggle = screen.getByTestId("comms-email-utm-enabled");
    expect(toggle.checked).toBe(true);
    // GET endpoint hit.
    expect(_apiGet).toHaveBeenCalledWith(
      "/comms/tenants/current/email-utm");
  });

  it("TD-44 · modal save PATCHes the UTM endpoint with the right body", async () => {
    _renderBuilder();
    await _flushAsync();
    fireEvent.click(screen.getByTestId("comms-email-utm-settings"));
    await _flushAsync();
    // Click Save without changes — the current (hydrated) state
    // should round-trip verbatim: wrapping enabled + the preset
    // utm_source/utm_medium from the GET mock.
    fireEvent.click(screen.getByTestId("comms-email-utm-save"));
    await _flushAsync();
    expect(_apiPatch).toHaveBeenCalled();
    const [path, body] = _apiPatch.mock.calls[0];
    expect(path).toBe("/comms/tenants/current/email-utm");
    expect(body.link_wrapping_enabled).toBe(true);
    expect(body.utm_defaults).toEqual({
      utm_source: "newsletter",
      utm_medium: "email",
    });
  });
});
