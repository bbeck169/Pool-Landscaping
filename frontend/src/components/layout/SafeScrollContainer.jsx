import React from "react";

/**
 * Feb-2026 · Scroll-trap prevention convention.
 *
 * Semantic wrapper for page-level content that GUARANTEES the outer
 * container never traps document scroll.
 *
 * Why this exists
 * ---------------
 * Two independent regressions in this codebase — DispatchBoard and
 * CalendarSchedule — both stemmed from a page-level container carrying
 * ``overflow: hidden`` / ``max-height`` / ``h-screen`` styles that
 * intercepted wheel events and made the whole document feel "frozen"
 * to end users. Internal scroll on sub-components (RBC time-grid,
 * long lists inside cards) is fine; the OUTER page must scroll
 * naturally as a normal document.
 *
 * The wrapper enforces the convention:
 *  * ``min-h-screen``  — the shell fills the viewport when content is short.
 *  * ``w-full``        — no horizontal clamping.
 *  * ``pb-24``         — bottom breathing room so the last card isn't
 *                        jammed against the viewport bottom.
 *  * NO ``overflow-*``, NO ``h-screen`` (only ``min-h-screen``), NO
 *    ``max-h-*``.
 *
 * Any classes the caller passes via ``className`` are appended AFTER
 * the defaults so callers can add padding / spacing / grid layout
 * decisions without accidentally removing the guarantees.
 *
 * Usage
 * -----
 *   <SafeScrollContainer className="p-4 md:p-6 space-y-4"
 *                          data-testid="my-page">
 *     ...page content...
 *   </SafeScrollContainer>
 *
 * The vitest helper ``src/test/helpers/assertNoScrollTrap.js`` pins the
 * guarantees on every page that adopts the wrapper.
 */
export default function SafeScrollContainer({
  as: Tag = "div",
  className = "",
  children,
  ...rest
}) {
  // Base classes — MUST NOT include any scroll-trapping token.
  const base = "min-h-screen w-full pb-24";
  return (
    <Tag className={`${base} ${className}`.trim()} {...rest}>
      {children}
    </Tag>
  );
}
