/**
 * Feb-2026 · N1 · Shared page-header component.
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
 *   Row 2 · slim navy hero band with search input.
 *   Row 3 · absolute-positioned dropdown pane (max 8 results,
 *           keyboard nav via ↑/↓, Enter navigates, Esc clears).
 *
 * Design tokens
 * ─────────────
 *   Search band background = ``colors.nav.bg`` (#1B1F5C · WEB
 *   nav chrome, defined in ``theme.js``).  Input border =
 *   ``colors.inputBorder`` (#3B82F6 · permanent search-border
 *   blue defined in ``theme.js``).  White input surface, dark
 *   text, muted keyboard hint on the right.
 *
 * Cmd+K global shortcut (N3) is NOT wired here.  Only the local
 * search UX ships in N1.  N2 wires this component into every
 * page's H1 slot in one sweep.
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
import { searchNavIndex } from "@/lib/navIndex";


/** Detect Mac for the ``⌘K`` vs ``Ctrl+K`` hint.  SSR-safe fallback
 *  is Ctrl since the visible chrome is a rendering hint only. */
function _detectMac() {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || navigator.platform || "";
  return /Mac|iPhone|iPad|iPod/i.test(ua);
}


export function PageHeader({ title, subtitle, actions }) {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const results = useMemo(
    () => (query.trim() ? searchNavIndex(query) : []),
    [query],
  );
  const isMac = useMemo(() => _detectMac(), []);
  const kbdHint = isMac ? "\u2318K" : "Ctrl+K";  // ⌘K

  // Keep highlight in bounds whenever the result set changes.
  useEffect(() => {
    setHighlight(0);
  }, [query]);

  const clearAndClose = useCallback(() => {
    setQuery("");
    setHighlight(0);
    if (inputRef.current) inputRef.current.blur();
  }, []);

  const commit = useCallback((rec) => {
    if (!rec || !rec.path) return;
    clearAndClose();
    navigate(rec.path);
  }, [clearAndClose, navigate]);

  const onKeyDown = useCallback((e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      clearAndClose();
      return;
    }
    if (!results.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      commit(results[highlight]);
    }
  }, [results, highlight, commit, clearAndClose]);

  const dropdownOpen = query.trim().length > 0 && results.length > 0;

  return (
    <header
      style={{ width: "100%", background: "transparent" }}
      data-testid="page-header"
    >
      {/* Row 1 · title + actions */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          padding: "20px 24px 8px",
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

      {/* Row 2 · slim navy band with the search input */}
      <div
        style={{
          backgroundColor: colors.nav.bg,
          padding: "8px 24px",
          position: "relative",
        }}
        data-testid="page-header-search-band"
      >
        <div style={{ position: "relative", maxWidth: 640 }}>
          <div
            style={{
              position: "relative",
              display: "flex",
              alignItems: "center",
              backgroundColor: colors.surface,
              borderStyle: "solid",
              borderWidth: 1,
              borderColor: colors.inputBorder,
              borderRadius: 8,
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
                color: colors.inputBorder,
                pointerEvents: "none",
              }}
              aria-hidden="true"
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
                color: colors.muted,
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
              {results.map((rec, idx) => {
                const active = idx === highlight;
                return (
                  <li
                    key={rec.path}
                    role="option"
                    aria-selected={active}
                    onMouseDown={(e) => {
                      // ``mousedown`` so the click fires before the
                      // input's ``blur`` collapses the dropdown.
                      e.preventDefault();
                      commit(rec);
                    }}
                    onMouseEnter={() => setHighlight(idx)}
                    style={{
                      padding: "8px 10px",
                      borderRadius: 6,
                      cursor: "pointer",
                      backgroundColor: active
                        ? colors.brandTertiary
                        : "transparent",
                      color: colors.onSurface,
                      fontSize: 14,
                    }}
                    data-testid={`page-header-search-result-${idx}`}
                  >
                    {rec.title}
                    <span
                      style={{
                        marginLeft: 8,
                        fontSize: 12,
                        color: colors.muted,
                      }}
                    >
                      {rec.path}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      </div>
    </header>
  );
}

export default PageHeader;
