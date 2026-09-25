/**
 * Feb 2026 · Dashboard global-search bar.
 *
 * Compact quick-find surface anchored at the top of the admin
 * dashboard. Fires ``GET /api/search`` on a 300 ms debounce and
 * renders a grouped panel below the input:
 *
 *   Customers · N
 *     - primary label       (secondary)
 *   Jobs · N
 *     ...
 *
 * Keyboard:
 *   ↑ ↓    move highlight across all flat rows
 *   Enter  navigate to the highlighted row
 *   Esc    close the panel
 *
 * Panel closes when:
 *   * a result is clicked
 *   * user clicks outside the search input container
 *   * Esc is pressed
 *   * the input is cleared
 *
 * NOT rendered on any page besides Dashboard.jsx per product spec.
 */
import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { Search, X } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";


const ENTITY_META = {
  customers: { label: "Customers", route: (id) => `/customers/${id}` },
  jobs:      { label: "Jobs",      route: (id) => `/jobs/${id}` },
  invoices:  { label: "Invoices",  route: (id) => `/invoices/${id}` },
  leads:     { label: "Leads",     route: (id) => `/leads/${id}` },
};
const ENTITY_ORDER = ["customers", "jobs", "invoices", "leads"];


export default function GlobalSearchBar() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [results, setResults] = useState(null);       // null = untouched
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const rootRef = useRef(null);
  const inputRef = useRef(null);

  // Debounce ~300ms
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);

  // Fetch on debounced-query change.
  useEffect(() => {
    if (!debounced) {
      setResults(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .get(`/search?q=${encodeURIComponent(debounced)}&limit=5`)
      .then((data) => {
        if (cancelled) return;
        setResults(data || {});
        setHighlight(0);
      })
      .catch(() => {
        if (cancelled) return;
        setResults({});
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [debounced]);

  // Flat row list for keyboard nav — [{entity, id, primary, secondary}]
  const flatRows = useMemo(() => {
    if (!results) return [];
    const rows = [];
    for (const e of ENTITY_ORDER) {
      const list = results[e] || [];
      for (const r of list) {
        rows.push({ entity: e, ...r });
      }
    }
    return rows;
  }, [results]);

  const totalCount = flatRows.length;

  // Close on outside click.
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (ev) => {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(ev.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const goto = useCallback((row) => {
    if (!row) return;
    const meta = ENTITY_META[row.entity];
    if (!meta) return;
    setOpen(false);
    setQuery("");
    setDebounced("");
    setResults(null);
    navigate(meta.route(row.id));
  }, [navigate]);

  const onKeyDown = (ev) => {
    if (ev.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!open || totalCount === 0) return;
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      setHighlight((h) => (h + 1) % totalCount);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      setHighlight((h) => (h - 1 + totalCount) % totalCount);
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      goto(flatRows[highlight]);
    }
  };

  const onClear = () => {
    setQuery("");
    setDebounced("");
    setResults(null);
    setOpen(false);
    if (inputRef.current) inputRef.current.focus();
  };

  const showPanel = open && !!debounced;
  // Rolling index while rendering groups so each row picks up the
  // correct highlight index without re-scanning ``flatRows``.
  let cursor = -1;

  return (
    <div
      ref={rootRef}
      className="relative mb-4"
      data-testid="dashboard-global-search-wrap"
    >
      <div
        className="flex items-center gap-2 rounded-xl px-3 py-2 transition-colors"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.inputBorder}`,
        }}
      >
        <Search size={16} color={colors.searchIcon} />
        <input
          ref={inputRef}
          type="text"
          value={query}
          placeholder="Search customers, jobs, invoices, leads..."
          onChange={(e) => {
            setQuery(e.target.value);
            if (e.target.value) setOpen(true);
            else setOpen(false);
          }}
          onFocus={() => { if (debounced) setOpen(true); }}
          onKeyDown={onKeyDown}
          className="flex-1 bg-transparent outline-none text-sm placeholder:text-[#1B1F5C]"
          style={{ color: colors.nav.bg }}
          data-testid="dashboard-global-search"
          aria-label="Search customers, jobs, invoices, leads"
        />
        {query ? (
          <button
            type="button"
            onClick={onClear}
            className="p-0.5 rounded-md hover:brightness-95"
            aria-label="Clear search"
            data-testid="dashboard-global-search-clear"
          >
            <X size={14} color={colors.muted} />
          </button>
        ) : null}
      </div>

      {showPanel ? (
        <div
          className="absolute left-0 right-0 mt-2 rounded-xl shadow-lg z-40 overflow-hidden"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
            maxHeight: 480,
            overflowY: "auto",
          }}
          data-testid="global-search-results"
          role="listbox"
        >
          {loading && !results ? (
            <div className="p-3 space-y-2" data-testid="global-search-loading">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="animate-pulse rounded-md h-8"
                  style={{ backgroundColor: colors.surfaceTertiary }}
                />
              ))}
            </div>
          ) : totalCount === 0 ? (
            <div
              className="p-4 text-sm"
              style={{ color: colors.muted }}
              data-testid="global-search-empty"
            >
              No matches for &ldquo;{debounced}&rdquo;
            </div>
          ) : (
            ENTITY_ORDER.map((entity) => {
              const list = (results && results[entity]) || [];
              if (list.length === 0) return null;
              const meta = ENTITY_META[entity];
              return (
                <div
                  key={entity}
                  data-testid={`global-search-group-${entity}`}
                >
                  <div
                    className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wide"
                    style={{
                      color: colors.muted,
                      backgroundColor: colors.surfaceTertiary,
                    }}
                  >
                    {meta.label} · {list.length}
                  </div>
                  {list.map((row) => {
                    cursor += 1;
                    const idx = cursor;
                    const isActive = idx === highlight;
                    return (
                      <button
                        key={`${entity}-${row.id}`}
                        type="button"
                        onClick={() => goto({ entity, ...row })}
                        onMouseEnter={() => setHighlight(idx)}
                        className="w-full text-left px-3 py-2 transition-colors"
                        style={{
                          backgroundColor: isActive
                            ? colors.brandTertiary
                            : "transparent",
                        }}
                        data-testid={`global-search-result-${entity}-${row.id}`}
                        role="option"
                        aria-selected={isActive}
                      >
                        <div
                          className="text-sm font-semibold truncate"
                          style={{ color: colors.onSurface }}
                        >
                          {row.primary}
                        </div>
                        {row.secondary ? (
                          <div
                            className="text-xs truncate"
                            style={{ color: colors.muted }}
                          >
                            {row.secondary}
                          </div>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              );
            })
          )}
        </div>
      ) : null}
    </div>
  );
}
