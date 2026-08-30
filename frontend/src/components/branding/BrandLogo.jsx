/**
 * BrandLogo — Feb-2026 UI Polish Addendum
 *
 * Responsive brand mark for the app shell (top-nav + mobile header +
 * left-rail crown). Multi-tenant aware:
 *
 *   1. Prefer `tenant.branding.logo_url` (new shape, set by future
 *      admin branding UI — see TD-08 in /app/memory/TECH_DEBT.md).
 *   2. Fall back to `tenant.logo_url` (legacy shape already accepted
 *      by PATCH /api/tenants/mine/brand).
 *   3. Fall back to the local placeholder shipped in this repo:
 *      /brand/logo.png (full wordmark) or /brand/logo-icon.png (icon).
 *
 * The wrapping <Link to="/"> matches the spec — clicking the logo
 * from anywhere in the app returns to the role-appropriate dashboard
 * (the "/" route resolves via App.js role gates).
 *
 * PLACEHOLDER — swap `/app/frontend/public/brand/logo.png` and
 * `/app/frontend/public/brand/logo-icon.png` with the real brand
 * asset when it lands. No code change required.
 */
import React from "react";
import { Link } from "react-router-dom";
import useTenantBrand from "@/hooks/useTenantBrand";

const LOCAL_FULL = "/brand/logo.png";
const LOCAL_ICON = "/brand/logo-icon.png";

export function BrandLogo({
  variant = "full",
  className = "",
  height,
  alt,
  linkTo = "/",
  testId,
}) {
  const brand = useTenantBrand();
  const tenantLogo = brand?.logo_url || null;

  // Icon variant renders the square mark; full variant renders the
  // horizontal wordmark. Both fall back to the local placeholder
  // when the tenant hasn't uploaded anything yet.
  const src = tenantLogo || (variant === "icon" ? LOCAL_ICON : LOCAL_FULL);
  const finalAlt = alt || brand?.name || "Pool & Landscaping";

  // Responsive defaults — callers can override via `height` prop or
  // additional `className` utilities.
  const sizeCls = height
    ? ""
    : variant === "icon"
      ? "h-8 w-8"
      : "h-8 sm:h-9 md:h-10";

  const img = (
    <img
      src={src}
      alt={finalAlt}
      className={`object-contain select-none pointer-events-none ${sizeCls} ${className}`.trim()}
      style={height ? { height, width: variant === "icon" ? height : undefined } : undefined}
      data-testid={testId ? `${testId}-img` : "brand-logo-img"}
      draggable={false}
      // Fallback to placeholder if a tenant-supplied URL 404s. Keeps
      // the shell from rendering a broken-image icon in the header.
      onError={(e) => {
        if (e?.currentTarget && e.currentTarget.src.indexOf(LOCAL_FULL) === -1
            && e.currentTarget.src.indexOf(LOCAL_ICON) === -1) {
          e.currentTarget.src = variant === "icon" ? LOCAL_ICON : LOCAL_FULL;
        }
      }}
    />
  );

  return (
    <Link
      to={linkTo}
      aria-label={`${finalAlt} — go to dashboard`}
      className={
        "inline-flex items-center rounded-md focus:outline-none " +
        "focus-visible:ring-2 focus-visible:ring-sky-500 " +
        "transition-transform duration-200 ease-out will-change-transform " +
        "hover:scale-[1.02] focus-visible:scale-[1.02]"
      }
      data-testid={testId || "brand-logo-link"}
    >
      {img}
    </Link>
  );
}

export default BrandLogo;
