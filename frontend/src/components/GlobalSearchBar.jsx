/**
 * Feb-2026 · Visible universal search bar (white pill in navy hero).
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
 * Styling — white pill on the ``#1B1F5C`` hero strip
 * ──────────────────────────────────────────────────
 *   * ``AppLayout`` renders this bar inside a full-width navy strip
 *     (``data-testid="admin-hero-banner"``, bg ``#1B1F5C``).
 *   * The pill itself is solid white, fully rounded
 *     (``border-radius: 9999px``), with a thin slate border for
 *     definition on the navy backdrop.
 *   * Left: search icon (gray-700). Right: ``⌘K`` / ``Ctrl+K``
 *     keyboard hint, hidden on ``<sm`` to save real estate.
 *   * Dark text + muted placeholder so WCAG AA contrast reads clean
 *     on white.
 */
import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { Search, X } from "lucide-react";
import { colors } from "@/theme";
import { useGlobalSearchResults } from "@/hooks/useGlobalSearchResults";


// White-pill surface tokens — pill reads as a clean affordance
// floating inside the navy ``#1B1F5C`` hero strip rendered by
// ``AppLayout``. Dark text + muted placeholder for WCAG AA
// contrast on white.
const HERO_BG          = "#FFFFFF";
const HERO_BG_HOVER    = "#F8FAFC";   // slate-50 — subtle hover shift
const HERO_FG          = "#111827";   // gray-900 — primary text
const HERO_PLACEHOLDER = "#6B7280";   // gray-500 — placeholder
const HERO_FOCUS_RING  = "#94A3B8";   // slate-400 — focus ring on white
const HERO_BORDER      = "#CBD5E1";   // slate-300 — pill border on navy
const HERO_ICON        = "#374151";   // gray-700 — left search icon
const KBD_FG           = "#64748B";   // slate-500 — kbd hint text
const KBD_BG           = "#F1F5F9";   // slate-100 — kbd hint tile bg
const KBD_BORDER       = "#CBD5E1";   // slate-300 — kbd hint tile border


// OS-aware keyboard hint — mirrors the ``_detectMac`` convention
// used by ``<GlobalSearch>`` (the ⌘K palette) so the hint reads
// identical semantics on both entry points.
function _detectMac() {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || navigator.platform || "";
  return /Mac|iPhone|iPad|iPod/i.test(ua);
}


// Route mapping for the five backend entities + pages.  Kept as a
// single map so the commit handler is a one-liner switch.
// TD-search-technicians-bucket · Feb-2026 — adds ``technician`` row
// routing. NOTE: the web route is SINGULAR ``/technician/:id``
// (``App.js:1510``), not plural; mobile has no equivalent route yet.
const ROUTE_FOR_KIND = {
  page:       (rec) => rec?.path || null,
  customer:   (rec) => (rec?.id ? `/customers/${rec.id}` : null),
  job:        (rec) => (rec?.id ? `/jobs/${rec.id}` : null),
  invoice:    (rec) => (rec?.id ? `/invoices/${rec.id}` : null),
  quote:      (rec) => (rec?.id ? `/quotes/${rec.id}` : null),
  lead:       (rec) => (rec?.id ? `/leads/${rec.id}` : null),
  technician: (rec) => (rec?.id ? `/technician/${rec.id}` : null),
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

  // OS-aware keyboard hint — resolves once on mount; rendered inside
  // the pill on ``sm+`` viewports.
  const isMac = useMemo(() => _detectMac(), []);
  const kbdHint = isMac ? "\u2318K" : "Ctrl+K";

  const {
    pages, customers, jobs, invoices, quotes, leads, technicians, loading,
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
    technicians.forEach((rec) => rows.push({ kind: "technician", rec }));
    return rows;
  }, [pages, customers, jobs, invoices, quotes, leads, technicians]);

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
  const pagesStart = running;        running += pages.length;
  const customersStart = running;    running += customers.length;
  const jobsStart = running;         running += jobs.length;
  const invoicesStart = running;     running += invoices.length;
  const quotesStart = running;       running += quotes.length;
  const leadsStart = running;        running += leads.length;
  const techniciansStart = running;  running += technicians.length;

  return (
    <div
      ref={rootRef}
      className="relative flex-1 max-w-xl mx-auto"
      data-testid="global-search-bar-root"
    >
      {/* Mobile compact button — visible below ``sm``.  Tap toggles
          the expanded input state so narrow viewports get an
          icon-first surface without stealing the whole nav row.
          White pill variant: matches the sm+ hero so the two
          responsive branches read as the same affordance. */}
      <button
        type="button"
        onClick={() => {
          setMobileExpanded((m) => !m);
          // Yield a tick so the input can mount before focus fires.
          setTimeout(() => inputRef.current?.focus(), 0);
        }}
        className="sm:hidden inline-flex items-center justify-center h-9 w-9 rounded-full shadow-sm hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
        style={{
          backgroundColor: HERO_BG,
          color: HERO_ICON,
          border: `1px solid ${HERO_BORDER}`,
        }}
        aria-label="Open search"
        aria-expanded={mobileExpanded}
        data-testid="global-search-bar-mobile-toggle"
      >
        <Search size={16} color={colors.searchIcon} aria-hidden="true" />
      </button>

      {/* Input strip — always visible on ``sm`` and up; on narrow
          viewports it renders only when ``mobileExpanded`` is on.
          White pill, fully rounded (``rounded-full``), thin slate
          border for definition on the ``#1B1F5C`` navy strip. */}
      <div
        className={[
          "items-center gap-2 rounded-full shadow-sm transition",
          "focus-within:shadow-md focus-within:ring-2",
          mobileExpanded ? "flex" : "hidden sm:flex",
        ].join(" ")}
        style={{
          backgroundColor: HERO_BG,
          color: HERO_FG,
          border: `1px solid ${HERO_BORDER}`,
          // Inline var so ``focus-within:ring-2`` picks up a slate
          // ring instead of shadcn's default.
          "--tw-ring-color": HERO_FOCUS_RING,
          padding: "6px 14px",
          height: 44,
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.backgroundColor = HERO_BG_HOVER;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = HERO_BG;
        }}
        data-testid="global-search-bar-hero"
      >
        <Search size={18} color={colors.searchIcon} aria-hidden="true" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => { if (query.trim()) setOpen(true); }}
          onKeyDown={onKeyDown}
          placeholder="Search customers, jobs, invoices, quotes, leads, technicians…"
          aria-label="Universal search"
          className="flex-1 min-w-0 bg-transparent outline-none text-sm font-medium"
          style={{ color: HERO_FG, caretColor: HERO_FG }}
          data-testid="global-search-bar-input"
        />
        {query ? (
          <button
            type="button"
            onClick={() => { setQuery(""); setOpen(false); }}
            aria-label="Clear search"
            className="inline-flex items-center justify-center h-6 w-6 rounded-full hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
            data-testid="global-search-bar-clear"
          >
            <X size={14} color={HERO_ICON} />
          </button>
        ) : null}
        {/* OS-aware keyboard hint — hidden on ``<sm`` to save the
            room taken by the compact mobile input. Mirrors the
            ``<GlobalSearch>`` palette's ``kbdHint`` so both entry
            points teach the same shortcut. */}
        <span
          className="hidden sm:inline-flex items-center h-6 px-2 rounded-md text-[11px] font-semibold tracking-wide select-none"
          style={{
            color: KBD_FG,
            backgroundColor: KBD_BG,
            border: `1px solid ${KBD_BORDER}`,
          }}
          aria-hidden="true"
          data-testid="global-search-bar-kbd-hint"
        >
          {kbdHint}
        </span>
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
          <Section
            label="Technicians" kind="technician" rows={technicians}
            start={techniciansStart}
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
