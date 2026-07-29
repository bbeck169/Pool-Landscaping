/**
 * CategoryPicker · Feb-2026
 *
 * Compact dropdown for choosing an income category. Renders the
 * category color swatch inline. When ``required`` is set + no value,
 * shows a red border and inline "Category required" hint on focusout.
 */
import React, { useEffect, useMemo, useState } from "react";
import { ChevronDown, AlertCircle } from "lucide-react";
import { colors } from "@/theme";
import { api } from "@/api";

/** Module-level cache so N line-item pickers don't each fire the same
 *  /income-categories GET on mount. */
let _cachedPromise = null;
function loadCategories() {
  if (!_cachedPromise) {
    _cachedPromise = api.get("/income-categories")
      .then((r) => (r?.items || []))
      .catch(() => []);
  }
  return _cachedPromise;
}
export function invalidateCategoryCache() { _cachedPromise = null; }

export default function CategoryPicker({
  value, onChange, required = false, disabled = false,
  testid = "category-picker", placeholder = "Choose category",
  size = "sm",
}) {
  const [cats, setCats] = useState([]);
  const [open, setOpen] = useState(false);
  const [touched, setTouched] = useState(false);
  const [filter, setFilter] = useState("");

  useEffect(() => { loadCategories().then(setCats); }, []);

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

  const showError = required && touched && !chosen;
  const borderColor = showError ? "#DC2626"
    : (required && !chosen ? "#FDE68A" : colors.border);

  const pick = (c) => {
    onChange?.(c.id);
    setOpen(false);
    setFilter("");
  };

  const padY = size === "sm" ? "py-1" : "py-1.5";

  return (
    <div className="relative" data-testid={testid}
          onBlur={() => setTouched(true)}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={`w-full flex items-center gap-2 px-2 ${padY} rounded text-sm text-left`}
        style={{ background: colors.surface,
                  border: `1px solid ${borderColor}`,
                  color: chosen ? colors.onSurface : colors.muted }}
        data-testid={`${testid}-button`}
      >
        {chosen ? (
          <span className="w-3 h-3 rounded-sm shrink-0"
                style={{ background: chosen.color || "#94A3B8" }} />
        ) : null}
        <span className="flex-1 truncate">
          {chosen ? chosen.name : placeholder}
        </span>
        <ChevronDown size={12} />
      </button>
      {showError ? (
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
        </div>
      ) : null}
    </div>
  );
}
