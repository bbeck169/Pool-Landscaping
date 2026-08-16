// Queue Item 2 · Feb-2026 — source-inspection vitest for the Admin
// Customer Tags CRUD upgrade (/admin/tags).
//
// Uses fs.readFileSync so it stays lightweight (no ReactDOM, no
// router harness) and mirrors the Phase 41.2 pattern already
// established in this repo. Locks in:
//   • "New tag" button + editor modal (name + color picker)
//   • Palette swatches available in the editor
//   • Per-row inline edit + delete affordances
//   • Delete confirm modal with live usage-count copy
//   • System-tag lock icon + disabled edit/delete + tooltip
//   • Search input rendered when totalCount > 10
//   • Bulk-select toolbar preserved
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const PAGE_PATH = resolve(__dirname, "../pages/admin/AdminTagsList.jsx");

const readPage = () => readFileSync(PAGE_PATH, "utf8");

describe("Queue Item 2 · AdminTagsList CRUD upgrade", () => {
  it("page file exists at the expected route mount", () => {
    expect(existsSync(PAGE_PATH)).toBe(true);
  });

  const src = readPage();

  it("keeps the /admin/tags page testID and existing bulk toolkit imports", () => {
    expect(src).toContain('data-testid="admin-tags-page"');
    expect(src).toContain('from "@/components/bulk-select/BulkSelectToolkit"');
    // Preserved bulk behaviour from the previous phase.
    expect(src).toContain("bulk-delete");
    expect(src).toContain("bulk-update");
  });

  it("exposes a New Tag button that opens the editor modal", () => {
    expect(src).toContain('data-testid="admin-tags-new-btn"');
    expect(src).toContain('data-testid="tag-editor-modal"');
    expect(src).toContain('data-testid="tag-editor-name-input"');
    expect(src).toContain('data-testid="tag-editor-submit"');
    expect(src).toContain('data-testid="tag-editor-cancel"');
  });

  it("renders a color-swatch palette inside the editor", () => {
    expect(src).toContain('data-testid="tag-editor-palette"');
    // At least the two system-tag colors + a handful of pastels are
    // exposed so admins can match/re-use.
    expect(src).toContain("#DBEAFE");
    expect(src).toContain("#FEE2E2");
    expect(src).toContain("#22C55E");
    expect(src).toContain("#94A3B8");
  });

  it("wires per-row edit + delete affordances via templated testIDs", () => {
    expect(src).toContain("`admin-tag-edit-btn-${r.id}`");
    expect(src).toContain("`admin-tag-delete-btn-${r.id}`");
    expect(src).toContain("`admin-tag-usage-${r.id}`");
  });

  it("locks system tags with the Lock icon + tooltip + disabled buttons", () => {
    expect(src).toContain('from "lucide-react"');
    expect(src).toContain("Lock");
    // Tooltip copy is centralized in a constant.
    expect(src).toContain("System tags cannot be modified");
    expect(src).toContain("SYSTEM_LOCK_TOOLTIP");
    // Both action buttons disable + show the tooltip when isSystem.
    expect(src).toContain("disabled={isSystem}");
    expect(src).toMatch(/isSystem \? SYSTEM_LOCK_TOOLTIP/);
    // Lock icon testID (per-row).
    expect(src).toContain("`admin-tag-system-lock-${r.id}`");
    // Visual "System" badge next to the name.
    expect(src).toMatch(/>\s*System\s*</);
  });

  it("mounts the single-tag delete confirm modal with a live usage count", () => {
    expect(src).toContain('data-testid="admin-tag-delete-modal"');
    expect(src).toContain('data-testid="admin-tag-delete-confirm"');
    expect(src).toContain('data-testid="admin-tag-delete-cancel"');
    expect(src).toContain('data-testid="admin-tag-delete-usage-count"');
    // Copy communicates cascade behaviour.
    expect(src).toMatch(/applied to/);
    expect(src).toMatch(/cannot be undone/);
  });

  it("renders the search input only when the tag count exceeds 10", () => {
    expect(src).toContain("SEARCH_VISIBILITY_THRESHOLD");
    expect(src).toContain("10");
    expect(src).toContain('data-testid="admin-tags-search-input"');
    expect(src).toMatch(/totalCount > SEARCH_VISIBILITY_THRESHOLD/);
  });

  it("uses the correct backend endpoints for CRUD", () => {
    // POST create / PATCH rename+recolor / DELETE cascade
    expect(src).toContain('api.post("/customer-tags", payload)');
    expect(src).toMatch(/api\.patch\(`\/customer-tags\/\$\{editor\.tag\.id\}`, payload\)/);
    expect(src).toMatch(/api\.del\(`\/customer-tags\/\$\{delModal\.tag\.id\}`\)/);
  });

  it("handles duplicate + system-readonly error codes with human toasts", () => {
    expect(src).toContain("duplicate_tag_name");
    expect(src).toContain("system_tag_readonly");
  });
});
