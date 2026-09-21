/**
 * Phase 9B · Feb 2026 — MergeTagPalette.
 *
 * shadcn Dialog + Command palette pattern. Fetches
 * ``GET /api/marketing/merge-tags`` once per session (cached in
 * module scope). Renders categories collapsibly, filters by search,
 * arrow-key nav + Enter to insert.
 *
 * ``onInsert("{{TOKEN}}")`` fires with the current row's token wrapped
 * in double-braces so caller can splice at the cursor.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Search, ChevronDown, ChevronRight, HelpCircle } from "lucide-react";
import { api } from "@/api";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";

// Session-cached catalog — hits /api/marketing/merge-tags at most
// once per page load. Keyed by nothing (single tenant per SPA session).
let _catalogCache = null;
let _catalogPromise = null;

async function loadCatalog() {
  if (_catalogCache) return _catalogCache;
  if (_catalogPromise) return _catalogPromise;
  _catalogPromise = api.get("/marketing/merge-tags").then((res) => {
    _catalogCache = res.categories || {};
    _catalogPromise = null;
    return _catalogCache;
  }).catch((e) => {
    _catalogPromise = null;
    throw e;
  });
  return _catalogPromise;
}

export function MergeTagPalette({ open, onOpenChange, onInsert }) {
  const [catalog, setCatalog] = useState(_catalogCache || {});
  const [loading, setLoading] = useState(!_catalogCache);
  const [q, setQ] = useState("");
  const [collapsed, setCollapsed] = useState({}); // {catName: true}
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setActiveIdx(0);
    if (_catalogCache) {
      setCatalog(_catalogCache);
      setLoading(false);
      return;
    }
    setLoading(true);
    loadCatalog()
      .then((c) => { setCatalog(c); })
      .finally(() => setLoading(false));
    // focus the search input after the dialog animates in
    const t = setTimeout(() => inputRef.current?.focus(), 60);
    return () => clearTimeout(t);
  }, [open]);

  // Flatten filtered rows for keyboard nav; keep category headers as
  // visual grouping only.
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const out = [];
    for (const [cat, tags] of Object.entries(catalog)) {
      const matching = tags.filter((t) => {
        if (!needle) return true;
        const hay = (t.token + " " + (t.label || "") + " " + (t.description || "")).toLowerCase();
        return hay.includes(needle);
      });
      if (matching.length) out.push({ category: cat, tags: matching });
    }
    return out;
  }, [catalog, q]);

  const flatOrder = useMemo(() => {
    const arr = [];
    filtered.forEach((grp) => {
      if (!collapsed[grp.category]) grp.tags.forEach((t) => arr.push(t));
    });
    return arr;
  }, [filtered, collapsed]);

  useEffect(() => {
    // Clamp active index when filter shrinks.
    if (activeIdx >= flatOrder.length) setActiveIdx(0);
  }, [flatOrder.length, activeIdx]);

  const insert = useCallback((token) => {
    if (typeof onInsert === "function") onInsert(`{{${token}}}`);
    onOpenChange(false);
  }, [onInsert, onOpenChange]);

  function onKeyDown(e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, Math.max(0, flatOrder.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter" && flatOrder[activeIdx]) {
      e.preventDefault();
      insert(flatOrder[activeIdx].token);
    }
  }

  const activeToken = flatOrder[activeIdx]?.token;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-2xl p-0 overflow-hidden"
        data-testid="merge-tag-palette-dialog"
        onKeyDown={onKeyDown}
      >
        <DialogHeader className="px-5 pt-5 pb-3">
          <DialogTitle>Insert merge tag</DialogTitle>
          <DialogDescription>
            Tags substitute at send time. Case-insensitive; safe on unknown tokens.
          </DialogDescription>
        </DialogHeader>
        <div className="px-5">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#0284C7]" />
            <input
              ref={inputRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search tags — try 'customer', 'invoice'…"
              data-testid="merge-tag-palette-search"
              className="w-full pl-9 pr-3 py-2 rounded-lg border border-zinc-200 text-sm placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-300"
            />
          </div>
        </div>
        <div className="mt-3 max-h-[420px] overflow-y-auto px-2 pb-4">
          {loading && (
            <div className="py-8 text-center text-sm text-zinc-500">
              Loading tag catalog…
            </div>
          )}
          {!loading && filtered.length === 0 && (
            <div className="py-8 text-center text-sm text-zinc-400"
                 data-testid="merge-tag-palette-empty">
              No tags match "{q}".
            </div>
          )}
          {!loading && filtered.map((grp) => {
            const isCollapsed = !!collapsed[grp.category];
            return (
              <div key={grp.category} className="mb-1">
                <button
                  onClick={() => setCollapsed((c) => ({ ...c, [grp.category]: !c[grp.category] }))}
                  className="w-full flex items-center gap-1 px-3 py-1.5 text-xs uppercase tracking-wide text-zinc-500 hover:bg-zinc-50 rounded"
                  data-testid={`merge-tag-category-header-${grp.category}`}
                >
                  {isCollapsed ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                  {grp.category}
                  <span className="ml-auto text-zinc-400 normal-case">{grp.tags.length}</span>
                </button>
                {!isCollapsed && grp.tags.map((t) => (
                  <button
                    key={t.token}
                    onClick={() => insert(t.token)}
                    onMouseEnter={() => {
                      const idx = flatOrder.findIndex((f) => f.token === t.token);
                      if (idx >= 0) setActiveIdx(idx);
                    }}
                    data-testid={`merge-tag-row-${t.token}`}
                    className={`w-full flex items-center gap-2 px-3 py-2 rounded text-left transition ${
                      activeToken === t.token
                        ? "bg-zinc-100"
                        : "hover:bg-zinc-50"
                    }`}
                  >
                    <span className="font-mono text-xs text-zinc-900">
                      {"{{"}{t.token}{"}}"}
                    </span>
                    <span className="text-sm text-zinc-500 truncate">
                      {t.label}
                    </span>
                    {t.description && (
                      <span
                        className="ml-auto text-zinc-300 hover:text-zinc-500"
                        title={t.description}
                      >
                        <HelpCircle className="w-3.5 h-3.5" />
                      </span>
                    )}
                  </button>
                ))}
              </div>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Testing helpers — the cache is process-wide so RTL specs need a way
// to reset it between tests.
export function __resetMergeTagCacheForTests() {
  _catalogCache = null;
  _catalogPromise = null;
}
