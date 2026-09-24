/**
 * Feb-2026 · Inline category combobox cell.
 *
 * Click-to-edit combobox for taxonomy columns (`income_category`,
 * `service_category`) on any row-oriented table that stores an
 * item's category-id as ``{axis}_category_id``. Originally shipped
 * for Recurring Jobs (Feb-2026); parameterized in Task C
 * (Feb-2026) so the Pricebook rows in ``OpsHub.jsx`` can consume
 * the same component without an intermediate wrapper.
 *
 * Flow on save:
 *   1. `POST /api/{axis}-categories/resolve-or-create` returns a
 *      canonical ``id`` for the typed value (creates a new master
 *      row on first use).
 *   2. `PATCH ${patchUrl}` with
 *      ``{ [axis + "_category_id"]: id }``. Row updates optimistically.
 *
 * Keys:
 *   ENTER / blur → save (400ms debounced against typeahead noise)
 *   ESC          → cancel, revert to prior display value
 */
import React from "react";
import { toast } from "sonner";
import { api } from "@/api";


const _AXIS_TO_URL = {
  income: "/income-categories",
  service: "/service-categories",
};


/**
 * @param {Object} props
 * @param {"income"|"service"} props.axis
 * @param {Object} props.row  Table row (must carry ``id``). Some
 *   callers use the row for the ``patchUrl`` builder; others only
 *   need the id for the testid default.
 * @param {string} [props.value]  Current denorm name on the row.
 *   For rows without a denorm (e.g. Pricebook items), callers
 *   resolve the name from the master category list and pass it in.
 * @param {string | ((row: object) => string)} props.patchUrl
 *   Required. String URL (e.g. ``/items/${row.id}``) or builder
 *   function (row) → string. Task C · Feb-2026 — no default. Prior
 *   to Task C the URL was hardcoded to ``/recurring-jobs/${row.id}``;
 *   callers now pass it explicitly so ``CategoryComboCell`` stays a
 *   pure parameterized component.
 * @param {(patch: object) => void} props.onPatched  Called with
 *   ``{ [axis + "_category_id"]: id, [axis + "_category_name"]: name }``
 *   so the parent can update the table row (or, for callers that
 *   prefer a whole-list refetch, ignore the payload and call their
 *   own ``refresh()``).
 * @param {string} [props.dataTestidBase]  Overrides the default
 *   ``recurring-cat-${axis}-${row.id}`` prefix. Task C uses
 *   ``pb-cat-${axis}-${row.id}`` on the Pricebook rows.
 */
export default function CategoryComboCell({
  axis, row, value, patchUrl, onPatched, dataTestidBase,
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(value || "");
  const [busy, setBusy] = React.useState(false);
  const [options, setOptions] = React.useState([]);
  const [showList, setShowList] = React.useState(false);
  const inputRef = React.useRef(null);
  const wrapRef = React.useRef(null);
  const testidBase = dataTestidBase || `recurring-cat-${axis}-${row?.id || "x"}`;

  React.useEffect(() => { setDraft(value || ""); }, [value]);

  // Fetch the master list once on first entry into edit mode. Cheap
  // — the two category collections are tenant-scoped and small.
  const loadOptions = React.useCallback(async () => {
    try {
      const r = await api.get(`${_AXIS_TO_URL[axis]}?include_archived=false`);
      setOptions(Array.isArray(r?.items) ? r.items : []);
    } catch (_err) {
      setOptions([]);
    }
  }, [axis]);

  const enterEdit = () => {
    setEditing(true);
    setShowList(true);
    loadOptions();
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const cancel = () => {
    setDraft(value || "");
    setEditing(false);
    setShowList(false);
  };

  const save = async () => {
    const trimmed = (draft || "").trim();
    if (trimmed === (value || "").trim()) {
      cancel();
      return;
    }
    if (trimmed.length > 80) {
      toast.error("Category name must be 80 characters or fewer");
      return;
    }
    setBusy(true);
    try {
      let categoryId = null;
      let categoryName = null;
      if (trimmed) {
        const created = await api.post(
          `${_AXIS_TO_URL[axis]}/resolve-or-create`,
          { name: trimmed },
        );
        const cat = created?.category || null;
        if (!cat?.id) throw new Error("resolve-or-create returned no id");
        categoryId = cat.id;
        categoryName = cat.name;
      }
      const patchKey = `${axis}_category_id`;
      // Task C · Feb-2026 — resolve the caller-provided patchUrl.
      // String (e.g. ``/items/${row.id}``) OR builder (row) => string.
      // No default: callers MUST supply it. Guarded so a missing
      // prop fails loud in dev rather than silently no-op'ing.
      const resolvedUrl = typeof patchUrl === "function"
        ? patchUrl(row)
        : patchUrl;
      if (typeof resolvedUrl !== "string" || !resolvedUrl) {
        throw new Error("CategoryComboCell: patchUrl prop is required");
      }
      await api.patch(resolvedUrl, { [patchKey]: categoryId || "" });
      onPatched && onPatched({
        [patchKey]: categoryId,
        [`${axis}_category_name`]: categoryName,
      });
    } catch (err) {
      toast.error(err?.message || "Save failed");
      setDraft(value || "");
    } finally {
      setBusy(false);
      setEditing(false);
      setShowList(false);
    }
  };

  const filtered = React.useMemo(() => {
    const q = (draft || "").trim().toLowerCase();
    if (!q) return options.slice(0, 12);
    return options
      .filter((c) => (c.name || "").toLowerCase().includes(q))
      .slice(0, 12);
  }, [options, draft]);

  // Debounced blur so rapid tab-through doesn't fire mid-typing.
  const blurTimer = React.useRef(null);
  const onBlur = () => {
    if (blurTimer.current) clearTimeout(blurTimer.current);
    blurTimer.current = setTimeout(() => save(), 400);
  };
  const cancelBlurTimer = () => {
    if (blurTimer.current) { clearTimeout(blurTimer.current); blurTimer.current = null; }
  };

  if (!editing) {
    return (
      <button
        type="button"
        onClick={enterEdit}
        className="w-full text-left px-2 py-1 rounded hover:bg-slate-100 text-xs"
        style={{ color: value ? "#0F172A" : "#94A3B8" }}
        data-testid={`${testidBase}-display`}
      >
        {value || <em>— set —</em>}
      </button>
    );
  }

  return (
    <div ref={wrapRef} className="relative"
          data-testid={`${testidBase}-editor`}>
      <input
        ref={inputRef}
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onFocus={cancelBlurTimer}
        onBlur={onBlur}
        onKeyDown={(e) => {
          if (e.key === "Enter") { cancelBlurTimer(); save(); }
          if (e.key === "Escape") { cancelBlurTimer(); cancel(); }
        }}
        disabled={busy}
        className="w-full px-2 py-1 rounded border text-xs"
        style={{ borderColor: "#CBD5E1" }}
        placeholder="Type or pick…"
        maxLength={80}
        data-testid={`${testidBase}-input`}
      />
      {showList && filtered.length > 0 ? (
        <ul
          className="absolute z-10 mt-1 w-56 max-h-48 overflow-y-auto rounded border bg-white shadow"
          style={{ borderColor: "#CBD5E1" }}
          data-testid={`${testidBase}-suggestions`}
          onMouseDown={cancelBlurTimer}
        >
          {filtered.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => { setDraft(c.name || ""); }}
                className="w-full text-left px-2 py-1 text-xs hover:bg-slate-100"
                data-testid={`${testidBase}-suggestion-${c.id}`}
              >
                {c.name}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
