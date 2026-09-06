// Feb-2026 · P35 — Customers list numbered pager.
//
// Rendering rules (matches the phase brief):
//   * ‹ Prev  — disabled at page 1.
//   * 1 2 3 … N — condensed when total_pages > 7 with an ellipsis on
//     either side of the current-page window (cur-1, cur, cur+1).
//   * Next ›  — disabled at last page.
//   * "Showing X-Y of {total}" label alongside.
//   * Jump-to-page numeric input (Enter navigates).
//
// The component renders nothing when total_pages < 2 so the top +
// bottom pager mounts self-hide on the 1-page case.
//
// Phase K62 · Feb-2026 — adds "« First" + "Last »" bookends and a
// 25 / 50 / 100 page-size selector. When ``pageSizeOptions`` +
// ``onPageSizeChange`` are supplied, the selector renders even
// when ``total_pages < 2`` (so a small result set can still be
// resized without a full-page reload). When those props are
// omitted, the component keeps its historical "hide on 1 page"
// behaviour for legacy callers.

import React, { useState, useCallback } from "react";
import { colors } from "@/theme";


// Compute the compact number strip:
//   total_pages <= 7 → [1..N]
//   otherwise       → [1, 2, "…", cur-1, cur, cur+1, "…", N-1, N]
// The window naturally collapses (no duplicates) when ``cur`` is
// near either edge.
function _pageStrip(page, total_pages) {
  if (total_pages <= 7) {
    const out = [];
    for (let i = 1; i <= total_pages; i++) out.push(i);
    return out;
  }
  const set = new Set([1, 2, page - 1, page, page + 1,
                          total_pages - 1, total_pages]);
  const sorted = Array.from(set)
    .filter((n) => n >= 1 && n <= total_pages)
    .sort((a, b) => a - b);
  const out = [];
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) out.push("ellipsis");
    out.push(sorted[i]);
  }
  return out;
}


export default function CustomersPager({
  page, total_pages, total, page_size, onPageChange,
  // Phase K62 · Feb-2026 — optional size selector. Absent =
  // legacy behaviour.
  pageSizeOptions,
  onPageSizeChange,
  testidPrefix = "customers-pager",
}) {
  const [jumpValue, setJumpValue] = useState("");

  const go = useCallback((next) => {
    if (!Number.isFinite(next)) return;
    if (next < 1 || next > total_pages) return;
    if (next === page) return;
    onPageChange(next);
  }, [page, total_pages, onPageChange]);

  const onJumpSubmit = useCallback((e) => {
    e.preventDefault();
    const n = parseInt(jumpValue, 10);
    if (!Number.isFinite(n)) return;
    setJumpValue("");
    go(n);
  }, [jumpValue, go]);

  const _showSizeSelector = Array.isArray(pageSizeOptions)
    && typeof onPageSizeChange === "function";
  // K62 · Feb-2026 — with the size selector wired, we still want
  // the operator to be able to switch sizes even when there's
  // only one page today. Render a minimal size-selector-only bar
  // in that case instead of returning null.
  const _multiPage = total_pages && total_pages >= 2;
  if (!_multiPage && !_showSizeSelector) return null;

  const from = _multiPage ? (page - 1) * page_size + 1 : Math.min(1, total);
  const to = _multiPage
    ? Math.min(page * page_size, total)
    : total || 0;
  const strip = _multiPage ? _pageStrip(page, total_pages) : [];

  const _btnBase = {
    minWidth: 32,
    height: 32,
    padding: "0 8px",
    borderRadius: 8,
    fontSize: 12,
    fontWeight: 600,
    cursor: "pointer",
  };

  const _sizeSelector = _showSizeSelector ? (
    <label
      className="flex items-center gap-1 ml-2 text-xs"
      style={{ color: colors.onSurfaceSecondary }}
      data-testid={`${testidPrefix}-size-selector-label`}
    >
      <span>Rows</span>
      <select
        value={page_size}
        onChange={(e) => {
          const next = parseInt(e.target.value, 10);
          if (Number.isFinite(next)) onPageSizeChange(next);
        }}
        data-testid={`${testidPrefix}-size-selector`}
        aria-label="Rows per page"
        style={{
          height: 32,
          padding: "0 8px",
          borderRadius: 8,
          fontSize: 12,
          fontWeight: 600,
          backgroundColor: colors.surface,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
      >
        {pageSizeOptions.map((n) => (
          <option key={n} value={n} data-testid={`${testidPrefix}-size-option-${n}`}>
            {n}
          </option>
        ))}
      </select>
    </label>
  ) : null;

  return (
    <div
      data-testid={testidPrefix}
      className="flex flex-wrap items-center gap-2 justify-between px-3 py-2 border-t border-b"
      style={{
        backgroundColor: colors.surfaceSecondary,
        borderColor: colors.border,
      }}
    >
      <span
        className="text-xs"
        style={{ color: colors.onSurfaceSecondary }}
        data-testid={`${testidPrefix}-showing-label`}
      >
        {total > 0 ? (
          <>
            Showing {from.toLocaleString()}-{to.toLocaleString()} of{" "}
            {total.toLocaleString()}
          </>
        ) : (
          <>0 customers</>
        )}
      </span>

      <div className="flex flex-wrap items-center gap-1">
        {_multiPage ? (
          <>
            {/* K62 · Feb-2026 — First / Last bookends around the
                existing Prev / strip / Next controls. */}
            <button
              type="button"
              onClick={() => go(1)}
              disabled={page <= 1}
              data-testid={`${testidPrefix}-first`}
              aria-label="First page"
              style={{
                ..._btnBase,
                backgroundColor: colors.surface,
                color: page <= 1 ? colors.muted : colors.onSurface,
                border: `1px solid ${colors.border}`,
                opacity: page <= 1 ? 0.5 : 1,
                cursor: page <= 1 ? "not-allowed" : "pointer",
              }}
            >
              « First
            </button>
            <button
              type="button"
              onClick={() => go(page - 1)}
              disabled={page <= 1}
              data-testid={`${testidPrefix}-prev`}
              style={{
                ..._btnBase,
                backgroundColor: colors.surface,
                color: page <= 1 ? colors.muted : colors.onSurface,
                border: `1px solid ${colors.border}`,
                opacity: page <= 1 ? 0.5 : 1,
                cursor: page <= 1 ? "not-allowed" : "pointer",
              }}
            >
              ‹ Prev
            </button>

            {strip.map((entry, idx) => {
              if (entry === "ellipsis") {
                return (
                  <span
                    key={`ellipsis-${idx}`}
                    data-testid={`${testidPrefix}-ellipsis-${idx}`}
                    className="px-1 text-xs"
                    style={{ color: colors.muted }}
                  >
                    …
                  </span>
                );
              }
              const active = entry === page;
              return (
                <button
                  key={entry}
                  type="button"
                  onClick={() => go(entry)}
                  data-testid={`${testidPrefix}-page-${entry}`}
                  aria-current={active ? "page" : undefined}
                  style={{
                    ..._btnBase,
                    backgroundColor: active ? colors.brandTertiary : colors.surface,
                    color: active ? colors.onBrandTertiary : colors.onSurface,
                    border: `1px solid ${active ? colors.brandTertiary : colors.border}`,
                  }}
                >
                  {entry}
                </button>
              );
            })}

            <button
              type="button"
              onClick={() => go(page + 1)}
              disabled={page >= total_pages}
              data-testid={`${testidPrefix}-next`}
              style={{
                ..._btnBase,
                backgroundColor: colors.surface,
                color: page >= total_pages ? colors.muted : colors.onSurface,
                border: `1px solid ${colors.border}`,
                opacity: page >= total_pages ? 0.5 : 1,
                cursor: page >= total_pages ? "not-allowed" : "pointer",
              }}
            >
              Next ›
            </button>
            <button
              type="button"
              onClick={() => go(total_pages)}
              disabled={page >= total_pages}
              data-testid={`${testidPrefix}-last`}
              aria-label="Last page"
              style={{
                ..._btnBase,
                backgroundColor: colors.surface,
                color: page >= total_pages ? colors.muted : colors.onSurface,
                border: `1px solid ${colors.border}`,
                opacity: page >= total_pages ? 0.5 : 1,
                cursor: page >= total_pages ? "not-allowed" : "pointer",
              }}
            >
              Last »
            </button>

            <form onSubmit={onJumpSubmit} className="flex items-center gap-1 ml-2">
              <label
                className="text-xs"
                style={{ color: colors.muted }}
                htmlFor={`${testidPrefix}-jump-input`}
              >
                Jump
              </label>
              <input
                id={`${testidPrefix}-jump-input`}
                type="number"
                min={1}
                max={total_pages}
                value={jumpValue}
                onChange={(e) => setJumpValue(e.target.value)}
                data-testid={`${testidPrefix}-jump-input`}
                className="w-16 px-2 py-1 rounded text-xs"
                style={{
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
              />
            </form>
          </>
        ) : null}

        {_sizeSelector}
      </div>
    </div>
  );
}
