/**
 * CategoryPicker · Feb-2026
 *
 * Compact dropdown for choosing an income OR service category.
 * Renders the category color swatch inline. When ``required`` is
 * set + no value, shows a red border and inline "Category required"
 * hint on focusout.
 *
 * Feb-2026 · UncategorizedItemsReport scope-addendum — accepts a
 * ``source`` prop selecting which taxonomy to fetch:
 *   * ``"income"``  (default, backwards-compat) — ``/income-categories``
 *   * ``"service"`` — ``/service-categories``
 * Both feed a per-source module-level cache so N pickers on one
 * page share exactly one HTTP round-trip.
 *
 * Feb-2026 · Invoice inline edit sprint — additions:
 *   * "+ Add category" option at the bottom of the dropdown opens an
 *     inline "create category" modal wired to
 *     POST /api/income-categories/resolve-or-create. Newly-created
 *     rows are appended to the module cache and auto-selected.
 *   * ``invalidReason`` prop (e.g. "archived_category") surfaces an
 *     inline warning chip + red border so the caller can force the
 *     operator to pick a new category before saving.
 *   * ``autoFocus`` prop opens the dropdown on mount — used by the
 *     save-error handler to focus the offending row.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, AlertCircle, Plus } from "lucide-react";
import { colors } from "@/theme";
import { api } from "@/api";

/** Per-source cache so N pickers don't each fire the same GET on mount. */
const _cachedPromises = { income: null, service: null };
const _cachedItems = { income: [], service: [] };

function loadCategories(source = "income") {
  if (!_cachedPromises[source]) {
    const url = source === "service"
      ? "/service-categories"
      : "/income-categories";
    _cachedPromises[source] = api.get(url)
      .then((r) => {
        _cachedItems[source] = (r?.items || []).slice();
        return _cachedItems[source];
      })
      .catch(() => []);
  }
  return _cachedPromises[source];
}
export function invalidateCategoryCache(source) {
  if (source == null) {
    _cachedPromises.income = null;
    _cachedPromises.service = null;
    _cachedItems.income = [];
    _cachedItems.service = [];
  } else {
    _cachedPromises[source] = null;
    _cachedItems[source] = [];
  }
}

/** Push a newly-created category into every mounted picker's cache. */
function _cachePush(source, cat) {
  if (!cat) return;
  _cachedItems[source] = _cachedItems[source] || [];
  if (!_cachedItems[source].find((c) => c.id === cat.id)) {
    _cachedItems[source] = [..._cachedItems[source], cat];
    _cachedPromises[source] = Promise.resolve(_cachedItems[source]);
  }
}

export default function CategoryPicker({
  value, onChange, required = false, disabled = false,
  testid = "category-picker", placeholder = "Choose category",
  size = "sm", source = "income",
  invalidReason = null, autoFocus = false,
}) {
  const [cats, setCats] = useState(_cachedItems[source] || []);
  const [open, setOpen] = useState(false);
  const [touched, setTouched] = useState(false);
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");
  const buttonRef = useRef(null);

  useEffect(() => { loadCategories(source).then(setCats); }, [source]);

  useEffect(() => {
    if (autoFocus && buttonRef.current) {
      buttonRef.current.focus();
      setOpen(true);
    }
  }, [autoFocus]);

  const active = useMemo(() => cats.filter((c) => !c.is_archived), [cats]);
  const chosen = useMemo(
    () => cats.find((c) => c.id === value || c.name === value),
    [cats, value],
  );
  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return active;
    return active.filter((c) => (c.name || "").toLowerCase().includes(q));
  }, [active, filter]);

  // Feb-2026 · Invoice inline edit sprint — three ways this picker
  // can flag an issue: caller-supplied invalidReason (from the
  // structured server error), required-but-empty (post-blur), or
  // value-that-doesn't-map (archived category surfaced by the
  // invoice's stored value not matching any active row).
  const orphanValue = value && !chosen;
  const showArchivedWarning = invalidReason === "archived_category"
    || (orphanValue && required);
  const showError = required && touched && !chosen;
  let borderColor = colors.border;
  if (showArchivedWarning) borderColor = "#DC2626";
  else if (showError) borderColor = "#DC2626";
  else if (required && !chosen) borderColor = "#FDE68A";

  const pick = (c) => {
    onChange?.(c.id);
    setOpen(false);
    setFilter("");
  };

  const openCreate = () => {
    setCreating(true);
    setCreateName(filter.trim());
    setCreateError("");
  };

  const submitCreate = async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    const name = (createName || "").trim();
    if (!name) {
      setCreateError("Name is required");
      return;
    }
    setCreateBusy(true);
    setCreateError("");
    try {
      // Only income categories support resolve-or-create; keep the
      // service surface as a plain create + refresh below.
      let created;
      if (source === "income") {
        const res = await api.post("/income-categories/resolve-or-create",
                                     { name });
        created = res?.category || res;
      } else {
        created = await api.post("/service-categories", { name });
      }
      if (created && created.id) {
        _cachePush(source, created);
        setCats((prev) => (prev.find((c) => c.id === created.id)
                             ? prev : [...prev, created]));
        onChange?.(created.id);
      }
      setCreating(false);
      setCreateName("");
      setOpen(false);
      setFilter("");
    } catch (err) {
      setCreateError(err?.message || "Failed to create category");
    } finally {
      setCreateBusy(false);
    }
  };

  const padY = size === "sm" ? "py-1" : "py-1.5";

  return (
    <div className="relative" data-testid={testid}
          onBlur={() => setTouched(true)}>
      <button
        ref={buttonRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={`w-full flex items-center gap-2 px-2 ${padY} rounded text-sm text-left`}
        style={{ background: colors.surface,
                  border: `1px solid ${borderColor}`,
                  color: chosen ? colors.onSurface : colors.muted }}
        data-testid={`${testid}-button`}
        data-invalid-reason={invalidReason || undefined}
      >
        {chosen ? (
          <span className="w-3 h-3 rounded-sm shrink-0"
                style={{ background: chosen.color || "#94A3B8" }} />
        ) : null}
        <span className="flex-1 truncate">
          {chosen ? chosen.name : (orphanValue ? `${value} (archived)` : placeholder)}
        </span>
        <ChevronDown size={12} />
      </button>
      {showArchivedWarning ? (
        <div
          className="flex items-center gap-1 mt-1 text-xs"
          style={{ color: "#DC2626" }}
          data-testid={`${testid}-archived-warning`}
        >
          <AlertCircle size={11} />
          Category{value ? ` '${value}'` : ""} is archived — pick a new category or create one.
        </div>
      ) : showError ? (
        <div className="flex items-center gap-1 mt-1 text-xs"
              style={{ color: "#DC2626" }}
              data-testid={`${testid}-error`}>
          <AlertCircle size={11} /> Category required
        </div>
      ) : null}
      {open && !disabled ? (
        <div
          className="absolute z-20 mt-1 w-full rounded-xl overflow-hidden"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}`,
                    boxShadow: "0 6px 16px rgba(0,0,0,0.10)" }}
          data-testid={`${testid}-popover`}
        >
          {creating ? (
            <form onSubmit={submitCreate} className="p-2">
              <div className="text-[10px] uppercase tracking-wider mb-1"
                    style={{ color: colors.muted }}>
                New category
              </div>
              <input
                type="text"
                autoFocus
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                placeholder="Category name"
                className="w-full px-2 py-1.5 text-sm rounded outline-none"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid={`${testid}-new-name`}
              />
              {createError ? (
                <div className="text-xs mt-1" style={{ color: "#DC2626" }}
                      data-testid={`${testid}-new-error`}>
                  {createError}
                </div>
              ) : null}
              <div className="flex justify-end gap-2 mt-2">
                <button type="button"
                        onClick={() => { setCreating(false); setCreateError(""); }}
                        className="text-xs px-2 py-1 rounded"
                        style={{ color: colors.muted }}
                        data-testid={`${testid}-new-cancel`}>
                  Cancel
                </button>
                <button type="submit"
                        disabled={createBusy}
                        className="text-xs font-semibold px-2 py-1 rounded text-white"
                        style={{ background: colors.brand,
                                  opacity: createBusy ? 0.6 : 1 }}
                        data-testid={`${testid}-new-submit`}>
                  {createBusy ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          ) : (
            <>
              <input
                type="text"
                placeholder="Search…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="w-full px-2 py-1.5 text-sm outline-none"
                style={{ borderBottom: `1px solid ${colors.border}`,
                          background: colors.surface }}
                autoFocus
                data-testid={`${testid}-search`}
              />
              <div className="max-h-56 overflow-y-auto">
                {filtered.length === 0 ? (
                  <div className="px-3 py-2 text-xs"
                        style={{ color: colors.muted }}>
                    No categories.
                  </div>
                ) : filtered.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => pick(c)}
                    className="w-full flex items-center gap-2 px-2 py-1.5 text-sm text-left hover:brightness-95"
                    style={{ background: colors.surface, color: colors.onSurface }}
                    data-testid={`${testid}-option-${c.id}`}
                  >
                    <span className="w-3 h-3 rounded-sm shrink-0"
                          style={{ background: c.color || "#94A3B8" }} />
                    <span className="truncate">{c.name}</span>
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={openCreate}
                className="w-full flex items-center gap-2 px-2 py-2 text-sm border-t hover:brightness-95"
                style={{ background: colors.surfaceSecondary,
                          borderColor: colors.border,
                          color: colors.brand }}
                data-testid={`${testid}-add-new`}
              >
                <Plus size={14} />
                <span>Add category{filter.trim() ? ` "${filter.trim()}"` : ""}</span>
              </button>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
