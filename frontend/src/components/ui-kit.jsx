import React from "react";
import { colors } from "@/theme";

// Compact chip used for tags, status pills, small filters.
export function Chip({ label, tone = "neutral", onClose, testid }) {
  const palette = {
    neutral: { bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary },
    brand: { bg: colors.brandTertiary, fg: colors.onBrandTertiary },
    success: { bg: "#DCFCE7", fg: colors.success },
    warning: { bg: "#FEF9C3", fg: "#A16207" },
    danger: { bg: "#FEE2E2", fg: colors.error },
    gold: { bg: "#FEF3C7", fg: "#B45309" },
    purple: { bg: "#EDE9FE", fg: "#6D28D9" },
  }[tone] || { bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary };
  return (
    <span
      className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full"
      style={{ backgroundColor: palette.bg, color: palette.fg }}
      data-testid={testid}
    >
      {label}
      {onClose ? (
        <button
          type="button"
          onClick={onClose}
          className="ml-0.5 opacity-70 hover:opacity-100"
          style={{ color: palette.fg }}
        >
          ×
        </button>
      ) : null}
    </span>
  );
}

export function TagChip({ tag, onRemove, testid }) {
  const tone = tag === "VIP" ? "gold" : tag === "Specialty" ? "purple" : "brand";
  return <Chip label={tag} tone={tone} onClose={onRemove} testid={testid} />;
}

export function StatusPill({ status }) {
  const meta = {
    requested: { bg: "#FFEDD5", fg: "#C2410C", label: "Requested" },
    pending: { bg: "#FEF9C3", fg: "#A16207", label: "Pending" },
    scheduled: { bg: "#E0E7FF", fg: "#4338CA", label: "Scheduled" },
    active: { bg: colors.brandTertiary, fg: colors.onBrandTertiary, label: "Active" },
    completed: { bg: "#DCFCE7", fg: colors.success, label: "Completed" },
    reopened: { bg: "#FFEDD5", fg: "#C2410C", label: "Reopened" },
    cancelled: { bg: "#FEE2E2", fg: colors.error, label: "Cancelled" },
    // Feb-2026 · Phase 1 — Could-Not-Service outcome. Amber palette
    // to distinguish from ``skipped`` (gray fallback) and
    // ``cancelled`` (red). Reportable as its own bucket.
    could_not_service: { bg: "#FEF3C7", fg: "#B45309", label: "Could Not Service" },
    skipped: { bg: "#E5E7EB", fg: "#6B7280", label: "Skipped" },
  }[status] || { bg: colors.surfaceTertiary, fg: colors.muted, label: status || "—" };
  return (
    <span
      className="text-xs font-semibold px-2.5 py-1 rounded-full whitespace-nowrap"
      style={{ backgroundColor: meta.bg, color: meta.fg }}
      data-testid={`status-pill-${status}`}
    >
      {meta.label}
    </span>
  );
}

export function Skeleton({ className = "", style = {} }) {
  return (
    <div
      className={`animate-pulse rounded-xl ${className}`}
      style={{ backgroundColor: colors.surfaceTertiary, ...style }}
    />
  );
}

export function EmptyState({ icon: Icon, title, hint, action }) {
  return (
    <div
      className="rounded-2xl p-10 text-center"
      style={{
        backgroundColor: colors.surface,
        border: `1px dashed ${colors.borderStrong}`,
      }}
      data-testid="empty-state"
    >
      {Icon ? (
        <div
          className="w-12 h-12 rounded-2xl mx-auto flex items-center justify-center mb-3"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}
        >
          <Icon size={22} />
        </div>
      ) : null}
      <div className="text-base font-semibold" style={{ color: colors.onSurface }}>
        {title}
      </div>
      {hint ? (
        <div className="text-sm mt-1" style={{ color: colors.muted }}>
          {hint}
        </div>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function PageHeader({ title, subtitle, right }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 mb-6">
      <div>
        <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
          {title}
        </h1>
        {subtitle ? (
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            {subtitle}
          </p>
        ) : null}
      </div>
      {right ? <div className="flex items-center gap-2">{right}</div> : null}
    </div>
  );
}

export function TextInput({ label, id, testid, wrapperClass = "", ...rest }) {
  return (
    <div className={wrapperClass}>
      {label ? (
        <label
          htmlFor={id}
          className="text-xs font-semibold tracking-wide mb-1 block"
          style={{ color: colors.onSurfaceSecondary }}
        >
          {label}
        </label>
      ) : null}
      <input
        id={id}
        {...rest}
        className={`w-full px-3.5 py-2.5 rounded-lg outline-none focus:ring-2 text-sm ${rest.className || ""}`}
        style={{
          backgroundColor: colors.surface,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid={testid}
      />
    </div>
  );
}

export function Button({ children, variant = "primary", tone, className = "", testid, ...rest }) {
  // Feb 2026 · Color pass — the ``tone`` prop lets a caller
  // route the primary CTA into a service-line palette
  // (``"pool"`` = cyan, ``"landscape"`` = green) or a direct
  // accent (``"violet"``, ``"amber"``, ``"sky"``, ``"emerald"``,
  // ``"rose"``). No tone → the existing brand gradient stays —
  // keeps every historical caller pixel-identical.
  //
  // Hover behaviour: the primary variant already relies on
  // ``hover:brightness-95``, which darkens the whole surface one
  // step. That matches the "500 → 600 on hover" contract the
  // color-pass spec calls for without needing a Framer-Motion
  // dance.  For solid-color tones we bump to the ``600`` shade
  // via a straight fill so the visual step is more obvious than
  // ``brightness(95%)`` alone.
  let toneBg = null;
  let toneOnBg = "#fff";
  if (tone && variant === "primary") {
    const map = colors.accent[String(tone).toLowerCase()];
    if (map) {
      toneBg = map[600];  // 600 = default rest state, brightness-95
                          // gets us visually into 700 on hover
    } else if (tone === "pool") {
      toneBg = colors.pool[600];
    } else if (tone === "landscape" || tone === "landscaping") {
      toneBg = colors.landscape[600];
    } else if (tone === "solid") {
      // "solid" retains the brand hue but drops the gradient for a
      // flatter, more vibrant primary.
      toneBg = colors.brand;
    }
  }

  const variants = {
    primary: toneBg
      ? { background: toneBg, color: toneOnBg }
      : {
          background:
            "linear-gradient(90deg, #0284C7 0%, #16A34A 100%)",
          color: "#fff",
        },
    ghost: {
      background: colors.surfaceSecondary,
      color: colors.onSurface,
      border: `1px solid ${colors.border}`,
    },
    outline: {
      background: colors.surface,
      color: toneBg || colors.brand,
      border: `1px solid ${toneBg || colors.brand}`,
    },
    danger: {
      background: "#FEE2E2",
      color: colors.error,
      border: `1px solid #FCA5A5`,
    },
  };
  const s = variants[variant] || variants.primary;
  return (
    <button
      {...rest}
      className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition active:scale-[0.99] hover:brightness-95 disabled:opacity-60 ${className}`}
      style={s}
      data-testid={testid}
      data-tone={tone || variant}
    >
      {children}
    </button>
  );
}

export function Modal({ open, onClose, title, children, footer, testid, wide }) {
  if (!open) return null;
  // Feb-2026 · optional ``wide`` variant — lifts the modal max-width
  // from ``max-w-lg`` (28rem) to ``max-w-3xl`` (48rem) so long forms
  // like the "+ New Scheduled Job" surface don't cramp on desktop.
  const maxW = wide ? "max-w-3xl" : "max-w-lg";
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ backgroundColor: "rgba(0,0,0,0.45)" }}
      onClick={onClose}
      data-testid={testid || "modal"}
    >
      <div
        className={`w-full ${maxW} rounded-2xl overflow-hidden shadow-2xl`}
        style={{ backgroundColor: colors.surface }}
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="px-5 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="text-base font-bold" style={{ color: colors.onSurface }}>
            {title}
          </div>
          <button
            onClick={onClose}
            className="text-xl leading-none px-1"
            style={{ color: colors.muted }}
            data-testid="modal-close"
          >
            ×
          </button>
        </header>
        <div className="px-5 py-4 max-h-[70vh] overflow-y-auto">{children}</div>
        {footer ? (
          <footer
            className="px-5 py-3 flex justify-end gap-2"
            style={{
              borderTop: `1px solid ${colors.border}`,
              backgroundColor: colors.surfaceSecondary,
            }}
          >
            {footer}
          </footer>
        ) : null}
      </div>
    </div>
  );
}

export function Toast({ toast, onClose }) {
  if (!toast) return null;
  const tone = toast.tone || "success";
  const styles = {
    success: { bg: colors.success, fg: "#fff" },
    error: { bg: colors.error, fg: "#fff" },
    info: { bg: colors.brand, fg: "#fff" },
  }[tone];
  return (
    <div
      className="fixed bottom-6 right-6 z-50 rounded-xl px-4 py-3 shadow-lg text-sm font-semibold"
      style={{ backgroundColor: styles.bg, color: styles.fg }}
      data-testid="toast"
      onClick={onClose}
    >
      {toast.message}
    </div>
  );
}
