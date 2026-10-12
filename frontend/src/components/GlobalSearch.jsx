/**
 * Phase GLOBAL-SEARCH-UNIFY · Feb-2026 — Standalone ⌘K palette.
 *
 * Responsibilities lifted OUT of ``PageHeader``:
 *   • Owns its own open / close state (modal, not always-visible).
 *   • Global ``⌘K`` (mac) / ``Ctrl+K`` (win) keydown listener,
 *     scoped to ``window`` and cleaned up on unmount.
 *   • ``Escape`` closes the palette and restores focus to whatever
 *     was active before the shortcut fired.
 *   • ``useGlobalSearchResults(query)`` orchestrates the debounced
 *     grouped search (pages · customers · documents) — the SAME
 *     hook the always-visible ``<GlobalSearchBar>`` (top bar)
 *     consumes so the two entry points can never drift on
 *     backend shape.
 *   • Enter commits the highlighted row and navigates via
 *     ``react-router-dom``'s ``useNavigate``.
 *
 * Styling contract (spec):
 *   • Solid white background (``#FFFFFF``) — no transparency, no
 *     gradient, no dark-mode inversion. Palette is admin-only so
 *     the Customer Portal Dark Theme (DTP-2) does not apply.
 *   • Solid black text (``#000000``).
 *   • Highlighted (keyboard-focused) row uses a light-gray
 *     background so it stays legible against the white surface.
 *
 * The component renders NOTHING when closed. Mount cost is one
 * ``useEffect`` + a couple of ``useState`` cells.
 */
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { colors } from "@/theme";
import { Search, X } from "lucide-react";
import { useGlobalSearchResults } from "@/hooks/useGlobalSearchResults";


// Palette colour tokens — SPEC-locked. Do not swap for design-system
// vars: the spec calls for solid white / black on THIS surface
// specifically.
const PALETTE_BG      = "#FFFFFF";
const PALETTE_FG      = "#000000";
const PALETTE_MUTED   = "#525252";
// ``PALETTE_HIGHLIGHT`` sits between palette-bg and #E5E5E5 so the
// keyboard highlight is discoverable without shouting.
const PALETTE_HIGHLIGHT = "#EEEEEE";
const PALETTE_BORDER  = "#D4D4D4";
const PALETTE_BADGE_BG_INVOICE = "#0EA5E9";
const PALETTE_BADGE_BG_QUOTE   = "#059669";
const PALETTE_BADGE_BG_JOB     = "#1B1F5C";


function _detectMac() {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || navigator.platform || "";
  return /Mac|iPhone|iPad|iPod/i.test(ua);
}


// Feb-2026 · migration to consolidated ``/api/search`` — badge label
// + background lookup keyed on the ``kind`` tag the hook attaches
// to every merged document row.
const _DOC_BADGE_LABEL = {
  job: "Job", invoice: "Invoice", quote: "Quote",
};
const _DOC_BADGE_BG = {
  job: PALETTE_BADGE_BG_JOB,
  invoice: PALETTE_BADGE_BG_INVOICE,
  quote: PALETTE_BADGE_BG_QUOTE,
};


export default function GlobalSearch({ initialQuery = "" } = {}) {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  // Captured the moment ⌘K opens the palette so ``Escape`` can
  // restore focus to whatever the user was in beforehand.
  const previousActiveElementRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(initialQuery);
  const [highlight, setHighlight] = useState(0);
  const { pages, customers, documents, loading, error }
    = useGlobalSearchResults(query);
  const isMac = useMemo(() => _detectMac(), []);
  const kbdHint = isMac ? "\u2318K" : "Ctrl+K";

  const flatRows = useMemo(() => {
    const rows = [];
    pages.forEach((rec) => rows.push({ kind: "page", rec }));
    customers.forEach((rec) => rows.push({ kind: "customer", rec }));
    documents.forEach((rec) => rows.push({ kind: "document", rec }));
    return rows;
  }, [pages, customers, documents]);

  // Reset the highlight on QUERY change (not on flatRows.length —
  // async backend arrivals mid-keystroke shouldn't jump the cursor).
  useEffect(() => { setHighlight(0); }, [query]);

  // ── ⌘K / Ctrl+K global open ──────────────────────────────────
  useEffect(() => {
    const onKey = (e) => {
      const isMetaK = (e.metaKey || e.ctrlKey)
        && (e.key || "").toLowerCase() === "k";
      if (!isMetaK) return;
      const target = e.target;
      const tag = ((target && target.tagName) || "").toUpperCase();
      const contentEditable = !!(
        target && target.getAttribute
        && target.getAttribute("contenteditable") === "true"
      );
      const inEditable = tag === "INPUT"
                          || tag === "TEXTAREA"
                          || tag === "SELECT"
                          || contentEditable;
      if (inEditable && target !== inputRef.current) return;
      e.preventDefault();
      // Idempotent re-press: already open + focused → no-op.
      if (open && document.activeElement === inputRef.current) return;
      // Capture pre-open focus target for Escape restoration.
      previousActiveElementRef.current = document.activeElement || null;
      setOpen(true);
      setQuery(initialQuery);
      setHighlight(0);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, initialQuery]);

  // ── Focus the input as soon as the modal opens. ──────────────
  useEffect(() => {
    if (!open) return undefined;
    // Yield a tick so the input element has actually mounted.
    const id = window.setTimeout(() => {
      const el = inputRef.current;
      if (el && typeof el.focus === "function") {
        try { el.focus(); } catch { /* jsdom rarely — silent */ }
        if (typeof el.select === "function") {
          try { el.select(); } catch { /* non-text — silent */ }
        }
      }
    }, 0);
    return () => window.clearTimeout(id);
  }, [open]);

  const closeAndRestoreFocus = useCallback(() => {
    setOpen(false);
    setQuery("");
    setHighlight(0);
    const prev = previousActiveElementRef.current;
    previousActiveElementRef.current = null;
    if (prev && typeof prev.focus === "function") {
      try { prev.focus(); } catch { /* jsdom / detached — silent */ }
    }
  }, []);

  const commit = useCallback((row) => {
    if (!row || !row.rec) return;
    let target = null;
    if (row.kind === "page") {
      target = row.rec.path;
    } else if (row.kind === "customer") {
      if (row.rec.id) target = `/customers/${row.rec.id}`;
    } else if (row.kind === "document") {
      // Feb-2026 · migration to consolidated ``/api/search`` — the
      // merged ``documents`` list carries a ``rec.kind`` tag (job /
      // invoice / quote) so we route each row to its canonical
      // detail page without a doc_type lookup.
      const k = row.rec.kind;
      if (row.rec.id && k === "invoice") target = `/invoices/${row.rec.id}`;
      else if (row.rec.id && k === "quote") target = `/quotes/${row.rec.id}`;
      else if (row.rec.id && k === "job") target = `/jobs/${row.rec.id}`;
    }
    if (!target) return;
    closeAndRestoreFocus();
    navigate(target);
  }, [closeAndRestoreFocus, navigate]);

  const onInputKeyDown = (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      closeAndRestoreFocus();
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
      const idx = Math.min(highlight, flatRows.length - 1);
      if (idx >= 0) commit(flatRows[idx]);
    }
  };

  // Closed state — render nothing. Mounted-but-invisible is the
  // canonical "modal palette" pattern (VSCode, Slack, Linear).
  if (!open) return null;

  const q = query.trim();
  const hasAnyResults = flatRows.length > 0;
  const showEmptyState = q.length >= 2 && !hasAnyResults && !loading && !error;

  const pagesStart = 0;
  const customersStart = pages.length;
  const documentsStart = pages.length + customers.length;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Global search"
      data-testid="global-search-overlay"
      onMouseDown={(e) => {
        // Click outside the panel closes the palette. Guard so a
        // mousedown on the panel itself doesn't dismiss.
        if (e.target === e.currentTarget) closeAndRestoreFocus();
      }}
      style={{
        position: "fixed",
        top: 0, left: 0, right: 0, bottom: 0,
        // Barely-there scrim so the underlying page stays readable
        // but focus visually lands on the palette.
        backgroundColor: "rgba(0, 0, 0, 0.28)",
        zIndex: 1000,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: "10vh",
      }}
    >
      <div
        // Solid white / black text — SPEC-locked; DO NOT swap for
        // theme tokens on this surface.
        style={{
          width: "min(680px, calc(100vw - 32px))",
          backgroundColor: PALETTE_BG,
          color: PALETTE_FG,
          border: `1px solid ${PALETTE_BORDER}`,
          borderRadius: 12,
          boxShadow: "0 20px 40px rgba(0, 0, 0, 0.25)",
          overflow: "hidden",
        }}
        data-testid="global-search-panel"
      >
        {/* Row 1 · input strip */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            padding: "10px 12px",
            borderBottom: `1px solid ${PALETTE_BORDER}`,
            gap: 8,
          }}
        >
          <Search size={16} color={colors.searchIcon} aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder="Search pages, customers, documents…"
            aria-label="Global search"
            style={{
              flex: "1 1 auto",
              minWidth: 0,
              border: "none",
              outline: "none",
              backgroundColor: PALETTE_BG,
              color: PALETTE_FG,
              fontSize: 15,
              padding: "4px 0",
            }}
            data-testid="global-search-input"
          />
          <span
            style={{
              fontSize: 11,
              letterSpacing: 0.5,
              color: PALETTE_MUTED,
              padding: "2px 6px",
              borderRadius: 4,
              backgroundColor: PALETTE_HIGHLIGHT,
            }}
            data-testid="global-search-kbd-hint"
          >
            {kbdHint}
          </span>
          <button
            type="button"
            onClick={closeAndRestoreFocus}
            aria-label="Close search"
            style={{
              background: "transparent",
              border: 0,
              padding: 4,
              cursor: "pointer",
              color: PALETTE_MUTED,
            }}
            data-testid="global-search-close-btn"
          >
            <X size={16} />
          </button>
        </div>

        {/* Row 2 · dropdown body (always renders when open; empty
             results still get a helpful hint). */}
        <ul
          role="listbox"
          style={{
            margin: 0,
            padding: 4,
            listStyle: "none",
            maxHeight: "60vh",
            overflowY: "auto",
            backgroundColor: PALETTE_BG,
          }}
          data-testid="global-search-listbox"
        >
          {q.length === 0 ? (
            <li
              role="presentation"
              style={{
                padding: "10px 12px", fontSize: 13,
                color: PALETTE_MUTED,
              }}
              data-testid="global-search-hint"
            >
              Type to search pages, customers, and documents…
            </li>
          ) : null}

          <Section label="Pages" kind="page"
                    rows={pages} startFlatIdx={pagesStart}
                    highlight={highlight} setHighlight={setHighlight}
                    commit={commit} />

          {loading && q.length >= 2 ? (
            <li
              role="presentation"
              data-testid="global-search-loading"
              style={{
                padding: "8px 10px",
                fontSize: 12,
                color: PALETTE_MUTED,
                fontStyle: "italic",
              }}
            >
              Loading customers &amp; documents…
            </li>
          ) : null}

          <Section label="Customers" kind="customer"
                    rows={customers} startFlatIdx={customersStart}
                    highlight={highlight} setHighlight={setHighlight}
                    commit={commit} />
          <Section label="Documents" kind="document"
                    rows={documents} startFlatIdx={documentsStart}
                    highlight={highlight} setHighlight={setHighlight}
                    commit={commit} />

          {showEmptyState ? (
            <li
              role="presentation"
              data-testid="global-search-empty-state"
              style={{
                padding: "10px 12px", fontSize: 13,
                color: PALETTE_MUTED,
              }}
            >
              No results for &ldquo;{q}&rdquo;
            </li>
          ) : null}
        </ul>
      </div>
    </div>
  );
}


// ── Section renderer ────────────────────────────────────────────
// Kept as an inner component (not a helper function) so React can
// bail cleanly on empty ``rows`` without allocating a wrapper LI.
function Section({ label, kind, rows, startFlatIdx,
                     highlight, setHighlight, commit }) {
  if (!rows.length) return null;
  return (
    <li
      role="presentation"
      style={{ padding: 0 }}
      data-testid={`global-search-section-${kind}`}
    >
      <div
        style={{
          padding: "8px 10px 4px",
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: 0.4,
          textTransform: "uppercase",
          color: PALETTE_MUTED,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span>{label}</span>
        <span>{rows.length}</span>
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
                // Selected row highlight — solid light-gray so it
                // reads clearly against the palette-white bg.
                backgroundColor: active ? PALETTE_HIGHLIGHT : "transparent",
                borderLeft: active
                  ? `3px solid ${PALETTE_FG}`
                  : "3px solid transparent",
                color: PALETTE_FG,
                fontSize: 14,
                display: "flex",
                flexDirection: "column",
                gap: 2,
              }}
              data-testid={`global-search-result-${flatIdx}`}
              data-kind={kind}
              data-active={active ? "true" : "false"}
            >
              {kind === "page" ? (
                <>
                  <span>{rec.title}</span>
                  <span style={{ fontSize: 12, color: PALETTE_MUTED }}>
                    {rec.path}
                  </span>
                </>
              ) : null}
              {kind === "customer" ? (
                <>
                  {/* Feb-2026 · migration to consolidated
                      ``/api/search`` — row shape is now
                      ``{id, primary, secondary}`` (was
                      ``{id, name, address_line1, ...}``).  The
                      ``primary`` field carries the customer name;
                      ``secondary`` carries whichever of email /
                      phone / address the backend chose to show. */}
                  <span style={{ fontWeight: 600 }}>{rec.primary}</span>
                  <span style={{ fontSize: 12, color: PALETTE_MUTED }}>
                    {rec.secondary || "\u2014"}
                  </span>
                </>
              ) : null}
              {kind === "document" ? (
                <div style={{
                  display: "flex", alignItems: "center", gap: 8,
                }}>
                  {/* Feb-2026 · migration to consolidated
                      ``/api/search`` — the merged ``documents``
                      list tags every row with ``rec.kind`` (job /
                      invoice / quote) so we badge each one
                      individually.  ``primary`` already carries
                      the display id (e.g. "Invoice INV-123"),
                      ``secondary`` carries the customer name +
                      formatted total. */}
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      letterSpacing: 0.5,
                      textTransform: "uppercase",
                      padding: "2px 6px",
                      borderRadius: 4,
                      color: "#FFFFFF",
                      backgroundColor:
                        _DOC_BADGE_BG[rec.kind] || PALETTE_BADGE_BG_JOB,
                    }}
                  >
                    {_DOC_BADGE_LABEL[rec.kind] || "Doc"}
                  </span>
                  <span style={{
                    fontFamily: "SFMono-Regular, Menlo, monospace",
                    fontSize: 13,
                  }}>
                    {rec.primary}
                  </span>
                  <span style={{
                    color: PALETTE_MUTED, fontSize: 13,
                    overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap", flex: "1 1 auto", minWidth: 0,
                  }}>
                    {rec.secondary || ""}
                  </span>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </li>
  );
}
