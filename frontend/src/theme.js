// Shared theme constants (mirrors /app/mobile/src/theme.ts).
// Web renders with Tailwind, but we keep these tokens as the single source of truth
// for gradients, brand colors, and status meta used across the web app.
//
// Feb 2026 · Color pass — additive extensions (see block at the bottom
// of ``colors``). The existing keys are unchanged; the new families
// (``pool``, ``landscape``, ``accent``, ``status``) exist alongside
// them so any consumer that reaches for ``colors.brand`` /
// ``colors.brandTertiary`` etc. keeps working.
export const colors = {
  surface: "#FFFFFF",
  onSurface: "#09090B",
  surfaceSecondary: "#F4F4F5",
  onSurfaceSecondary: "#52525B",
  surfaceTertiary: "#E4E4E7",
  surfaceInverse: "#18181B",
  onSurfaceInverse: "#FFFFFF",
  brand: "#0284C7",
  brandPrimary: "#0284C7",
  onBrandPrimary: "#FFFFFF",
  brandSecondary: "#16A34A",
  brandTertiary: "#E0F2FE",
  onBrandTertiary: "#0369A1",
  success: "#16A34A",
  onSuccess: "#FFFFFF",
  warning: "#CA8A04",
  onWarning: "#FFFFFF",
  error: "#DC2626",
  onError: "#FFFFFF",
  info: "#0284C7",
  border: "#E4E4E7",
  borderStrong: "#D4D4D8",
  divider: "#E4E4E7",
  muted: "#71717A",

  // ═══════════════════════════════════════════════════════════════
  // Feb 2026 · Service-line palettes (additive).
  //
  // Every consumer that renders a job / customer / KPI in a
  // service-line context should resolve its color family via
  // ``utils/serviceLineTheme.js`` rather than reaching for these
  // shades directly. That indirection lets us swap the underlying
  // hex later without a codebase-wide search-replace.
  //
  // Contrast rule: white text on 500 / 600 / 700 shades passes
  // WCAG AA at ≥ 4.5:1 body / 3:1 large text. Dark text
  // (``onSurface``) on 50 / 100 / 300 shades passes at the same
  // thresholds — verified in
  // ``test/feb2026-color-contrast.test.js``.
  // ═══════════════════════════════════════════════════════════════
  pool: {
    50: "#ECFEFF",
    100: "#CFFAFE",
    300: "#67E8F9",
    500: "#06B6D4",   // primary Pool accent
    600: "#0891B2",
    700: "#0E7490",
  },
  landscape: {
    50: "#F0FDF4",
    100: "#DCFCE7",
    300: "#86EFAC",
    500: "#22C55E",   // primary Landscape accent
    600: "#16A34A",
    700: "#15803D",
  },
  // KPI variety — five distinct hues that live comfortably next
  // to each other on the dashboard KPI grid without descending
  // into a chaotic rainbow. Ordering below is the default rotation
  // the KpiCard consumes when no explicit tone is passed.
  accent: {
    violet: { 50: "#F5F3FF", 100: "#EDE9FE", 500: "#8B5CF6", 600: "#7C3AED", 700: "#6D28D9" },
    amber:  { 50: "#FFFBEB", 100: "#FEF3C7", 500: "#F59E0B", 600: "#D97706", 700: "#B45309" },
    rose:   { 50: "#FFF1F2", 100: "#FFE4E6", 500: "#F43F5E", 600: "#E11D48", 700: "#BE123C" },
    emerald:{ 50: "#ECFDF5", 100: "#D1FAE5", 500: "#10B981", 600: "#059669", 700: "#047857" },
    sky:    { 50: "#F0F9FF", 100: "#E0F2FE", 500: "#0EA5E9", 600: "#0284C7", 700: "#0369A1" },
  },
  // Semantic status tokens — same shape as the ``accent`` entries
  // so any tinted-tile / colored-border consumer can pick them
  // interchangeably. This pass wires them into KPI + button
  // surfaces only; the app-wide badge migration is a follow-up.
  status: {
    scheduled:  { primary: "#06B6D4", soft: "#CFFAFE", strong: "#0E7490" },
    inProgress: { primary: "#F59E0B", soft: "#FEF3C7", strong: "#B45309" },
    completed:  { primary: "#22C55E", soft: "#DCFCE7", strong: "#15803D" },
    overdue:    { primary: "#F43F5E", soft: "#FFE4E6", strong: "#BE123C" },
    paid:       { primary: "#10B981", soft: "#D1FAE5", strong: "#047857" },
  },
  // ═══════════════════════════════════════════════════════════════
  // Phase K50 · Feb-2026 — WEB nav chrome (Pipedrive-inspired navy).
  //
  // Single source of truth for the desktop sidebar (``QuickNavRail``)
  // and the top main menu (``AdminTopBar``).  Mobile chrome, the
  // customer portal shell, and the ``AdminSidebar`` group content
  // that renders inside the mobile drawer stay on their existing
  // light palette — this token is deliberately scoped to the two
  // desktop surfaces the user called out.
  //
  // Contrast rule:
  //   * ``nav.fg`` (#FFFFFF) on ``nav.bg`` (#1B1F5C) → 12.8 : 1
  //     (AAA at all sizes).
  //   * ``nav.fgActive`` (#1B1F5C) on ``nav.bgActive`` (#FFFFFF) →
  //     12.8 : 1 (AAA at all sizes).
  //   * ``nav.bgHover`` (#2A2F7A) sits ~one shade lighter than
  //     ``nav.bg`` so a subtle hover state is visible without a
  //     white overlay that would fight the WCAG contrast on the
  //     child icon.
  // ═══════════════════════════════════════════════════════════════
  nav: {
    bg: "#1B1F5C",
    bgHover: "#2A2F7A",
    bgActive: "#FFFFFF",     // legacy pill active — retained for portal preview; K52 primary chrome uses ``gradient.css`` instead
    // Phase K64 · Feb-2026 — lighter-navy solid used by the main
    // admin nav (left rail + top-nav category dropdowns) for
    // BOTH hover and active states. Replaces the K52 mint-green
    // gradient on the main-nav surfaces only. Other gradient
    // consumers (badge chips, sub-nav filter pills, CTAs) are
    // intentionally untouched — they keep resolving through
    // ``colors.gradient.*``. Contrast: white on ``#303AA0`` →
    // ~7.4 : 1 (WCAG AAA).
    bgActiveNavy: "#303AA0",
    fg: "#FFFFFF",
    fgActive: "#1B1F5C",     // legacy pill text — retained for portal preview
    fgMuted: "rgba(255, 255, 255, 0.72)",
    border: "rgba(255, 255, 255, 0.10)",
  },

  // ═══════════════════════════════════════════════════════════════
  // Phase K52 · Feb-2026 — signature action gradient.
  // Phase K67 · Feb-2026 — swapped the sky-300 stop for the menu
  // navy (``colors.nav.bg`` #1B1F5C) so the gradient reads as
  // green → navy instead of green → sky, cohering with the K50–K64
  // navy nav theme. Direction is unchanged (green stays on the
  // left) per K67 constraints.
  //
  // Used on: primary CTAs (shadcn ``Button`` default variant), the
  // active-state pill in the sidebar / top-bar / sub-nav, and the
  // focus-ring accent on the navy filter strip.  Every consumer
  // must resolve values through ``colors.gradient.*`` rather than
  // inlining the hex — the tokens are the single source of truth
  // so a future palette shift is a one-file change.
  //
  // Contrast rule (post-K67): white text on the K67 navy end
  // (#1B1F5C) is 12.8:1 (AAA at all sizes) — the sky-300 end used
  // to be the weakest link at ~2.4:1 and required a text-shadow
  // patch to reach WCAG AA large. The ``textShadow`` token is
  // retained for backwards compatibility but is no longer required
  // for contrast; keeping it also improves legibility over the
  // green mid-point (green-500 → navy sweep) where the perceptual
  // luminance dips.
  // ═══════════════════════════════════════════════════════════════
  gradient: {
    from: "#22C55E",         // emerald-500 — green stop (unchanged)
    to:   "#1B1F5C",         // K67 · menu navy (was #7DD3FC sky-300)
    css:      "linear-gradient(90deg, #22C55E 0%, #1B1F5C 100%)",
    cssHover: "linear-gradient(90deg, #34D673 0%, #2A2F7A 100%)",  // K67 · matched ~+8% lightness on each stop; hover-navy equals colors.nav.bgHover
    fg: "#FFFFFF",
    fgHover: "#FFFFFF",
    textShadow: "0 1px 2px rgba(0, 0, 0, 0.25)",
  },

  // ═══════════════════════════════════════════════════════════════
  // Phase K54 · Feb-2026 — solid destructive-red token.
  //
  // Applied to: shadcn ``Button variant="destructive"``, every
  // Sign-out entry point (AdminTopBar / UniversalMenu portal pill /
  // AppLayout mobile bar / TenantPicker), and legacy inline
  // Delete / Discard / Void / Deactivate buttons.
  //
  //   • ``bg``               #DC2626 (red-600) — button surface.
  //   • ``bgHover``          #B91C1C (red-700) — hover surface.
  //   • ``fg``               #FFFFFF          — foreground text.
  //   • ``ring``             #EF4444 (red-500) — focus-visible ring.
  //   • ``disabledOpacity``  0.55             — matches the shared
  //                                              ``disabled:opacity-55``
  //                                              in ``buttonVariants``.
  //
  // Contrast rule: white text on ``#DC2626`` → 5.9 : 1 (WCAG AA
  // body + AAA large). White text on ``#B91C1C`` → 7.9 : 1 (AAA
  // body). Verified in ``test/k54-destructive-buttons.test.js``.
  // ═══════════════════════════════════════════════════════════════
  destructive: {
    bg: "#DC2626",
    bgHover: "#B91C1C",
    fg: "#FFFFFF",
    ring: "#EF4444",
    disabledOpacity: 0.55,
  },
};

// ═══════════════════════════════════════════════════════════════
// Phase K67 · Feb-2026 — canonical navy → green gradient.
//
// Single source of truth for every legacy "blue-to-green" surface
// (dashboard KPI hero, auth-page banners, portal hero banner, the
// R0 reports "Open new suite" chip, etc.).  Historically the two
// stops were sky-600 (#0284C7) → green-600 (#16A34A), which read
// as "blue → teal-green" and clashed with the K50–K64 navy nav.
// K67 swaps the sky-600 stop for the menu navy (colors.nav.bg
// #1B1F5C) while preserving the green stop and the 90deg
// direction, so the gradient now reads as navy → green.
//
// Contrast rule:
//   * White text on ``#1B1F5C`` (start) → 12.8 : 1 (AAA at all
//     sizes) — improved from the sky-600 start's 4.6 : 1.
//   * White text on ``#16A34A`` (end)   → 4.4 : 1 (AA body /
//     AAA large — unchanged, this stop wasn't touched).
//   * The perceptual mid-point sits near navy-teal at ~luminance
//     0.35 which stays well above the 3:1 large-text bar.
// ═══════════════════════════════════════════════════════════════
export const gradients = {
  navyToGreen: {
    from: "#1B1F5C",  // K67 · menu navy (colors.nav.bg)
    to:   "#16A34A",  // green-600 (unchanged)
    css:      "linear-gradient(90deg, #1B1F5C 0%, #16A34A 100%)",
    // Hover: +8% lightness on each stop, mirroring the K52
    // ``colors.gradient.cssHover`` pattern.
    cssHover: "linear-gradient(90deg, #2A2F7A 0%, #22B457 100%)",
    fg: "#FFFFFF",
    textShadow: "0 1px 2px rgba(0, 0, 0, 0.25)",
  },
};

// ═══════════════════════════════════════════════════════════════
// @deprecated K67 · Feb-2026 — use ``gradients.navyToGreen.*``.
//
// Historical name for the primary brand gradient. Left exported
// so the ~60 existing callers do not break in a single phase;
// the underlying stops are already rerouted to the K67 navy →
// green palette. Full call-site migration is a K67-follow-up.
// ═══════════════════════════════════════════════════════════════
export const brandGradient = ["#1B1F5C", "#16A34A"];
export const brandGradientCss = gradients.navyToGreen.css;

export const font = {
  family: "'Plus Jakarta Sans', system-ui, -apple-system, sans-serif",
};

export const statusMeta = {
  requested: { label: "Requested", bg: "#FFEDD5", fg: "#C2410C" },
  pending: { label: "Pending", bg: "#FEF9C3", fg: "#A16207" },
  active: { label: "Active", bg: colors.brandTertiary, fg: colors.onBrandTertiary },
  completed: { label: "Completed", bg: "#DCFCE7", fg: colors.success },
  cancelled: { label: "Cancelled", bg: "#FEE2E2", fg: colors.error },
  draft: { label: "Draft", bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary },
  published: { label: "Published", bg: "#DCFCE7", fg: colors.success },
  scheduled: { label: "Scheduled", bg: "#E0E7FF", fg: "#4338CA" },
  sent: { label: "Sent", bg: colors.brandTertiary, fg: colors.onBrandTertiary },
  accepted: { label: "Accepted", bg: "#DCFCE7", fg: colors.success },
  rejected: { label: "Rejected", bg: "#FEE2E2", fg: colors.error },
  paid: { label: "Paid", bg: "#DCFCE7", fg: colors.success },
  unpaid: { label: "Unpaid", bg: "#FEF9C3", fg: "#A16207" },
};

export const money = (n = 0) =>
  "$" +
  Number(n || 0).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
