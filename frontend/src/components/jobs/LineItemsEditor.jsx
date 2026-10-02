/**
 * Feb-2026 · Jobs Overhaul Phase 3c — shared in-memory line-items editor.
 *
 * Controlled presentation component for the in-memory line-items editor
 * used on the New Job form (``/jobs/new``). The server-backed sibling for
 * the Job Detail page lives in ``pages/jobs/LineItemsSection.jsx`` and is
 * deliberately NOT merged with this component — the two surfaces diverge
 * on data flow (in-memory array vs. per-row HTTP CRUD), row shape (4
 * fields vs. 10), role gating, totals computation, and validation. See
 * the Phase 3c discovery report for the full delta.
 *
 * Scope invariants (locked):
 *   * This component is **presentation only** — all state ownership
 *     (``lines``, pricebook search string, add/update/remove handlers,
 *     subtotal-driven sibling-field effects) stays in the parent. The
 *     parent passes a fully-controlled prop surface and the editor
 *     fires callbacks on every mutation.
 *   * The outer wrapper card testid (``jf-line-items-section``) is
 *     emitted by the PARENT, not this component. Keep that invariant
 *     so JobNew's existing wrapper + the surrounding card chrome stay
 *     identical byte-for-byte.
 *   * Testids on the inner affordances are prefix-driven via the
 *     ``testidPrefix`` prop (default ``"jf-li"``) so JobNew sees zero
 *     drift and future consumers can namespace their own instance
 *     without a collision.
 *
 * Props (strict):
 *   - ``lines`` (array, required)              — the current line-items array.
 *   - ``onAddBlank`` (function)                — called on "Add line" click.
 *   - ``onAddFromPricebook`` (function)        — called with the picked pricebook row.
 *   - ``onUpdateLine`` (function)              — called with ``(idx, patch)`` on cell edit.
 *   - ``onRemoveLine`` (function)              — called with ``idx`` on trash click.
 *   - ``pricebookSearch`` (string)             — controlled pricebook search value.
 *   - ``onPricebookSearchChange`` (function)   — called with the next search string.
 *   - ``testidPrefix`` (string, default "jf-li") — namespace for all internal testids.
 *
 * Row shape (parent-owned; must match the server ``LineItem`` 4-field subset):
 *   ``{description: string, quantity: number, unit_price: number, pricebook_item_id?: string|null}``
 */
import React, { useMemo } from "react";
import { Plus, Trash2 } from "lucide-react";
import { colors } from "@/theme";
import { Button } from "@/components/ui-kit";
import PricebookItemPicker from "@/components/pricebook/PricebookItemPicker";

export default function LineItemsEditor({
  lines = [],
  onAddBlank,
  onAddFromPricebook,
  onUpdateLine,
  onRemoveLine,
  pricebookSearch,
  onPricebookSearchChange,
  testidPrefix = "jf-li",
}) {
  // Subtotal is recomputed inside the editor for the tfoot label.  The
  // parent can — and does, for the price-sync side effect in JobNew —
  // compute its own subtotal from ``lines`` using the same formula.
  const subtotal = useMemo(
    () =>
      (lines || []).reduce(
        (sum, li) =>
          sum
          + (Number(li.quantity) || 0) * (Number(li.unit_price) || 0),
        0,
      ),
    [lines],
  );

  return (
    <>
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <div>
          <h3
            className="text-lg font-bold"
            style={{ color: colors.onSurface }}
          >
            Line Items
          </h3>
          <p className="text-xs" style={{ color: colors.muted }}>
            Add items from the pricebook or type your own. The
            subtotal auto-fills the Price field above.
          </p>
        </div>
        <div className="flex items-center">
          <Button
            type="button"
            testid={`${testidPrefix}-add-blank`}
            onClick={onAddBlank}
          >
            <Plus size={14} /> Add line
          </Button>
        </div>
      </div>
      {/* "Add from pricebook" affordance — the inline picker acts
          as a search-and-add. Typing surfaces the pricebook
          dropdown; picking a row appends a line and clears the
          input.  See ``@/components/pricebook/PricebookItemPicker``
          for the debounce + keyboard-navigation contract. */}
      <div className="mb-3">
        <PricebookItemPicker
          value={pricebookSearch}
          onChange={onPricebookSearchChange}
          onSelect={(row) => {
            onAddFromPricebook(row);
            onPricebookSearchChange("");
          }}
          placeholder="Add from pricebook — search by item name…"
          testidPrefix={`${testidPrefix}-pricebook`}
          wrapperTestid={`${testidPrefix}-add-pricebook`}
          inputTestid={`${testidPrefix}-pricebook-input`}
        />
      </div>
      {(lines || []).length === 0 ? (
        <div
          className="p-4 text-sm text-center rounded-lg"
          style={{
            background: colors.surfaceSecondary,
            color: colors.muted,
          }}
          data-testid={`${testidPrefix}-empty`}
        >
          No line items yet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table
            className="w-full text-sm"
            data-testid={`${testidPrefix}-table`}
          >
            <thead>
              <tr>
                {["Description", "Qty", "Unit", "Total", ""].map((h) => (
                  <th
                    key={h || "actions"}
                    className={
                      h === "Total"
                        ? "text-right text-[10px] uppercase font-bold px-2 py-1"
                        : "text-left text-[10px] uppercase font-bold px-2 py-1"
                    }
                    style={{
                      color: colors.muted,
                      borderBottom: `1px solid ${colors.border}`,
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {lines.map((li, i) => {
                const rowTotal =
                  (Number(li.quantity) || 0)
                  * (Number(li.unit_price) || 0);
                return (
                  <tr
                    key={i}
                    data-testid={`${testidPrefix}-row-${i}`}
                    style={{
                      borderBottom: `1px solid ${colors.border}`,
                    }}
                  >
                    <td className="px-2 py-2 align-top">
                      <input
                        type="text"
                        value={li.description || ""}
                        onChange={(e) =>
                          onUpdateLine(i, {
                            description: e.target.value,
                          })
                        }
                        className="w-full px-2 py-1 rounded-md text-sm"
                        style={{
                          border: `1px solid ${colors.border}`,
                          background: colors.surface,
                          color: colors.onSurface,
                        }}
                        data-testid={`${testidPrefix}-desc-${i}`}
                      />
                    </td>
                    <td className="px-2 py-2 align-top">
                      <input
                        type="number"
                        min="0"
                        step="0.5"
                        value={li.quantity ?? 1}
                        onChange={(e) =>
                          onUpdateLine(i, {
                            quantity: e.target.value,
                          })
                        }
                        className="w-20 px-2 py-1 rounded-md text-sm"
                        style={{
                          border: `1px solid ${colors.border}`,
                          background: colors.surface,
                          color: colors.onSurface,
                        }}
                        data-testid={`${testidPrefix}-qty-${i}`}
                      />
                    </td>
                    <td className="px-2 py-2 align-top">
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={li.unit_price ?? 0}
                        onChange={(e) =>
                          onUpdateLine(i, {
                            unit_price: e.target.value,
                          })
                        }
                        className="w-24 px-2 py-1 rounded-md text-sm"
                        style={{
                          border: `1px solid ${colors.border}`,
                          background: colors.surface,
                          color: colors.onSurface,
                        }}
                        data-testid={`${testidPrefix}-unit-${i}`}
                      />
                    </td>
                    <td
                      className="px-2 py-2 align-top text-right font-semibold"
                      style={{ color: colors.onSurface }}
                      data-testid={`${testidPrefix}-total-${i}`}
                    >
                      {`$${rowTotal.toFixed(2)}`}
                    </td>
                    <td className="px-2 py-2 align-top text-right">
                      <button
                        type="button"
                        onClick={() => onRemoveLine(i)}
                        style={{
                          background: "transparent",
                          border: 0,
                          cursor: "pointer",
                          color: colors.danger || colors.error,
                        }}
                        aria-label="Remove line"
                        data-testid={`${testidPrefix}-del-${i}`}
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3} className="px-2 py-1"></td>
                <td
                  className="px-2 py-1 text-right text-sm font-bold"
                  style={{ color: colors.onSurface }}
                  data-testid={`${testidPrefix}-subtotal`}
                >
                  {`Subtotal $${subtotal.toFixed(2)}`}
                </td>
                <td></td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </>
  );
}
