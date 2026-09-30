/**
 * Phase PRICEBOOK-UNIFY · Feb-2026 — Standalone pricebook item
 * picker extracted from ``K71PricebookPicker`` inside
 * :file:`components/quotes/K71LineItemsEditor.jsx`.
 *
 * Contract
 * ────────
 *   <PricebookItemPicker
 *     value={line.description}
 *     onChange={(text) => …}          // required — free-text edit
 *     onSelect={(item) => …}          // required — picked a real item
 *     placeholder="Search pricebook…" // optional
 *     disabled={false}                // optional
 *     testidPrefix="k71-pricebook-search"  // optional — used for
 *                                     // data-testid namespacing so
 *                                     // K71 can preserve its
 *                                     // historical selectors while
 *                                     // new consumers namespace on
 *                                     // ``pricebook-picker``.
 *     inputTestid="..."               // optional — override the
 *                                     // input's data-testid; K71
 *                                     // sets this to
 *                                     // ``k71-input-item-<i>-input``
 *     wrapperTestid="..."             // optional — override the
 *                                     // outer wrapper's data-testid.
 *                                     // K71 sets this per-row to
 *                                     // ``k71-input-item-<i>`` so
 *                                     // legacy tests keep resolving.
 *                                     // Defaults to
 *                                     // ``${testidPrefix}-wrapper``.
 *   />
 *
 * Behaviour
 * ─────────
 *   • Debounces the ``GET /api/items`` request 250 ms per keystroke.
 *   • Monotonic request-id race guard drops stale responses.
 *   • ArrowUp / ArrowDown navigate the results list; Enter selects
 *     the currently-highlighted row; Escape closes the dropdown.
 *   • Outside-click closes the dropdown.
 *   • Empty / whitespace value short-circuits — no request fired,
 *     no dropdown rendered.
 *
 * Accessibility
 * ─────────────
 *   • Wrapper carries ``role="combobox"``,
 *     ``aria-expanded={showDropdown}``, ``aria-haspopup="listbox"``.
 *   • Dropdown renders as ``role="listbox"``; individual result
 *     buttons as ``role="option"`` with ``aria-selected`` on the
 *     keyboard-highlighted row.
 */
import React, { useEffect, useRef, useState, useCallback } from "react";
import { Search } from "lucide-react";

import { api } from "@/api";
import { colors, money } from "@/theme";


// Feb-2026 — 50 rows matches the K71 default and keeps the dropdown
// interaction snappy without paging.  Bump / drop via a caller
// prop later if any consumer wants a different cap.
const PICKER_MAX_RESULTS = 50;
const PICKER_DEBOUNCE_MS = 250;


export default function PricebookItemPicker({
  value,
  onChange,
  onSelect,
  placeholder = "Search pricebook…",
  disabled = false,
  testidPrefix = "pricebook-picker",
  inputTestid,
  wrapperTestid,
}) {
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const wrapRef = useRef(null);
  const inputRef = useRef(null);
  // Monotonic request id — every keystroke bumps this. Response
  // handlers compare against the LATEST value and discard stale
  // ones. Same pattern React Router / TanStack Query use for
  // request-cancellation-lite when native AbortSignal isn't wired.
  const reqSeqRef = useRef(0);

  useEffect(() => { setHighlight(0); }, [results]);

  // Outside-click closes the dropdown.
  useEffect(() => {
    if (!open) return undefined;
    const onDocClick = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  // Debounced search. Cleared / empty ``value`` short-circuits —
  // no request fired, results wiped.
  useEffect(() => {
    const trimmed = (value || "").trim();
    if (!trimmed) {
      setResults([]);
      setLoading(false);
      return undefined;
    }
    setLoading(true);
    const mySeq = ++reqSeqRef.current;
    const t = setTimeout(async () => {
      try {
        const params = new URLSearchParams({
          search: trimmed,
          active: "true",
          limit: String(PICKER_MAX_RESULTS),
        }).toString();
        const rows = await api.get(`/items?${params}`);
        // Stale response — a newer keystroke bumped the counter
        // after we captured ``mySeq``. Drop this batch.
        if (mySeq !== reqSeqRef.current) return;
        setResults(Array.isArray(rows) ? rows : []);
      } catch {
        if (mySeq !== reqSeqRef.current) return;
        setResults([]);
      } finally {
        if (mySeq === reqSeqRef.current) setLoading(false);
      }
    }, PICKER_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [value]);

  const handleTextChange = (next) => {
    if (typeof onChange === "function") onChange(next);
    if ((next || "").trim()) setOpen(true);
  };

  const handlePick = useCallback((row) => {
    if (typeof onSelect === "function") onSelect(row);
    setOpen(false);
  }, [onSelect]);

  const onKeyDown = (e) => {
    if (e.key === "Escape") {
      if (open) {
        e.preventDefault();
        setOpen(false);
      }
      return;
    }
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      handlePick(results[Math.min(highlight, results.length - 1)]);
    }
  };

  const trimmed = (value || "").trim();
  const showDropdown = open && trimmed.length > 0;

  return (
    <div
      ref={wrapRef}
      className="relative"
      role="combobox"
      aria-expanded={showDropdown}
      aria-haspopup="listbox"
      aria-owns={`${testidPrefix}-dropdown`}
      data-testid={wrapperTestid || `${testidPrefix}-wrapper`}
    >
      <div className="relative">
        <Search
          size={14}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none"
          style={{ color: colors.searchIcon || colors.muted }}
        />
        <input
          ref={inputRef}
          type="text"
          value={value || ""}
          onChange={(e) => handleTextChange(e.target.value)}
          onFocus={() => { if (trimmed) setOpen(true); }}
          onClick={() => { if (trimmed) setOpen(true); }}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder={placeholder}
          className="w-full text-sm rounded-lg py-2 pl-8 pr-3"
          style={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
            opacity: disabled ? 0.55 : 1,
          }}
          data-testid={inputTestid || `${testidPrefix}-input`}
          autoComplete="off"
        />
      </div>

      {showDropdown ? (
        <div
          id={`${testidPrefix}-dropdown`}
          role="listbox"
          className="absolute z-[60] left-0 right-0 mt-1 rounded-lg overflow-hidden shadow-lg"
          style={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            maxHeight: 300,
            overflowY: "auto",
          }}
          data-testid={`${testidPrefix}-dropdown`}
        >
          {loading ? (
            <div
              className="px-3 py-2 text-xs"
              style={{ color: colors.muted }}
              data-testid={`${testidPrefix}-loading`}
            >
              Searching pricebook…
            </div>
          ) : null}
          {!loading && results.length === 0 ? (
            <div
              className="px-3 py-2 text-xs"
              style={{ color: colors.muted }}
              data-testid={`${testidPrefix}-empty`}
            >
              No pricebook items match &ldquo;{trimmed}&rdquo;.
              You can type a one-off name — it&rsquo;ll save on this line only.
            </div>
          ) : null}
          {!loading && results.map((row, i) => {
            const svcName = row.service_category_name || "";
            const incName = row.income_category_name || "";
            const legacyCat = row.category || "";
            const isActive = i === highlight;
            return (
              <button
                key={row.id ?? i}
                type="button"
                role="option"
                aria-selected={isActive}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setHighlight(i)}
                onClick={() => handlePick(row)}
                className="w-full text-left px-3 py-2 text-sm flex flex-col gap-1"
                style={{
                  color: colors.onSurface,
                  borderBottom: `1px solid ${colors.border}`,
                  backgroundColor: isActive
                    ? (colors.surfaceSecondary || "#F1F5F9")
                    : "transparent",
                }}
                data-testid={`${testidPrefix}-item-${i}`}
                data-active={isActive ? "true" : "false"}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-semibold truncate">{row.name}</span>
                  <span
                    className="text-xs tabular-nums shrink-0"
                    style={{ color: colors.muted }}
                  >
                    {money(Number(row.unit_price || 0))}
                  </span>
                </div>
                {row.description ? (
                  <div
                    className="text-xs truncate"
                    style={{ color: colors.muted }}
                    title={row.description}
                  >
                    {row.description}
                  </div>
                ) : null}
                {(svcName || incName || legacyCat) ? (
                  <div className="flex items-center flex-wrap gap-1 mt-0.5">
                    {svcName ? (
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide"
                        style={{
                          backgroundColor: colors.brandAccent
                            || colors.surfaceSecondary,
                          color: colors.onBrand || colors.onSurface,
                        }}
                      >
                        {svcName}
                      </span>
                    ) : null}
                    {incName ? (
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide"
                        style={{
                          backgroundColor: colors.surfaceSecondary,
                          color: colors.muted,
                        }}
                      >
                        {incName}
                      </span>
                    ) : null}
                    {(!svcName && legacyCat) ? (
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide"
                        style={{
                          backgroundColor: colors.surfaceSecondary,
                          color: colors.muted,
                        }}
                      >
                        {legacyCat}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
