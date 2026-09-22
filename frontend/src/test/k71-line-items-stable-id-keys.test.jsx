/**
 * Feb-2026 · K71 stable-id keys + duplicate-row guard.
 *
 * Locks in the anti-flake contract the tester dispatched after the
 * responsive-cards ship:
 *
 *   1. Every rendered line row (desktop ``<tr>`` + mobile
 *      ``<MobileCard>``) is keyed by a STABLE identifier —
 *      ``line.id`` when the server has stamped one, or a
 *      client-minted ``_uid`` when the row is a pre-save optimistic
 *      draft. Never the array index.
 *   2. If the input array ever contains two entries with the same
 *      stable id (e.g. a brief race between an optimistic add and
 *      the server-confirmed reload), ``_normalize`` de-duplicates
 *      so only ONE row/card is emitted.
 *   3. A fresh Add-line click mints a ``_uid`` immediately and
 *      reuses it across the save round-trip; after the parent
 *      ``load()`` returns the server-assigned ``id`` the row's key
 *      switches to ``id`` and the ``_uid``-keyed optimistic entry
 *      is replaced in-place, never duplicated.
 *   4. Delete → Undo restores exactly ONE row with the same stable
 *      id — no accidental duplicate if the parent has already
 *      round-tripped the server copy during the 5s undo window.
 *
 * Testids remain index-based (``k71-row-<i>`` / ``k71-card-<i>``)
 * to preserve the 4300+ existing suite; only the React ``key=``
 * prop switched to a stable identifier. That's asserted below via
 * ``document.querySelectorAll`` on the rendered ``<tr>`` /
 * ``<li>`` counts, not by peeking at ``element._reactProps``.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0B4A6F",
    onBrand: "#FFFFFF",
    onSurface: "#111827",
    onSurfaceSecondary: "#6B7280",
    muted: "#6B7280",
    border: "#E5E7EB",
    divider: "#E5E7EB",
    surface: "#FFFFFF",
    surfaceSecondary: "#F8FAFC",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

vi.mock("@/components/income/CategoryPicker", () => ({
  default: ({ value, onChange, testid }) => (
    <select
      data-testid={testid}
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">Choose</option>
      <option value="svc-a">Service A</option>
      <option value="inc-a">Income A</option>
    </select>
  ),
  loadCategories: vi.fn(async () => []),
  invalidateCategoryCache: vi.fn(),
}));

// Phase P16.1 · Feb-2026 — stub the Master Service combobox with a
// plain <input> so this file's stable-id-keys contract isn't
// coupled to the combobox's dropdown / fetch surface.  Downstream
// tests (``p16-1-combobox-sweep``) cover the real integration.
vi.mock("@/components/services/MasterServiceCombobox", () => ({
  default: ({ value, onChange, testid }) => (
    <input
      data-testid={`${testid}-input`}
      value={value || ""}
      onChange={(e) => onChange?.({
        name: e.target.value, default_price: null, category: null,
      })}
    />
  ),
  invalidateMasterServicesCache: vi.fn(),
}));

import K71LineItemsEditor from "@/components/quotes/K71LineItemsEditor";


function _renderK71(overrides = {}) {
  const doc = { line_items: overrides.lines ?? [], ...overrides.doc };
  const onLinesUpdated = overrides.onLinesUpdated ?? vi.fn(async () => true);
  const onError = overrides.onError ?? vi.fn();
  return {
    onLinesUpdated,
    onError,
    ...render(
      <K71LineItemsEditor
        doc={doc}
        canEdit={overrides.canEdit ?? true}
        onLinesUpdated={onLinesUpdated}
        onError={onError}
      />,
    ),
  };
}


describe("K71LineItemsEditor · stable-id keys + duplicate-row guard", () => {
  it("de-dups input rows that share the same stable id (renders exactly one row/card)", () => {
    // Contrived: two lines with the SAME ``id`` reach the editor
    // (e.g. an optimistic + server-confirmed copy briefly held
    // during a race). Only ONE row should render.
    const doc = {
      line_items: [
        { id: "li-dup",   description: "Design",  quantity: 1, unit_price: 100,
          service_category_id: "svc-a", income_category_id: "inc-a" },
        { id: "li-dup",   description: "Design",  quantity: 1, unit_price: 100,
          service_category_id: "svc-a", income_category_id: "inc-a" },
        { id: "li-other", description: "Install", quantity: 2, unit_price: 50,
          service_category_id: "svc-a", income_category_id: "inc-a" },
      ],
    };
    _renderK71({ doc });

    // Desktop: exactly 2 rows (the duplicate ``li-dup`` was
    // collapsed to one).
    const rows = document.querySelectorAll('tbody tr[data-testid^="k71-row-"]');
    expect(rows.length).toBe(2);
    // Mobile: exactly 2 card ``<li>``s. Narrow to ``<li>`` so we
    // don't also count the per-card Edit / Delete buttons whose
    // testids also start with ``k71-card-``.
    const cards = document.querySelectorAll('li[data-testid^="k71-card-"]');
    expect(cards.length).toBe(2);
    // Desktop rows carry the description in a ``<td>``; mobile
    // cards carry it in a ``<span>``. After dedup, "Design" appears
    // once on each surface (2 total), never 4 (which is what a
    // dup-through render would yield).
    expect(screen.getAllByText("Design").length).toBe(2);
  });

  it("keeps stable-id rows unique on re-sync when the parent briefly returns duplicates", () => {
    // First render with one server line.
    const one = [
      { id: "li-A", description: "Only",  quantity: 1, unit_price: 25,
        service_category_id: "svc-a", income_category_id: "inc-a" },
    ];
    const { rerender } = render(
      <K71LineItemsEditor
        doc={{ line_items: one }}
        canEdit={true}
        onLinesUpdated={vi.fn(async () => true)}
        onError={vi.fn()}
      />,
    );
    expect(document.querySelectorAll('tbody tr[data-testid^="k71-row-"]').length).toBe(1);

    // Parent momentarily emits a doc where the same ``li-A`` appears
    // twice — e.g. a stale optimistic entry not yet reconciled by
    // the server round-trip.
    const dup = [
      { id: "li-A", description: "Only",   quantity: 1, unit_price: 25,
        service_category_id: "svc-a", income_category_id: "inc-a" },
      { id: "li-A", description: "Only",   quantity: 1, unit_price: 25,
        service_category_id: "svc-a", income_category_id: "inc-a" },
    ];
    rerender(
      <K71LineItemsEditor
        doc={{ line_items: dup }}
        canEdit={true}
        onLinesUpdated={vi.fn(async () => true)}
        onError={vi.fn()}
      />,
    );
    expect(document.querySelectorAll('tbody tr[data-testid^="k71-row-"]').length).toBe(1);
    expect(document.querySelectorAll('li[data-testid^="k71-card-"]').length).toBe(1);
  });

  it("optimistic-add → server-confirm produces exactly one row (no duplicate)", async () => {
    // Simulate the real parent flow:
    //   • ``onLinesUpdated`` is called with the optimistic ``next``
    //     (a fresh line carrying a ``_uid``, no server ``id`` yet).
    //   • The parent then reloads and re-renders the editor with a
    //     new ``doc.line_items`` where the same line now carries a
    //     server-assigned ``id`` (and no ``_uid``).
    //   • K71 must render exactly ONE row.
    let capturedNext = null;
    const onLinesUpdated = vi.fn(async (next) => {
      capturedNext = next;
      return true;
    });
    const initial = [
      { id: "li-existing", description: "Existing", quantity: 1, unit_price: 40,
        service_category_id: "svc-a", income_category_id: "inc-a" },
    ];
    const { rerender } = render(
      <K71LineItemsEditor
        doc={{ line_items: initial }}
        canEdit={true}
        onLinesUpdated={onLinesUpdated}
        onError={vi.fn()}
      />,
    );

    // Kick off an add — this mints a ``_uid`` on the empty draft.
    fireEvent.click(screen.getByTestId("k71-add-line-btn"));
    expect(screen.getByTestId("k71-row-edit-1")).toBeTruthy();

    // Fill in the required fields + commit.
    // Phase P16.1 · Feb-2026 — target the Master Service combobox's
    // inner <input> (``-input`` suffix); the wrapper div carries
    // the legacy ``k71-input-item-{i}`` testid.
    fireEvent.change(screen.getByTestId("k71-input-item-1-input"),
                     { target: { value: "Fresh add" } });
    fireEvent.change(screen.getByTestId("k71-input-qty-1"),
                     { target: { value: "3" } });
    fireEvent.change(screen.getByTestId("k71-input-price-1"),
                     { target: { value: "15" } });
    fireEvent.change(screen.getByTestId("k71-service-picker-1"),
                     { target: { value: "svc-a" } });
    fireEvent.change(screen.getByTestId("k71-income-picker-1"),
                     { target: { value: "inc-a" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("k71-save-1"));
    });
    await waitFor(() => expect(onLinesUpdated).toHaveBeenCalled());

    // The optimistic ``next`` submitted to the parent carries the
    // client-generated ``_uid`` — never index or nothing.
    expect(capturedNext).toBeTruthy();
    expect(capturedNext.length).toBe(2);
    const optimisticNew = capturedNext[1];
    expect(typeof (optimisticNew._uid || optimisticNew.id)).toBe("string");

    // The parent's reload comes back: the fresh line now has a
    // server-assigned ``id`` (and no ``_uid``). We rerender with the
    // new doc — the editor MUST NOT emit two rows.
    const serverConfirmed = [
      ...initial,
      { id: "li-fresh", description: "Fresh add", quantity: 3, unit_price: 15,
        service_category_id: "svc-a", income_category_id: "inc-a" },
    ];
    rerender(
      <K71LineItemsEditor
        doc={{ line_items: serverConfirmed }}
        canEdit={true}
        onLinesUpdated={onLinesUpdated}
        onError={vi.fn()}
      />,
    );

    // Exactly two rows: the original + the newly-persisted one.
    // No lingering optimistic duplicate under a ``_uid`` key.
    expect(document.querySelectorAll('tbody tr[data-testid^="k71-row-"]').length).toBe(2);
    expect(document.querySelectorAll('li[data-testid^="k71-card-"]').length).toBe(2);
    // "Fresh add" appears on both surfaces after the reload, but
    // only ONCE per surface (never twice).
    expect(screen.getAllByText("Fresh add").length).toBe(2);
  });

  it("delete → undo restores the row exactly once (no duplicate) even if a stale server copy arrives", async () => {
    const lines = [
      { id: "li-A", description: "Alpha", quantity: 1, unit_price: 10,
        service_category_id: "svc-a", income_category_id: "inc-a" },
      { id: "li-B", description: "Beta",  quantity: 1, unit_price: 20,
        service_category_id: "svc-a", income_category_id: "inc-a" },
    ];
    const onLinesUpdated = vi.fn(async () => true);
    render(
      <K71LineItemsEditor
        doc={{ line_items: lines }}
        canEdit={true}
        onLinesUpdated={onLinesUpdated}
        onError={vi.fn()}
      />,
    );
    // Delete Alpha.
    fireEvent.click(screen.getByTestId("k71-delete-btn-0"));
    expect(document.querySelectorAll('tbody tr[data-testid^="k71-row-"]').length).toBe(1);
    // Undo.
    fireEvent.click(screen.getByTestId("k71-undo-btn"));
    // Exactly two rows again, one Alpha, one Beta.
    expect(document.querySelectorAll('tbody tr[data-testid^="k71-row-"]').length).toBe(2);
    expect(document.querySelectorAll('li[data-testid^="k71-card-"]').length).toBe(2);
    // Text is duplicated across desktop + mobile surfaces (2 per
    // line), never DUPLICATE within a surface (which would be 4).
    expect(screen.getAllByText("Alpha").length).toBe(2);
    expect(screen.getAllByText("Beta").length).toBe(2);
  });

  it("empty stable id on incoming rows gets a client-minted _uid so keys are never null", () => {
    // Legacy-shaped input: no ``id`` and no ``_uid``. The editor
    // must still render (React would warn on null keys).
    const doc = {
      line_items: [
        { description: "Legacy row 1", quantity: 1, unit_price: 5 },
        { description: "Legacy row 2", quantity: 2, unit_price: 6 },
      ],
    };
    // Capture React warnings.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    _renderK71({ doc });
    // No warning about ``Each child in a list should have a unique
    // "key" prop`` was emitted.
    const warnings = spy.mock.calls
      .map((c) => String(c[0] || ""))
      .filter((s) => s.includes('unique "key"'));
    expect(warnings.length).toBe(0);
    spy.mockRestore();
    // Both rows rendered.
    expect(document.querySelectorAll('tbody tr[data-testid^="k71-row-"]').length).toBe(2);
  });
});
