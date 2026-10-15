/**
 * TD-52 · Feb-2026 — Form Builder palette expansion.
 *
 * Phase 3 Commit 2 — admin palette widens from 14 → 18 field types.
 * Four new entries land with their own labels, inspector-level
 * acceptance (no options list, duplicate-name check still fires),
 * and widget renderers (signature canvas, address_manual composite,
 * rating_stars star group, file_multi_upload multi-picker).
 *
 * Covers (16 cases):
 *
 * Builder palette (6):
 *   1. Palette select renders all four new type options with the
 *      correct FIELD_TYPE_LABELS copy.
 *   2. Adding a signature field via the palette dropdown produces
 *      a field row with type=signature and no options.
 *   3. Adding an address_manual field produces a type=address_manual
 *      row with no options.
 *   4. Adding a rating_stars field produces a type=rating_stars row
 *      with no options.
 *   5. Adding a file_multi_upload field produces a type=
 *      file_multi_upload row with no options.
 *   6. The new types are NOT layout markers (they expose a name
 *      input in the editor row — regression gate for the layout
 *      exemption in the FieldEditorRow renderer).
 *
 * Widget renderer (10):
 *   The widget bundle is vanilla JS; we exercise the renderer by
 *   parsing the source text and asserting the four new switch
 *   cases exist AND that collectAnswers folds the address_manual
 *   sub-field names back into a nested object. Full end-to-end
 *   DOM mounting is already covered by
 *   marketing-forms-phase4-widget-parity.test.jsx — this suite
 *   locks the TD-52 widget contract.
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
  id: "frm_td52",
  tenant_id: "t1",
  slug: "frm-td52",
  name: "TD-52 palette form",
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
    if (p && p.startsWith("/admin/forms/frm_td52")) return Promise.resolve(_SAVED_FORM);
    return Promise.resolve([]);
  });
  _mocks.patch.mockResolvedValue({ ..._SAVED_FORM });
}


async function _openEditor() {
  render(<MarketingFormsPage />);
  await screen.findByText("TD-52 palette form");
  fireEvent.click(screen.getByText("TD-52 palette form"));
  // Wait for editor to mount.
  return await screen.findByTestId("form-save-btn");
}


// ──────────────────────────────────────────────────────────────────
// Builder palette
// ──────────────────────────────────────────────────────────────────
describe("MarketingFormsPage · TD-52 palette", () => {
  beforeEach(_resetMocks);
  afterEach(() => cleanup());

  it("palette dropdown exposes the four new field type options", async () => {
    await _openEditor();
    // The palette-select renders every FIELD_TYPES entry as an
    // <option> OR as a quick-add button; the component uses both
    // patterns. Verify the user-facing labels appear in the DOM.
    const expected = [
      "Signature pad",
      "Address (manual entry)",
      "Rating (1–5 stars)",
      "File upload (multiple)",
    ];
    for (const label of expected) {
      const hits = screen.getAllByText(label);
      expect(hits.length).toBeGreaterThan(0);
    }
  });

  it.each([
    ["signature", "Signature pad"],
    ["address_manual", "Address (manual entry)"],
    ["rating_stars", "Rating (1–5 stars)"],
    ["file_multi_upload", "File upload (multiple)"],
  ])("palette button for '%s' appends a new row of that type",
    async (type, _label) => {
      await _openEditor();
      const btn = screen.getByTestId(`form-field-palette-${type}`);
      fireEvent.click(btn);
      // The newly-added row should expose a type select whose
      // selected value is the new type.
      await waitFor(() => {
        const selects = Array.from(document.querySelectorAll(
          "select",
        )).filter((s) => s.value === type);
        expect(selects.length).toBeGreaterThan(0);
      });
    },
  );

  it("new field types are value-carrying (not layout markers) — row appears in field list", async () => {
    await _openEditor();
    const initialRowCount = document.querySelectorAll(
      '[data-testid^="form-field-sortable-"]',
    ).length;
    const btn = screen.getByTestId("form-field-palette-signature");
    fireEvent.click(btn);
    await waitFor(() => {
      const after = document.querySelectorAll(
        '[data-testid^="form-field-sortable-"]',
      ).length;
      expect(after).toBe(initialRowCount + 1);
    });
  });
});


// ──────────────────────────────────────────────────────────────────
// Widget renderer — source parse (vanilla JS bundle, no DOM mount)
// ──────────────────────────────────────────────────────────────────
describe("widget bundle · TD-52 renderer cases", () => {
  const WIDGET = fs.readFileSync(
    path.resolve(__dirname, "../../public/widget/form.js"),
    "utf8",
  );

  it.each([
    "signature", "address_manual", "rating_stars", "file_multi_upload",
  ])("switch case for '%s' is defined", (t) => {
    expect(WIDGET).toMatch(new RegExp(`case\\s+"${t}"\\s*:`));
  });

  it("signature case renders a <canvas> + hidden input + Clear button", () => {
    const match = WIDGET.match(
      /case "signature": \{([\s\S]*?)break;\s*\}/,
    );
    expect(match).toBeTruthy();
    const src = match[1];
    expect(src.includes('el("canvas"')).toBe(true);
    expect(src.includes('type: "hidden"')).toBe(true);
    expect(src.includes("Clear")).toBe(true);
    // Must bind the hidden input's value to the canvas.toDataURL
    // call so the signature travels on form submit.
    expect(src.includes("toDataURL")).toBe(true);
  });

  it("address_manual case renders 4 inputs with __line1/__city/__state/__zip sub-names", () => {
    const match = WIDGET.match(
      /case "address_manual": \{([\s\S]*?)break;\s*\}/,
    );
    expect(match).toBeTruthy();
    const src = match[1];
    expect(src.includes('"__line1"')).toBe(true);
    expect(src.includes('"__city"')).toBe(true);
    expect(src.includes('"__state"')).toBe(true);
    expect(src.includes('"__zip"')).toBe(true);
  });

  it("rating_stars case renders 5 radios with values 1..5", () => {
    const match = WIDGET.match(
      /case "rating_stars": \{([\s\S]*?)break;\s*\}/,
    );
    expect(match).toBeTruthy();
    const src = match[1];
    // Loop 1..5 → String(rs) values.
    expect(src.includes("for (var rs = 1; rs <= 5; rs++)")).toBe(true);
    expect(src.includes('type: "radio"')).toBe(true);
    // Required check still participates with the first star.
    expect(src.includes("rs === 1")).toBe(true);
  });

  it("file_multi_upload case uses multiple=''", () => {
    const match = WIDGET.match(
      /case "file_multi_upload":([\s\S]*?)break;/,
    );
    expect(match).toBeTruthy();
    expect(match[1].includes('multiple: ""')).toBe(true);
  });

  it("collectAnswers folds address_manual sub-field names into a nested object", () => {
    expect(WIDGET).toMatch(/__(line1|city|state|zip)/);
    // The folding regex captures the parent name + slot.
    expect(WIDGET).toMatch(/\^\(\.\+\)__\(line1\|city\|state\|zip\)\$/);
    // And multi-file inputs serialise as a list of names.
    expect(WIDGET.includes("input.multiple")).toBe(true);
  });
});
