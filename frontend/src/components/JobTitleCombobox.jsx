/**
 * Feb 2026 · Auto-learning Job Title combobox for the New Job /
 * Edit Job forms.
 *
 * Contract:
 *   • Wraps a plain ``<input>`` — the user can still free-type any
 *     title. No enforced dictionary — the whole point of this
 *     combobox is auto-learn.
 *   • On focus + after each keystroke (debounced 250ms) the
 *     component fetches ``GET /api/job-titles?q=<value>&limit=10``.
 *     The list is scoped tenant-side by the endpoint — no client
 *     filtering needed.
 *   • Suggestions render in an anchored ``<ul>`` panel. Click
 *     (or Enter / Tab while highlighted) fills the input and
 *     closes the panel.  Escape closes without touching the value.
 *   • Enter on free-typed text closes the panel and preserves
 *     whatever the user typed. Parent form save is responsible for
 *     the actual submit — this component never triggers submit.
 *
 * Auto-learn side of the loop is handled server-side: the
 * ``create_job`` and ``update_job`` routers call
 * ``record_title_usage`` on every save so the next open of this
 * combobox sees the new title. There is NO client-side POST
 * here — a bad network won't leak duplicate rows.
 *
 * Props:
 *   value      current input value (controlled)
 *   onChange   ``(nextValue) => void``. Called on typing AND on
 *              suggestion click.  Matches the ``TextInput`` /
 *              ``set()`` convention already in use on the job
 *              forms — the parent adapter can pass a value-only
 *              handler or a ``(e) => e.target.value`` wrapper.
 *   label      Optional label rendered above the input.
 *   placeholder / disabled / testid  standard passthroughs.
 *
 * Testids exposed:
 *   {testid}                     root
 *   {testid}-input               the underlying text input
 *   {testid}-panel               the suggestion panel (only when open)
 *   {testid}-option-<idx>        each suggestion row (0-based)
 */
import React, { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/api";
import { colors } from "@/theme";


function useDebounced(value, delay = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}


export default function JobTitleCombobox({
  value,
  onChange,
  label,
  placeholder = "Start typing a title…",
  disabled = false,
  testid = "job-title-combobox",
  autoFocus = false,
}) {
  const [open, setOpen] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const [loading, setLoading] = useState(false);
  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const debounced = useDebounced(value || "", 250);

  // Fetch suggestions on debounced value or focus-open. Empty ``q``
  // returns the top-usage catalog rows — matches the endpoint's
  // "no q → top hits" behaviour so a first-focus click on the
  // input shows something useful immediately.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    api
      .get(`/job-titles?q=${encodeURIComponent(debounced)}&limit=10`)
      .then((rows) => {
        if (!alive) return;
        setSuggestions(Array.isArray(rows) ? rows : []);
        setHighlightIdx(-1);
      })
      .catch(() => {
        // Silent — offline / 401 / 500 all degrade to plain free-
        // typing behaviour. Never blocks form save.
        if (alive) setSuggestions([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [open, debounced]);

  // Click-outside closes the panel.
  useEffect(() => {
    if (!open) return;
    const _onClick = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", _onClick);
    return () => document.removeEventListener("mousedown", _onClick);
  }, [open]);

  const commit = (choice) => {
    onChange && onChange(choice);
    setOpen(false);
    setHighlightIdx(-1);
  };

  const onKey = (e) => {
    if (!open) {
      // Down / Up opens the panel with the top row highlighted.
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        setOpen(true);
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIdx((i) =>
        suggestions.length ? Math.min(i + 1, suggestions.length - 1) : -1,
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      if (highlightIdx >= 0 && suggestions[highlightIdx]) {
        e.preventDefault();
        commit(suggestions[highlightIdx].title);
      } else {
        // Free-typed Enter — just close the panel; parent form
        // handles submit separately.
        setOpen(false);
      }
    } else if (e.key === "Tab") {
      if (highlightIdx >= 0 && suggestions[highlightIdx]) {
        e.preventDefault();
        commit(suggestions[highlightIdx].title);
      } else {
        setOpen(false);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const showLabel = useMemo(() => {
    if (!label) return null;
    return (
      <label
        className="text-xs font-semibold uppercase tracking-wide"
        style={{ color: colors.muted }}
        htmlFor={`${testid}-input`}
      >
        {label}
      </label>
    );
  }, [label, testid]);

  return (
    <div
      ref={rootRef}
      className="relative"
      data-testid={testid}
    >
      {showLabel}
      <input
        ref={inputRef}
        id={`${testid}-input`}
        type="text"
        value={value || ""}
        onChange={(e) => {
          onChange && onChange(e.target.value);
          if (!open) setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKey}
        placeholder={placeholder}
        disabled={disabled}
        autoFocus={autoFocus}
        autoComplete="off"
        className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm mt-1"
        style={{
          backgroundColor: colors.surface,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid={`${testid}-input`}
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={`${testid}-panel`}
        role="combobox"
      />
      {open && suggestions.length > 0 ? (
        <ul
          id={`${testid}-panel`}
          data-testid={`${testid}-panel`}
          className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-lg shadow-lg"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          role="listbox"
        >
          {suggestions.map((s, idx) => {
            const highlighted = idx === highlightIdx;
            return (
              <li
                key={s.id}
                data-testid={`${testid}-option-${idx}`}
                onMouseDown={(e) => {
                  // ``mousedown`` (not click) so the click-outside
                  // handler doesn't fire between mousedown and
                  // click and close the panel first.
                  e.preventDefault();
                  commit(s.title);
                }}
                onMouseEnter={() => setHighlightIdx(idx)}
                className="cursor-pointer px-3 py-2 text-sm flex items-center justify-between gap-3"
                style={{
                  backgroundColor: highlighted
                    ? colors.brandTertiary
                    : "transparent",
                  color: colors.onSurface,
                }}
                role="option"
                aria-selected={highlighted}
              >
                <span className="truncate">{s.title}</span>
                <span
                  className="text-[10px] font-semibold"
                  style={{ color: colors.muted }}
                  title="times used on this tenant"
                >
                  ×{s.usage_count}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
      {open && !loading && suggestions.length === 0 && (value || "").trim() ? (
        <div
          data-testid={`${testid}-empty`}
          className="absolute z-30 mt-1 w-full rounded-lg px-3 py-2 text-xs italic"
          style={{
            backgroundColor: colors.surface,
            color: colors.muted,
            border: `1px solid ${colors.border}`,
          }}
        >
          No matches — this title will be added when you save the job.
        </div>
      ) : null}
    </div>
  );
}
