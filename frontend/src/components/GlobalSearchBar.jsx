/**
 * Feb-2026 · Visible universal search bar (blue hero).
 *
 * Primary quick-find entry point mounted app-wide from
 * ``AdminTopBar``.  Always visible — the ⌘K palette
 * (``<GlobalSearch>``) remains as the modal shortcut alongside it.
 *
 * Behaviour
 * ─────────
 *   * 300 ms debounce on ``useGlobalSearchResults(query)``.
 *   * Grouped inline dropdown: customers · jobs · invoices ·
 *     quotes · leads · pages (in that order).
 *   * ↑ ↓ move highlight across the flat row list.
 *   * Enter navigates to the highlighted row.
 *   * Esc clears query + closes the dropdown but keeps the input
 *     mounted.
 *   * Click outside dismisses the dropdown.
 *   * Mobile: below the ``sm`` (640 px) breakpoint the bar collapses
 *     to a compact icon-only button that expands on tap.
 *
 * Styling — blue hero
 * ───────────────────
 *   * Bold brand blue (``#0284C7``) surface, white text, rounded-xl,
 *     visible focus ring, hover shadow. Placeholder mirrors the
 *     ⌘K palette so keyboard users see identical semantics on
 *     both entry points.
 */
import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { Search, X } from "lucide-react";
import { colors } from "@/theme";
import { useGlobalSearchResults } from "@/hooks/useGlobalSearchResults";


// Blue-hero surface tokens — locked to the app brand blue so the
// bar reads as the same identity as every other blue affordance
// (``colors.searchIcon``, primary CTAs).
const HERO_BG = colors.brand;             // "#0284C7"
const HERO_BG_HOVER = "#0369A1";          // sky-700 for hover-shift
const HERO_FG = "#FFFFFF";
const HERO_PLACEHOLDER = "rgba(255,255,255,0.75)";
const HERO_FOCUS_RING = "rgba(255,255,255,0.85)";


// Route mapping for the five backend entities + pages.  Kept as a
// single map so the commit handler is a one-liner switch.
const ROUTE_FOR_KIND = {
  page:     (rec) => rec?.path || null,
  customer: (rec) => (rec?.id ? `/customers/${rec.id}` : null),
  job:      (rec) => (rec?.id ? `/jobs/${rec.id}` : null),
  invoice:  (rec) => (rec?.id ? `/invoices/${rec.id}` : null),
  quote:    (rec) => (rec?.id ? `/quotes/${rec.id}` : null),
  lead:     (rec) => (rec?.id ? `/leads/${rec.id}` : null),
};


export default function GlobalSearchBar() {
  const navigate = useNavigate();
  const rootRef = useRef(null);
  const inputRef = useRef(null);

  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  // Mobile expand state — the compact icon-only button toggles this
  // to reveal the full-width input on narrow viewports.
  const [mobileExpanded, setMobileExpanded] = useState(false);

  const {
    pages, customers, jobs, invoices, quotes, leads, loading,
  } = useGlobalSearchResults(query);

  // Flat row list drives keyboard navigation.  Order mirrors the
  // rendered sections so ArrowDown/Up feel intuitive.
  const flatRows = useMemo(() => {
    const rows = [];
    pages.forEach((rec) => rows.push({ kind: "page", rec }));
    customers.forEach((rec) => rows.push({ kind: "customer", rec }));
    jobs.forEach((rec) => rows.push({ kind: "job", rec }));
    invoices.forEach((rec) => rows.push({ kind: "invoice", rec }));
    quotes.forEach((rec) => rows.push({ kind: "quote", rec }));
    leads.forEach((rec) => rows.push({ kind: "lead", rec }));
    return rows;
  }, [pages, customers, jobs, invoices, quotes, leads]);

  // Reset highlight on query change so late-arriving backend hits
  // don't jump the cursor mid-typing.
  useEffect(() => { setHighlight(0); }, [query]);

  // Auto-open the dropdown as soon as the user starts typing.
  useEffect(() => {
    if (query.trim().length > 0) setOpen(true);
  }, [query]);

  // Click-outside dismiss (dropdown only — input stays mounted).
  useEffect(() => {
    if (!open) return undefined;
    const onDocMouseDown = (e) => {
      const root = rootRef.current;
      if (root && !root.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  const commit = useCallback((row) => {
    if (!row) return;
    const routeFn = ROUTE_FOR_KIND[row.kind];
    const target = routeFn ? routeFn(row.rec) : null;
    if (!target) return;
    setOpen(false);
    setMobileExpanded(false);
    navigate(target);
  }, [navigate]);

  const onKeyDown = (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      // Clear query + close dropdown but KEEP the input mounted so
      // the user's next keystroke lands in the same surface.
      setQuery("");
      setOpen(false);
      return;
    }
    if (!flatRows.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, flatRows.length - 1));
      setOpen(true);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
      setOpen(true);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const idx = Math.min(highlight, flatRows.length - 1);
      if (idx >= 0) commit(flatRows[idx]);
    }
  };

  const q = query.trim();
  const hasAnyResults = flatRows.length > 0;
  const showEmpty = q.length >= 2 && !hasAnyResults && !loading;

  // Section offsets for the flat highlight index.
  let running = 0;
  const pagesStart = running;      running += pages.length;
  const customersStart = running;  running += customers.length;
  const jobsStart = running;       running += jobs.length;
  const invoicesStart = running;   running += invoices.length;
  const quotesStart = running;     running += quotes.length;
  const leadsStart = running;      running += leads.length;

  return (
    <div
      ref={rootRef}
      className="relative flex-1 max-w-xl mx-auto"
      data-testid="global-search-bar-root"
    >
      {/* Mobile compact button — visible below ``sm``.  Tap toggles
          the expanded input state so narrow viewports get an
          icon-first surface without stealing the whole nav row. */}
      <button
        type="button"
        onClick={() => {
          setMobileExpanded((m) => !m);
          // Yield a tick so the input can mount before focus fires.
          setTimeout(() => inputRef.current?.focus(), 0);
        }}
        className="sm:hidden inline-flex items-center justify-center h-8 w-8 rounded-xl text-white shadow-sm hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
        style={{ backgroundColor: HERO_BG }}
        aria-label="Open search"
        aria-expanded={mobileExpanded}
        data-testid="global-search-bar-mobile-toggle"
      >
        <Search size={16} />
      </button>

      {/* Input strip — always visible on ``sm`` and up; on narrow
          viewports it renders only when ``mobileExpanded`` is on. */}
      <div
        className={[
          "items-center gap-2 rounded-xl shadow-sm transition",
          "focus-within:shadow-md focus-within:ring-2",
          mobileExpanded ? "flex" : "hidden sm:flex",
        ].join(" ")}
        style={{
          backgroundColor: HERO_BG,
          color: HERO_FG,
          // Inline vars so ``focus-within:ring-2`` picks up a white
          // ring instead of shadcn's default.
          "--tw-ring-color": HERO_FOCUS_RING,
          padding: "6px 10px",
          height: 40,
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.backgroundColor = HERO_BG_HOVER;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = HERO_BG;
        }}
        data-testid="global-search-bar-hero"
      >
        <Search size={18} color={HERO_FG} aria-hidden="true" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => { if (query.trim()) setOpen(true); }}
          onKeyDown={onKeyDown}
          placeholder="Search customers, jobs, invoices, quotes, leads…"
          aria-label="Universal search"
          className="flex-1 min-w-0 bg-transparent outline-none placeholder:opacity-80 text-sm font-medium"
          style={{ color: HERO_FG, "::placeholder": HERO_PLACEHOLDER }}
          data-testid="global-search-bar-input"
        />
        {query ? (
          <button
            type="button"
            onClick={() => { setQuery(""); setOpen(false); }}
            aria-label="Clear search"
            className="inline-flex items-center justify-center h-6 w-6 rounded-lg hover:bg-white/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
            data-testid="global-search-bar-clear"
          >
            <X size={14} color={HERO_FG} />
          </button>
        ) : null}
      </div>

      {/* Inline results dropdown.  Absolutely positioned below the
          hero surface so it never nudges the nav layout. */}
      {open && (hasAnyResults || showEmpty || loading) ? (
        <div
          role="listbox"
          className="absolute left-0 right-0 mt-1 rounded-xl border bg-white shadow-lg z-40 max-h-[70vh] overflow-y-auto"
          style={{ borderColor: colors.border }}
          data-testid="global-search-bar-dropdown"
        >
          {loading ? (
            <div
              className="px-3 py-2 text-xs italic"
              style={{ color: colors.muted }}
              data-testid="global-search-bar-loading"
            >
              Searching…
            </div>
          ) : null}

          <Section
            label="Pages" kind="page" rows={pages} start={pagesStart}
            highlight={highlight} setHighlight={setHighlight} commit={commit}
          />
          <Section
            label="Customers" kind="customer" rows={customers}
            start={customersStart}
            highlight={highlight} setHighlight={setHighlight} commit={commit}
          />
          <Section
            label="Jobs" kind="job" rows={jobs} start={jobsStart}
            highlight={highlight} setHighlight={setHighlight} commit={commit}
          />
          <Section
            label="Invoices" kind="invoice" rows={invoices}
            start={invoicesStart}
            highlight={highlight} setHighlight={setHighlight} commit={commit}
          />
          <Section
            label="Quotes" kind="quote" rows={quotes}
            start={quotesStart}
            highlight={highlight} setHighlight={setHighlight} commit={commit}
          />
          <Section
            label="Leads" kind="lead" rows={leads} start={leadsStart}
            highlight={highlight} setHighlight={setHighlight} commit={commit}
          />

          {showEmpty ? (
            <div
              className="px-3 py-3 text-sm"
              style={{ color: colors.muted }}
              data-testid="global-search-bar-empty"
            >
              No results for &ldquo;{q}&rdquo;
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}


// Inline section — bail cleanly on empty ``rows`` so the dropdown
// never renders a phantom section header for a group that missed.
function Section({ label, kind, rows, start, highlight, setHighlight, commit }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div
      role="group"
      className="py-1 border-t first:border-t-0"
      style={{ borderColor: colors.border }}
      data-testid={`global-search-bar-section-${kind}`}
    >
      <div
        className="flex items-center justify-between px-3 pt-1 pb-0.5 text-[10px] font-bold uppercase tracking-wide"
        style={{ color: colors.muted }}
      >
        <span>{label}</span>
        <span>{rows.length}</span>
      </div>
      <ul className="m-0 p-0 list-none">
        {rows.map((rec, idx) => {
          const flatIdx = start + idx;
          const active = flatIdx === highlight;
          const primary = kind === "page" ? rec.title : rec.primary;
          const secondary = kind === "page" ? rec.path : rec.secondary;
          return (
            <li
              key={`${kind}-${rec.id || rec.path}-${idx}`}
              role="option"
              aria-selected={active}
              onMouseDown={(e) => { e.preventDefault(); commit({ kind, rec }); }}
              onMouseEnter={() => setHighlight(flatIdx)}
              className="px-3 py-2 cursor-pointer flex flex-col text-sm"
              style={{
                backgroundColor: active ? "#EFF6FF" : "transparent",
                borderLeft: active
                  ? `3px solid ${colors.brand}`
                  : "3px solid transparent",
                color: colors.onSurface,
              }}
              data-testid={`global-search-bar-result-${flatIdx}`}
              data-kind={kind}
              data-active={active ? "true" : "false"}
            >
              <span className="font-medium">{primary}</span>
              {secondary ? (
                <span className="text-xs" style={{ color: colors.muted }}>
                  {secondary}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
