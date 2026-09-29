/**
 * Feb-2026 · N1 · Shared page-header component.
 *
 * Contract
 * ────────
 *   <PageHeader
 *     title="Invoices"           // required — renders as <h1>
 *     actions={<Buttons/>}       // optional — right-aligned actions
 *     subtitle="Filed & Open"    // optional — small text under H1
 *     filterBar={<NavyBar/>}     // optional — filter-bar slot
 *   />
 *
 * Layout
 * ──────
 *   Row 1 · title left, actions right, inherits page background.
 *   Row 2 · optional filter-bar slot (24px horizontal insets).
 *
 * Phase GLOBAL-SEARCH-UNIFY · Feb-2026
 * ────────────────────────────────────
 * The Row-1 blue command-bar search band + grouped dropdown that
 * previously lived here have moved into
 * :js:mod:`components/GlobalSearch` and are mounted once at the
 * ``AdminTopBar`` level. Every page now invokes the unified
 * palette via the global ``⌘K`` / ``Ctrl+K`` shortcut instead of
 * a per-header inline input. The ``page-header-search-*``
 * testids the old palette exposed have moved along with it —
 * the new palette carries ``global-search-*`` testids.
 */
import React from "react";
import { colors } from "@/theme";


export function PageHeader({ title, subtitle, actions, filterBar = null }) {
  return (
    <header
      style={{ width: "100%", background: "transparent" }}
      data-testid="page-header"
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          padding: "20px 24px 20px",
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
