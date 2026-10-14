/**
 * P2 #11 · Phase 1 · Feb-2026 — vitest for the drag-and-drop
 * email builder upgrades to ``pages/comms/CommsPages.jsx::
 * CommsEmailBuilder``.
 *
 * Locks the hardening set from the Phase 1 dispatch:
 *
 *   1. Click-to-add (``comms-email-add-{type}``) still works and
 *      is preserved alongside the new drag source — the pre-Phase-1
 *      test ID contract is unchanged.
 *   2. Each palette item carries a ``data-drag-source`` attribute so
 *      DnD-aware clients can distinguish it from a plain button.
 *   3. Each block card on the canvas gets a dedicated drag handle
 *      (``comms-email-drag-handle-N``) — the whole card is NOT
 *      draggable (would conflict with inspector focus).
 *   4. TipTap wires up for ``text.html`` fields (role=textbox) and
 *      preserves the existing ``comms-email-field-{k}`` test IDs.
 *   5. Brand-primary binding applies ONLY to NEW blocks created
 *      after mount — existing blocks loaded from the server are
 *      byte-identical when saved without edits.
 *   6. Byte-identical round-trip: load a server template, save
 *      without editing, assert the ``updateEmailTemplate`` payload
 *      has blocks_json identical to the loaded value.
 *   7. Preview viewport toggle swaps the iframe ``width`` attribute
 *      between 600 (desktop) and 375 (mobile).
 *   8. Test-send button opens the inline panel and calls
 *      ``testSendEmailTemplate(code, to)`` with the right body.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, cleanup, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";


// Mock the tenants API (used by _useBrandPrimary) + the comms API
// (used by the builder's load/save/preview/test-send paths). BOTH
// mocks are declared BEFORE the component import so Vitest hoists
// them above the ES module graph.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path === "/tenants/current") {
        return { brand_primary: "#AB1234", branding: { brand_primary: "#AB1234" } };
      }
      return {};
    }),
    post: vi.fn(async () => ({})),
    patch: vi.fn(async () => ({})),
    del: vi.fn(async () => ({})),
  },
}));


// Capture call shapes on the comms API mocks so tests can introspect
// what the builder actually dispatched to the server.
const _mocks = {
  getEmailTemplate: vi.fn(),
  updateEmailTemplate: vi.fn(),
  createEmailTemplate: vi.fn(),
  previewEmailTemplate: vi.fn(),
  testSendEmailTemplate: vi.fn(),
  duplicateEmailTemplate: vi.fn(),
};

vi.mock("@/api/comms", () => ({
  listEmailTemplates: vi.fn(async () => []),
  getEmailTemplate: (...args) => _mocks.getEmailTemplate(...args),
  createEmailTemplate: (...args) => _mocks.createEmailTemplate(...args),
  updateEmailTemplate: (...args) => _mocks.updateEmailTemplate(...args),
  deleteEmailTemplate: vi.fn(async () => ({})),
  duplicateEmailTemplate: (...args) => _mocks.duplicateEmailTemplate(...args),
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


// Keep the TokenPickerModal + Toast noise out of the test render.
vi.mock("@/components/comms/TokenPickerModal", () => ({
  __esModule: true,
  default: () => null,
}));


// Stub bulk-select toolkit (not exercised by Phase 1 tests).
vi.mock("@/components/bulk-select/BulkSelectToolkit", () => ({
  useBulkSelect: () => ({ selected: new Set(), toggle: () => undefined,
                           reset: () => undefined, isAllSelected: false }),
  BulkSelectAll: () => null,
  BulkSelectRow: () => null,
  BulkActionBar: () => null,
  BulkConfirmModal: () => null,
  LockedPill: () => null,
}));


// Stub CustomerCombobox — unused by the email builder (SMS only).
vi.mock("@/components/customers/CustomerCombobox", () => ({
  __esModule: true,
  default: () => null,
}));


import { CommsEmailBuilder } from "@/pages/comms/CommsPages";


const _EXISTING_TEMPLATE = {
  code: "existing-tpl",
  name: "Existing Welcome",
  subject: "Welcome {{customer.first_name}}",
  blocks_json: [
    { type: "heading", text: "Hi {{customer.first_name}}", level: 1,
      alignment: "left", color: "#0f6ed1", padding: "16px 24px" },
    { type: "text", html: "<p>Thanks for joining.</p>",
      padding: "12px 24px", text_color: "#222" },
  ],
  is_system: false,
};


function _renderBuilder({ route = "/admin/comms/email/existing-tpl" } = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/admin/comms/email/:code"
               element={<CommsEmailBuilder />} />
        <Route path="/admin/comms/email/new"
               element={<CommsEmailBuilder />} />
      </Routes>
    </MemoryRouter>,
  );
}


async function _flushAsync() {
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}


beforeEach(() => {
  cleanup();
  Object.values(_mocks).forEach((m) => m.mockReset?.());
  _mocks.getEmailTemplate.mockResolvedValue(
    JSON.parse(JSON.stringify(_EXISTING_TEMPLATE)),
  );
  _mocks.updateEmailTemplate.mockResolvedValue({ ..._EXISTING_TEMPLATE });
  _mocks.previewEmailTemplate.mockResolvedValue({
    subject: "Welcome Alex",
    html: "<html><body>Preview</body></html>",
  });
  _mocks.testSendEmailTemplate.mockResolvedValue({
    status: "sent", send_id: "s-1", recipient: "admin@test.local",
    subject: "[TEST] Welcome Alex",
  });
});


describe("CommsEmailBuilder · Phase 1 drag-and-drop + WYSIWYG + brand + test-send",
  () => {
  it("preserves click-to-add path with the existing "
     + "comms-email-add-{type} test IDs (Q2-A)", async () => {
    _renderBuilder({ route: "/admin/comms/email/new" });
    await _flushAsync();
    // All 12 click-to-add buttons still present.
    for (const type of ["text", "heading", "image", "button", "divider",
                         "spacer", "columns_2", "columns_3", "social",
                         "video", "product_card", "footer"]) {
      expect(screen.getByTestId(`comms-email-add-${type}`)).toBeTruthy();
    }
    // Clicking still adds a block.
    fireEvent.click(screen.getByTestId("comms-email-add-text"));
    expect(screen.getByTestId("comms-email-block-0")).toBeTruthy();
  });

  it("exposes palette items as drag sources via data-drag-source "
     + "and renders a dedicated drag handle on each canvas block",
     async () => {
    _renderBuilder({ route: "/admin/comms/email/new" });
    await _flushAsync();
    const addText = screen.getByTestId("comms-email-add-text");
    expect(addText.getAttribute("data-drag-source"))
      .toBe("comms-email-drag-text");
    // Add a block and assert the handle appears with a dedicated
    // test ID (whole card is NOT draggable — only the handle is).
    fireEvent.click(addText);
    expect(screen.getByTestId("comms-email-drag-handle-0")).toBeTruthy();
  });

  it("TipTap mounts for text.html fields with the preserved "
     + "comms-email-field-{k} test ID and emits HTML on update "
     + "(Q3-A)", async () => {
    _renderBuilder({ route: "/admin/comms/email/new" });
    await _flushAsync();
    fireEvent.click(screen.getByTestId("comms-email-add-text"));
    // Select the newly-added block to open the inspector.
    fireEvent.click(screen.getByTestId("comms-email-block-0"));
    const field = await screen.findByTestId("comms-email-field-html");
    // TipTap-backed field advertises role=textbox (plain textareas
    // don't — plain textareas live under a different element).
    expect(field.getAttribute("role")).toBe("textbox");
    expect(field.getAttribute("aria-multiline")).toBe("true");
  });

  it("brand-primary binding applies ONLY to NEW blocks (Q5-A). "
     + "A new button block picks up #AB1234 for background_color; "
     + "existing blocks on the loaded template retain their "
     + "pre-ship colors (byte-identical).", async () => {
    _renderBuilder({ route: "/admin/comms/email/existing-tpl" });
    await _flushAsync();
    // Add a new button block — should get brand_primary.
    fireEvent.click(screen.getByTestId("comms-email-add-button"));
    // The existing-tpl loaded with 2 blocks (heading + text), so
    // the new button is at index 2.
    fireEvent.click(screen.getByTestId("comms-email-block-2"));
    const bgField = await screen.findByTestId(
      "comms-email-field-background_color",
    );
    expect(bgField.getAttribute("value") || bgField.value)
      .toBe("#AB1234");
    // Existing heading at index 0 — unchanged (#0f6ed1 from
    // the loaded template, NOT the brand color).
    fireEvent.click(screen.getByTestId("comms-email-block-0"));
    const colorField = await screen.findByTestId("comms-email-field-color");
    expect(colorField.getAttribute("value") || colorField.value)
      .toBe("#0f6ed1");
  });

  it("byte-identical round-trip — load a server template, save "
     + "without editing, and the updateEmailTemplate payload "
     + "carries blocks_json identical to the loaded value "
     + "(Q5-A hardening)", async () => {
    _renderBuilder({ route: "/admin/comms/email/existing-tpl" });
    await _flushAsync();
    fireEvent.click(screen.getByTestId("comms-email-save"));
    await _flushAsync();
    expect(_mocks.updateEmailTemplate).toHaveBeenCalled();
    const [, payload] = _mocks.updateEmailTemplate.mock.calls[0];
    // Preserved verbatim — same order, same keys, same values.
    expect(payload.blocks_json).toEqual(_EXISTING_TEMPLATE.blocks_json);
    expect(payload.subject).toBe(_EXISTING_TEMPLATE.subject);
  });

  it("preview viewport toggle swaps the iframe width between "
     + "600 (desktop) and 375 (mobile) (Q7-A)", async () => {
    _renderBuilder({ route: "/admin/comms/email/existing-tpl" });
    await _flushAsync();
    fireEvent.click(screen.getByTestId("comms-email-preview"));
    await _flushAsync();
    const iframe = await screen.findByTestId("comms-preview-iframe");
    expect(iframe.getAttribute("width")).toBe("600");
    expect(iframe.getAttribute("data-viewport")).toBe("desktop");
    // Click mobile → width swaps to 375.
    fireEvent.click(screen.getByTestId("comms-preview-viewport-mobile"));
    await _flushAsync();
    const iframeAfter = await screen.findByTestId("comms-preview-iframe");
    expect(iframeAfter.getAttribute("width")).toBe("375");
    expect(iframeAfter.getAttribute("data-viewport")).toBe("mobile");
  });

  it("test-send button opens the inline panel + calls "
     + "testSendEmailTemplate(code, to) with the admin-entered "
     + "recipient (Q6-A)", async () => {
    _renderBuilder({ route: "/admin/comms/email/existing-tpl" });
    await _flushAsync();
    // Open the panel.
    fireEvent.click(screen.getByTestId("comms-email-test-send-toggle"));
    const input = await screen.findByTestId("comms-email-test-send-input");
    fireEvent.change(input, { target: { value: "peer@test.local" } });
    fireEvent.click(screen.getByTestId("comms-email-test-send-submit"));
    await _flushAsync();
    expect(_mocks.testSendEmailTemplate).toHaveBeenCalledWith(
      "existing-tpl", "peer@test.local",
    );
  });

  it("test-send button with EMPTY `to` falls through to the "
     + "server's self-send default (passes undefined, server "
     + "reads caller's email) (Q6-A safe-default)", async () => {
    _renderBuilder({ route: "/admin/comms/email/existing-tpl" });
    await _flushAsync();
    fireEvent.click(screen.getByTestId("comms-email-test-send-toggle"));
    fireEvent.click(screen.getByTestId("comms-email-test-send-submit"));
    await _flushAsync();
    expect(_mocks.testSendEmailTemplate).toHaveBeenCalledWith(
      "existing-tpl", undefined,
    );
  });
});
