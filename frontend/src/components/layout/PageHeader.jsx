/**
 * Feb-2026 · N1 / N4' · Shared page-header component with grouped
 * global search.
 *
 * Contract
 * ────────
 *   <PageHeader
 *     title="Invoices"           // required — renders as <h1>
 *     actions={<Buttons/>}       // optional — right-aligned actions
 *     subtitle="Filed & Open"    // optional — small text under H1
 *   />
 *
 * Layout
 * ──────
 *   Row 1 · title left, actions right, inherits page background.
 *   Row 2 · slim blue command-bar band with a centered search
 *           input (max-width 640, ``margin: 0 auto``).
 *   Row 3 · absolute-positioned dropdown pane with THREE grouped
 *           sections (Pages · Customers · Documents), keyboard nav
 *           traverses ALL rows flat regardless of section.
 *
 * N4' additions (Feb-2026)
 * ────────────────────────
 * * Dropdown is grouped via ``useGlobalSearch(query)``:
 *     - Pages (local, sync, from ``@/lib/navIndex``)
 *     - Customers (from ``/api/search/global``)
 *     - Documents (Jobs + Invoices, merged, from same endpoint)
 * * Backend fetch is debounced 300 ms + cancellable via
 *   AbortController — stale keystrokes truly abort mid-flight.
 * * On transient backend error, prior results are preserved so
 *   the panel doesn't flash empty.
 * * Enter navigates to the appropriate route based on row kind:
 *     Page      → ``rec.path`` (navIndex-provided)
 *     Customer  → ``/customers/${id}``
 *     Document/job     → ``/jobs/${id}``  (App.js:938)
 *     Document/invoice → ``/invoices/${id}``  (App.js:950)
 * * Empty state ("No results for `<q>`") only when q has ≥ 2
 *   chars AND all three groups are empty AND no error.
 */
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { colors } from "@/theme";
import { useGlobalSearch } from "@/hooks/useGlobalSearch";


/** Detect Mac for the ``⌘K`` vs ``Ctrl+K`` hint. */
function _detectMac() {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || navigator.platform || "";
  return /Mac|iPhone|iPad|iPod/i.test(ua);
}


/** Compute the customer address subline. Uses structured fields
 *  when available, falls back to the legacy concatenated
 *  ``address`` field if the structured fields are absent. */
function _customerAddressLine(c) {
  const line1 = (c.address_line1 || "").trim();
  const city = (c.city || "").trim();
  const postal = (c.postal_code || "").trim();
  if (line1 || city || postal) {
    const parts = [line1, [city, postal].filter(Boolean).join(" ")];
    return parts.filter(Boolean).join(", ");
  }
  return (c.address || "").trim();
}


export function PageHeader({ title, subtitle, actions, filterBar = null }) {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const { pages, customers, documents, loading, error }
    = useGlobalSearch(query);
  const isMac = useMemo(() => _detectMac(), []);
  const kbdHint = isMac ? "\u2318K" : "Ctrl+K";  // ⌘K

  // ── Flat row list for keyboard nav — sections are visual only.
  //    Each row carries { kind, rec, sectionIndex } so ``commit``
  //    can dispatch on kind without another lookup.
  const flatRows = useMemo(() => {
    const rows = [];
    pages.forEach((rec) =>
      rows.push({ kind: "page", rec }));
    customers.forEach((rec) =>
      rows.push({ kind: "customer", rec }));
    documents.forEach((rec) =>
      rows.push({ kind: "document", rec }));
    return rows;
  }, [pages, customers, documents]);

  // Keep highlight in bounds whenever the QUERY changes. NOT on
  // ``flatRows.length`` — a length change triggered by an async
  // backend arrival would fire mid-way through a keystroke burst
  // and reset the user's cursor unexpectedly.
  useEffect(() => {
    setHighlight(0);
  }, [query]);

  const clearAndClose = useCallback(() => {
    setQuery("");
    setHighlight(0);
    if (inputRef.current) inputRef.current.blur();
  }, []);

  const commit = useCallback((row) => {
    if (!row || !row.rec) return;
    let target = null;
    if (row.kind === "page") {
      target = row.rec.path;
    } else if (row.kind === "customer") {
      if (row.rec.id) target = `/customers/${row.rec.id}`;
    } else if (row.kind === "document") {
      if (row.rec.type === "invoice" && row.rec.id) {
        target = `/invoices/${row.rec.id}`;
      } else if (row.rec.type === "job" && row.rec.id) {
        target = `/jobs/${row.rec.id}`;
      }
    }
    if (!target) return;
    clearAndClose();
    navigate(target);
  }, [clearAndClose, navigate]);

  // Event handler — deliberately NOT memoized. React re-creates
  // on every render (cheap) so ``flatRows`` + ``highlight`` are
  // always fresh from render scope. useCallback memoisation risks
  // capturing stale ``flatRows`` between synchronous fireEvents
  // when a backend arrival changes the row count mid-burst.
  const onKeyDown = (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      clearAndClose();
      return;
    }
    if (!flatRows.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, flatRows.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      // Bounds guard — if backend results shrunk mid-nav, clamp
      // to the last valid row.
      const idx = Math.min(highlight, flatRows.length - 1);
      if (idx >= 0) commit(flatRows[idx]);
    }
  };

  const q = query.trim();
  const hasAnyResults = flatRows.length > 0;
  const showEmptyState = q.length >= 2 && !hasAnyResults && !loading && !error;
  const dropdownOpen = q.length > 0 && (hasAnyResults || showEmptyState || loading);

  // ── section renderer ──
  const renderSection = (label, kind, rows, startFlatIdx) => {
    if (!rows.length) return null;
    return (
      <li
        role="presentation"
        style={{ padding: 0 }}
        data-testid={`page-header-section-${kind}`}
      >
        <div
          style={{
            padding: "8px 10px 4px",
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: 0.4,
            textTransform: "uppercase",
            color: colors.muted,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
          data-testid={`page-header-section-header-${kind}`}
        >
          <span>{label}</span>
          <span data-testid={`page-header-section-count-${kind}`}>
            {rows.length}
          </span>
        </div>
        <ul role="group" style={{
          margin: 0, padding: 0, listStyle: "none",
        }}>
          {rows.map((rec, idx) => {
            const flatIdx = startFlatIdx + idx;
            const active = flatIdx === highlight;
            return (
              <li
                key={`${kind}-${rec.id || rec.path}-${idx}`}
                role="option"
                aria-selected={active}
                onMouseDown={(e) => {
                  e.preventDefault();
                  commit({ kind, rec });
                }}
                onMouseEnter={() => setHighlight(flatIdx)}
                style={{
                  padding: "8px 10px",
                  borderRadius: 6,
                  cursor: "pointer",
                  backgroundColor: active
                    ? colors.brandTertiary
                    : "transparent",
                  borderLeft: active
                    ? `3px solid ${colors.nav.bg}`
                    : "3px solid transparent",
                  color: colors.onSurface,
                  fontSize: 14,
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                }}
                data-testid={`page-header-search-result-${flatIdx}`}
              >
                {kind === "page" ? (
                  <>
                    <span>{rec.title}</span>
                    <span style={{
                      fontSize: 12, color: colors.muted,
                    }}>
                      {rec.path}
                    </span>
                  </>
                ) : null}
                {kind === "customer" ? (
                  <>
                    <span style={{ fontWeight: 600 }}>{rec.name}</span>
                    <span style={{
                      fontSize: 12, color: colors.muted,
                    }} data-testid={`customer-address-${flatIdx}`}>
                      {_customerAddressLine(rec) || "\u2014"}
                    </span>
                  </>
                ) : null}
                {kind === "document" ? (
                  <div style={{
                    display: "flex", alignItems: "center", gap: 8,
                  }}>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        letterSpacing: 0.5,
                        textTransform: "uppercase",
                        padding: "2px 6px",
                        borderRadius: 4,
                        color: colors.surface,
                        backgroundColor: rec.type === "invoice"
                          ? colors.inputBorder  // blue for invoice
                          : colors.nav.bg,      // navy for job
                      }}
                      data-testid={`doc-badge-${flatIdx}`}
                    >
                      {rec.type === "invoice" ? "Invoice" : "Job"}
                    </span>
                    <span style={{
                      fontFamily: "SFMono-Regular, Menlo, monospace",
                      fontSize: 13,
                    }}>
                      {rec.display_id}
                    </span>
                    <span style={{
                      color: colors.muted, fontSize: 13,
                      overflow: "hidden", textOverflow: "ellipsis",
                      whiteSpace: "nowrap", flex: "1 1 auto", minWidth: 0,
                    }}>
                      {rec.title}
                    </span>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </li>
    );
  };

  // Compute the starting flat index for each section.
  const pagesStart = 0;
  const customersStart = pages.length;
  const documentsStart = pages.length + customers.length;

  return (
    <header
      style={{ width: "100%", background: "transparent" }}
      data-testid="page-header"
    >
      {/* Row 1 · slim navy command-bar band with the search input.
          Feb-2026 · N5.reorder — moved above the title row and
          restyled from a full-bleed blue hero (colors.inputBorder)
          into a contained navy card mirroring the C3
          NavyFilterBar treatment: navy bg + subtle nav.border
          stroke + rounded-2xl (16px) corners + horizontal 24px
          margin so the corners are visible and never bleed
          edge-to-edge. */}
      <div
        style={{
          backgroundColor: colors.nav.bg,
          border: `1px solid ${colors.nav.border}`,
          borderRadius: 16,
          margin: "20px 24px 8px",
          padding: "10px 16px",
          position: "relative",
        }}
        data-testid="page-header-search-band"
      >
        <div
          style={{
            position: "relative",
            maxWidth: 640,
            margin: "0 auto",
          }}
        >
          <div
            style={{
              position: "relative",
              display: "flex",
              alignItems: "center",
              backgroundColor: colors.surface,
              border: "none",
              borderRadius: 999,
              paddingLeft: 34,
              paddingRight: 68,
              height: 34,
            }}
            data-testid="page-header-search-input-wrap"
          >
            <Search
              size={16}
              style={{
                position: "absolute",
                left: 10,
                color: colors.nav.bg,
                pointerEvents: "none",
              }}
              aria-hidden="true"
              data-testid="page-header-search-icon"
            />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Jump to page... (e.g., PDF Upload, Invoices, Fuel Tracking)"
              aria-label="Jump to page"
              style={{
                width: "100%",
                border: "none",
                outline: "none",
                background: "transparent",
                color: colors.onSurface,
                fontSize: 14,
              }}
              data-testid="page-header-search-input"
            />
            <span
              style={{
                position: "absolute",
                right: 10,
                fontSize: 11,
                letterSpacing: 0.5,
                color: "#3F3F46",
                padding: "2px 6px",
                borderRadius: 4,
                backgroundColor: colors.surfaceSecondary,
                pointerEvents: "none",
              }}
              data-testid="page-header-search-kbd-hint"
            >
              {kbdHint}
            </span>
          </div>

          {dropdownOpen ? (
            <ul
              role="listbox"
              style={{
                position: "absolute",
                top: "calc(100% + 4px)",
                left: 0,
                right: 0,
                maxWidth: 640,
                margin: 0,
                padding: 4,
                listStyle: "none",
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
                borderRadius: 8,
                boxShadow: "0 6px 20px rgba(0, 0, 0, 0.12)",
                zIndex: 40,
              }}
              data-testid="page-header-search-dropdown"
            >
              {renderSection("Pages", "page", pages, pagesStart)}
              {loading && q.length >= 2 ? (
                <li
                  role="presentation"
                  data-testid="page-header-loading-shimmer"
                  style={{
                    padding: "8px 10px",
                    fontSize: 12,
                    color: colors.muted,
                    fontStyle: "italic",
                  }}
                >
                  Loading customers &amp; documents\u2026
                </li>
              ) : null}
              {renderSection("Customers", "customer", customers, customersStart)}
              {renderSection("Documents", "document", documents, documentsStart)}
              {showEmptyState ? (
                <li
                  role="presentation"
                  data-testid="page-header-empty-state"
                  style={{
                    padding: "8px 10px",
                    fontSize: 13,
                    color: colors.muted,
                  }}
                >
                  No results for &ldquo;{q}&rdquo;
                </li>
              ) : null}
            </ul>
          ) : null}
        </div>
      </div>

      {/* Row 2 · title + actions. Feb-2026 · N5.reorder — moved
          below the search band. Top padding trimmed and bottom
          padding grown so the vertical rhythm from the pre-reorder
          layout is preserved (band's 20 top + 8 bottom margins
          absorb the removed title-row top padding). */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          padding: "8px 24px 20px",
        }}
        data-testid="page-header-title-row"
      >
        <div style={{ minWidth: 0, flex: "1 1 auto" }}>
          <h1
            style={{
              fontSize: 28,
              lineHeight: 1.2,
              fontWeight: 700,
              margin: 0,
              color: colors.onSurface,
            }}
            data-testid="page-header-title"
          >
            {title}
          </h1>
          {subtitle ? (
            <p
              style={{
                fontSize: 13,
                lineHeight: 1.4,
                margin: "4px 0 0",
                color: colors.muted,
              }}
              data-testid="page-header-subtitle"
            >
              {subtitle}
            </p>
          ) : null}
        </div>
        {actions ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flex: "0 0 auto",
            }}
            data-testid="page-header-actions"
          >
            {actions}
          </div>
        ) : null}
      </div>

      {/* Row 3 · optional filter-bar slot. N5.filterBar consolidation
          preflight — N5-T2 will migrate the 4 pages currently
          rendering ``<NavyFilterBar>`` under an inline ``<h1>`` into
          ``<PageHeader filterBar={<NavyFilterBar>...</NavyFilterBar>}>``.
          Consumers pass the child element as-is; PageHeader owns
          only the placement + horizontal alignment (24px to match
          the search-band + title-row insets). NavyFilterBar's own
          ``rounded-2xl p-4 mb-4`` primitive supplies the bg/border/
          bottom-margin so this slot never fights the child for
          layout. Omitting the prop = zero DOM change (backwards
          compat for every page already consuming PageHeader). */}
      {filterBar ? (
        <div
          style={{ padding: "0 24px" }}
          data-testid="page-header-filter-bar-slot"
        >
          {filterBar}
        </div>
      ) : null}
    </header>
  );
}

export default PageHeader;
