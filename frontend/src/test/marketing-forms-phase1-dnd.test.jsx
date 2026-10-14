/**
 * Feb-2026 · Form Builder P2 #12 · Phase 1 Commit 1 — DnD vitest.
 *
 * Locks the DnD field reorder + left-rail palette UI on the Marketing
 * Forms admin page. Covers (8 cases):
 *   1. Palette renders one button per supported field type.
 *   2. Palette button click adds a field of that type at the end.
 *   3. Each rendered field row has a drag handle (`form-field-drag-N`).
 *   4. Each row remains inside a sortable wrapper (`form-field-sortable-N`).
 *   5. ArrowUp / ArrowDown a11y fallback still reorders.
 *   6. "Add field" button (click-add, non-palette) still works.
 *   7. Save payload omits the client-only `_rowId` key.
 *   8. Source-lint: @dnd-kit imports present, no new npm deps.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";

// Shared @/api mock — hoisted via vi.hoisted so the module load
// below sees the stubs.
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

// Minimal Hero + Theme + RichText stubs — DnD vitest doesn't need
// Tiptap or image library wiring.
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


const MFP_PATH = path.resolve(
  process.cwd(), "src/pages/marketing/MarketingFormsPage.jsx",
);
const PKG_PATH = path.resolve(process.cwd(), "package.json");


async function _openEditor() {
  // Click "New form" to open the editor drawer with an empty-template
  // seed (one default `text` field).
  const newBtn = await screen.findByTestId("form-create-btn");
  fireEvent.click(newBtn);
  await screen.findByTestId("form-edit-drawer");
}


beforeEach(() => {
  _mocks.get.mockReset();
  _mocks.post.mockReset();
  _mocks.patch.mockReset();
  _mocks.del.mockReset();
  // GET /admin/forms → empty list; GET /tenants/mine/widget-config
  // → defaults.  Any other GET → empty object.
  _mocks.get.mockImplementation(async (p) => {
    if (p === "/admin/forms") return [];
    if (p === "/tenants/mine/widget-config") {
      return { public_key: "pk_test", turnstile_site_key: null };
    }
    return {};
  });
  _mocks.post.mockResolvedValue({
    id: "frm_1", slug: "frm-1", fields: [], hero: null,
  });
  _mocks.patch.mockResolvedValue({
    id: "frm_1", slug: "frm-1", fields: [], hero: null,
  });
});
afterEach(() => cleanup());


describe("MarketingFormsPage · Phase 1 DnD + palette", () => {
  // ──────────────────────────────────────────────────────────────
  // Source-lint — guards the @dnd-kit imports + confirms no new deps.
  // ──────────────────────────────────────────────────────────────
  it("source-lints @dnd-kit imports + no new deps in package.json", () => {
    const src = fs.readFileSync(MFP_PATH, "utf8");
    expect(src).toMatch(/from\s+"@dnd-kit\/core"/);
    expect(src).toMatch(/from\s+"@dnd-kit\/sortable"/);
    expect(src).toMatch(/from\s+"@dnd-kit\/utilities"/);
    // No new deps — all three @dnd-kit libs were already in the bundle
    // (used by the Email Builder Phase 1/2 work).
    const pkg = JSON.parse(fs.readFileSync(PKG_PATH, "utf8"));
    expect(pkg.dependencies["@dnd-kit/core"]).toBeTruthy();
    expect(pkg.dependencies["@dnd-kit/sortable"]).toBeTruthy();
    expect(pkg.dependencies["@dnd-kit/utilities"]).toBeTruthy();
  });

  // ──────────────────────────────────────────────────────────────
  // 1. Palette renders one button per field type
  // ──────────────────────────────────────────────────────────────
  it("renders the left-rail palette with one button per supported field type", async () => {
    render(<MarketingFormsPage />);
    await _openEditor();
    const palette = await screen.findByTestId("form-field-palette");
    expect(palette).toBeTruthy();
    // 14 types in the registry (text/email/phone/textarea/number/url/
    // date/address_google/dropdown/multiselect/checkbox/radio/file/section).
    const types = [
      "text", "email", "phone", "textarea", "number", "url", "date",
      "address_google", "dropdown", "multiselect", "checkbox", "radio",
      "file", "section",
    ];
    for (const t of types) {
      expect(screen.getByTestId(`form-field-palette-${t}`)).toBeTruthy();
    }
  });

  // ──────────────────────────────────────────────────────────────
  // 2. Palette click adds a typed field at the end
  // ──────────────────────────────────────────────────────────────
  it("clicking a palette button appends a field of that type", async () => {
    render(<MarketingFormsPage />);
    await _openEditor();
    // Default seed: one `text` field.
    expect(screen.getByTestId("form-field-0")).toBeTruthy();
    // Click palette → add email field.
    fireEvent.click(screen.getByTestId("form-field-palette-email"));
    expect(screen.getByTestId("form-field-1")).toBeTruthy();
    const newType = screen.getByTestId("form-field-type-1").value;
    expect(newType).toBe("email");
  });

  // ──────────────────────────────────────────────────────────────
  // 3. Each rendered field row has a drag handle
  // ──────────────────────────────────────────────────────────────
  it("renders a drag handle on each field row", async () => {
    render(<MarketingFormsPage />);
    await _openEditor();
    expect(screen.getByTestId("form-field-drag-0")).toBeTruthy();
    fireEvent.click(screen.getByTestId("form-field-palette-phone"));
    expect(screen.getByTestId("form-field-drag-0")).toBeTruthy();
    expect(screen.getByTestId("form-field-drag-1")).toBeTruthy();
  });

  // ──────────────────────────────────────────────────────────────
  // 4. Sortable wrapper surrounds each row
  // ──────────────────────────────────────────────────────────────
  it("renders each field inside a sortable wrapper", async () => {
    render(<MarketingFormsPage />);
    await _openEditor();
    fireEvent.click(screen.getByTestId("form-field-palette-phone"));
    expect(screen.getByTestId("form-field-sortable-0")).toBeTruthy();
    expect(screen.getByTestId("form-field-sortable-1")).toBeTruthy();
  });

  // ──────────────────────────────────────────────────────────────
  // 5. a11y arrow-key fallback — move up / move down still works
  // ──────────────────────────────────────────────────────────────
  it("ArrowUp / ArrowDown reorder buttons still function (a11y fallback)", async () => {
    render(<MarketingFormsPage />);
    await _openEditor();
    fireEvent.click(screen.getByTestId("form-field-palette-email"));
    // Label the two rows so we can prove the swap. Row 0 = default
    // text, row 1 = email just appended.
    fireEvent.change(screen.getByTestId("form-field-label-0"),
                      { target: { value: "First row" } });
    fireEvent.change(screen.getByTestId("form-field-label-1"),
                      { target: { value: "Second row" } });
    expect(screen.getByTestId("form-field-label-0").value).toBe("First row");
    // Click Move Down on row 0 → row 0 should become "Second row".
    fireEvent.click(screen.getByTestId("form-field-down-0"));
    expect(screen.getByTestId("form-field-label-0").value).toBe("Second row");
    expect(screen.getByTestId("form-field-label-1").value).toBe("First row");
  });

  // ──────────────────────────────────────────────────────────────
  // 6. "Add field" button (the generic non-palette path) still works
  // ──────────────────────────────────────────────────────────────
  it("the generic 'Add field' button still appends a text field", async () => {
    render(<MarketingFormsPage />);
    await _openEditor();
    fireEvent.click(screen.getByTestId("form-add-field-btn"));
    expect(screen.getByTestId("form-field-1")).toBeTruthy();
    expect(screen.getByTestId("form-field-type-1").value).toBe("text");
  });

  // ──────────────────────────────────────────────────────────────
  // 7. Save payload omits the client-only `_rowId` key
  // ──────────────────────────────────────────────────────────────
  it("save payload does not leak the client-only `_rowId` into the backend body", async () => {
    render(<MarketingFormsPage />);
    await _openEditor();
    // Give the form a name + save.
    fireEvent.change(screen.getByTestId("form-name-input"),
                      { target: { value: "Phase1 DnD Fixture" } });
    fireEvent.change(screen.getByTestId("form-field-label-0"),
                      { target: { value: "Full name" } });
    fireEvent.click(screen.getByTestId("form-save-btn"));
    await waitFor(() => expect(_mocks.post).toHaveBeenCalled());
    const [path, body] = _mocks.post.mock.calls[0];
    expect(path).toBe("/admin/forms");
    expect(Array.isArray(body.fields)).toBe(true);
    for (const f of body.fields) {
      expect(f._rowId).toBeUndefined();
    }
  });
});
