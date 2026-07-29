/**
 * Admin Sidebar pinned nav · Feb-2026.
 *
 * Covers:
 *   1. MAX_PINNED cap is 20 (bumped from 8 per user request).
 *   2. DnD reorder produces the correct new array via arrayMove.
 *   3. localStorage persists the reordered array.
 *
 * We do not mount the full AdminSidebar (it pulls in dozens of route
 * modules).  Instead we assert the module-local constant by reading
 * source, and verify @dnd-kit's arrayMove semantics directly against
 * the persistence contract the sidebar uses.
 */
import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { arrayMove } from "@dnd-kit/sortable";
import fs from "fs";
import path from "path";

afterEach(() => cleanup());

function readAdminSidebarSource() {
  return fs.readFileSync(
    path.resolve(__dirname, "../layouts/AdminSidebar.jsx"),
    "utf8",
  );
}

describe("AdminSidebar pinned-nav cap", () => {
  it("MAX_PINNED constant is set to 20", () => {
    const src = readAdminSidebarSource();
    const m = src.match(/const\s+MAX_PINNED\s*=\s*(\d+)/);
    expect(m).not.toBeNull();
    expect(parseInt(m[1], 10)).toBe(20);
  });

  it("togglePin trims to MAX_PINNED (referenced by name, not literal)", () => {
    const src = readAdminSidebarSource();
    // Ensure togglePin uses the named constant — a hardcoded literal
    // like ``slice(0, 8)`` is the old bug this test guards against.
    const trimLine = src.match(/togglePin\s*=\s*\([^)]*\)\s*=>[\s\S]*?slice\(0,\s*([A-Z_]+)\s*\)/);
    expect(trimLine).not.toBeNull();
    expect(trimLine[1]).toBe("MAX_PINNED");
  });
});

describe("AdminSidebar pinned drag-and-drop", () => {
  it("wires up DndContext + SortableContext + arrayMove", () => {
    const src = readAdminSidebarSource();
    expect(src).toContain("DndContext");
    expect(src).toContain("SortableContext");
    expect(src).toContain("arrayMove");
    expect(src).toContain("verticalListSortingStrategy");
    // Keyboard accessibility — the sortable keyboard coordinate getter.
    expect(src).toContain("sortableKeyboardCoordinates");
    // The sortable row uses useSortable.
    expect(src).toContain("useSortable");
    // Handle test id present for e2e / a11y probing.
    expect(src).toContain("nav-pinned-handle-");
  });

  it("arrayMove reorders position 0 → 2 correctly", () => {
    const before = ["/", "/customers", "/jobs", "/invoices"];
    const after = arrayMove(before, 0, 2);
    expect(after).toEqual(["/customers", "/jobs", "/", "/invoices"]);
  });

  it("arrayMove reorders position 3 → 1 correctly", () => {
    const before = ["/", "/customers", "/jobs", "/invoices"];
    const after = arrayMove(before, 3, 1);
    expect(after).toEqual(["/", "/invoices", "/customers", "/jobs"]);
  });

  it("handleDragEnd persistence contract — the reordered array is what saveLS(LS_PINNED, …) writes", () => {
    // The sidebar uses `useState(loadLS(LS_PINNED, []))` +
    // `useEffect(() => saveLS(LS_PINNED, pinned), [pinned])`.
    // So a reorder that returns a new `pinned` array via arrayMove
    // WILL be persisted verbatim.  We assert that contract remains
    // in the source so a future refactor doesn't accidentally drop
    // the auto-save effect.
    const src = readAdminSidebarSource();
    expect(src).toContain("useEffect(() => saveLS(LS_PINNED, pinned), [pinned])");
    // And the reorder handler calls arrayMove on the pinned state.
    expect(src).toContain("arrayMove(prev, from, to)");
  });
});
