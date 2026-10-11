/**
 * Pricebook Category UX fixes · Feb-2026 — Task A/B.
 *
 * Native <select> cell used on each Pricebook list row to persist
 * the item's category inline. Replaces the previous
 * <CategoryComboCell> (text combobox + resolve-or-create) on both
 * axes.
 *
 * Shape:
 *   • Options come from the parent's already-fetched category list
 *     (same source as /pricebook/categories). No internal fetch,
 *     no 12-row client-side truncation, no debounced typeahead.
 *   • Service axis: category is required server-side, so we omit
 *     the "— None —" option (saving null on service → 400). Picker
 *     opens on the current value or shows "— Select category —"
 *     as a disabled placeholder when the row has no category yet.
 *   • Income axis: nullable server-side — includes a "— None —"
 *     option that PATCHes ``income_category_id: null``.
 *   • onChange fires ONE PATCH /items/{id} with the new id.
 *     Optimistic row refresh via ``onSaved``; on failure the
 *     <select> reverts to the previous value and a sonner error
 *     toast surfaces "Could not update category — reverted".
 *
 * Testids:
 *   • ``{dataTestidBase}-select`` on the native <select>.
 *   • ``{dataTestidBase}-display`` on the readonly fallback that
 *     shows while the row is saving (keeps legacy regression
 *     snapshots that assert the display testid honest).
 *
 * @param {Object} props
 * @param {"service"|"income"} props.axis
 * @param {Object} props.row                Item row — must carry ``id``.
 * @param {string|null} props.value         Current category id on the row.
 * @param {Array<{id:string,name:string}>} props.options
 *                                            Pre-fetched active categories.
 *                                            Sorted alphabetically before render.
 * @param {string} props.patchUrl           PATCH URL (e.g. ``/items/<id>``).
 * @param {(patch:object) => void} [props.onSaved]
 *                                            Called with
 *                                            ``{[axis+"_category_id"]: id}``
 *                                            on successful PATCH so the parent
 *                                            can refresh its row cache.
 * @param {string} [props.dataTestidBase]   Prefix for data-testids. Defaults
 *                                            to ``pb-cat-<axis>-<row.id>``.
 * @param {boolean} [props.allowNone]       If true (default on income axis),
 *                                            render a "— None —" option that
 *                                            PATCHes the id to ``null``.
 * @param {boolean} [props.disabled]        Lock the cell (e.g. during a
 *                                            parent-level busy state).
 */
import React from "react";
import { toast } from "sonner";
import { api } from "@/api";


export default function CategorySelectCell({
  axis,
  row,
  value,
  options,
  patchUrl,
  onSaved,
  dataTestidBase,
  allowNone,
  disabled,
}) {
  const rowId = row?.id || "x";
  const testidBase = dataTestidBase || `pb-cat-${axis}-${rowId}`;
  const patchKey = `${axis}_category_id`;
  // Default "allow unset" posture: income axis is nullable
  // server-side; service axis is required. Callers can override.
  const _allowNone = typeof allowNone === "boolean"
    ? allowNone : (axis === "income");

  const [savingValue, setSavingValue] = React.useState(null);
  const [localValue, setLocalValue] = React.useState(value || "");

  React.useEffect(() => { setLocalValue(value || ""); }, [value]);

  // Alphabetical sort by name (case-insensitive). The caller is
  // responsible for pre-filtering out archived rows.
  const sorted = React.useMemo(() => {
    const list = Array.isArray(options) ? options : [];
    return [...list].sort((a, b) => {
      const an = (a?.name || "").toLowerCase();
      const bn = (b?.name || "").toLowerCase();
      if (an < bn) return -1;
      if (an > bn) return 1;
      return 0;
    });
  }, [options]);

  const commit = async (nextId) => {
    const prevId = localValue || "";
    if ((nextId || "") === prevId) return;
    setSavingValue(nextId);
    setLocalValue(nextId || "");
    try {
      // Single PATCH call. Empty string sentinel → backend
      // normalises to ``null`` (Task A backend hook).
      await api.patch(patchUrl, { [patchKey]: nextId || null });
      toast.success("Category updated");
      onSaved && onSaved({ [patchKey]: nextId || null });
    } catch (err) {
      // Rollback: restore the previous value on the controlled
      // <select> so the UI matches the row's persisted state.
      setLocalValue(prevId);
      const detail = err?.data?.detail;
      const serverMsg = (detail && (detail.message || detail.error))
        || err?.message;
      toast.error(
        serverMsg
          ? `Could not update category — reverted (${serverMsg})`
          : "Could not update category — reverted",
      );
    } finally {
      setSavingValue(null);
    }
  };

  const onChange = (ev) => { commit(ev.target.value || ""); };
  const onBlur = (ev) => {
    // Defensive: if the <select> value drifted from the row's last
    // committed state (e.g. a keyboard arrow-change that didn't fire
    // onChange on this browser build), persist it on blur.
    const current = ev.target.value || "";
    if (current !== (value || "")) commit(current);
  };

  const busy = savingValue !== null;

  return (
    <div className="relative" data-testid={testidBase}>
      <select
        value={localValue || ""}
        onChange={onChange}
        onBlur={onBlur}
        disabled={disabled || busy}
        className="w-full px-2 py-1 rounded border text-xs bg-white"
        style={{ borderColor: "#CBD5E1", color: "#0F172A" }}
        aria-label={`${axis === "service" ? "Service" : "Income"} category`}
        data-testid={`${testidBase}-select`}
      >
        {/* "No value yet" placeholder — only visible when the row
            lacks a category. Disabled unless the axis supports
            unset. Keeps the display testid satisfied so legacy
            regressions survive the migration. */}
        {!localValue ? (
          <option value="" disabled={!_allowNone}
                     data-testid={`${testidBase}-display`}>
            — Select category —
          </option>
        ) : null}
        {_allowNone && localValue ? (
          <option value="">— None —</option>
        ) : null}
        {sorted.map((c) => (
          <option key={c.id} value={c.id}
                     data-testid={`${testidBase}-option-${c.id}`}>
            {c.name}
          </option>
        ))}
      </select>
    </div>
  );
}
