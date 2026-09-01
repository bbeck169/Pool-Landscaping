/**
 * Phase K2 · Feb-2026 — App-shell breadcrumb component.
 *
 * Renders the shadcn ``<Breadcrumb>`` primitive above every
 * authenticated route (mounted once in ``AppLayout``).  Skips
 * landing pages (``/``, ``/dashboard``, ``/portal/home``,
 * ``/tech/dashboard``) via ``CRUMB_SKIP``; otherwise walks the
 * ``parent`` chain in ``routeMeta.js`` to produce
 * ``Home > Section > … > Current`` links.
 *
 * Dynamic labels — the customer's display name, an invoice number,
 * the title of the portal service — resolve at render time from
 * the map published by ``useSetDynamicCrumb`` in the owning page.
 * While the entity is still loading the crumb renders the
 * "..." skeleton so the placeholder ``Customer`` never flashes
 * before the real name.
 *
 * ``variant`` toggles the light (admin) vs. dark (portal) styling
 * so the same component reads naturally on both surfaces.
 */
import React, { useMemo } from "react";
import { Link, useLocation } from "react-router-dom";

import {
  Breadcrumb, BreadcrumbList, BreadcrumbItem,
  BreadcrumbLink, BreadcrumbPage, BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { buildCrumbs } from "@/components/breadcrumbs/routeMeta";
import { useDynamicCrumbLabels } from "./dynamicCrumbContext";

const VARIANT_STYLES = {
  admin: {
    bg: "#F9FAFB",
    border: "1px solid #E5E7EB",
    linkColor: "#0369A1",
    currentColor: "#0F172A",
    separatorColor: "#9CA3AF",
    skeletonBg: "#E5E7EB",
    skeletonColor: "#6B7280",
  },
  portal: {
    bg: "#0B1220",
    border: "1px solid rgba(255,255,255,0.08)",
    linkColor: "#38BDF8",
    currentColor: "#F8FAFC",
    separatorColor: "#64748B",
    skeletonBg: "rgba(255,255,255,0.10)",
    skeletonColor: "#94A3B8",
  },
};


export default function AppBreadcrumbs({ variant = "admin", className }) {
  const location = useLocation();
  const dynLabels = useDynamicCrumbLabels();

  const crumbs = useMemo(
    () => buildCrumbs(location.pathname, dynLabels),
    [location.pathname, dynLabels],
  );

  if (!crumbs.length) return null;

  const styles = VARIANT_STYLES[variant] || VARIANT_STYLES.admin;

  return (
    <div
      className={`px-3 py-2 ${className || ""}`}
      style={{ background: styles.bg, borderBottom: styles.border }}
      data-testid="app-breadcrumbs"
      data-variant={variant}
    >
      <Breadcrumb>
        <BreadcrumbList className="text-xs">
          {crumbs.map((c, i) => {
            const isLast = i === crumbs.length - 1;
            const usesPlaceholder = Boolean(
              c.dynamic && !dynLabels[c.dynamic]
                        && !dynLabels[c.routeKey],
            );
            // Placeholder crumbs render the "..." skeleton so we
            // never leak the generic route-meta label ("Customer")
            // before the entity resolves.
            const rendered = usesPlaceholder ? (
              <span
                aria-hidden={false}
                aria-label="Loading page name"
                data-testid={`app-breadcrumbs-skeleton-${i}`}
                style={{
                  display: "inline-block",
                  minWidth: 42,
                  height: 12,
                  borderRadius: 4,
                  background: styles.skeletonBg,
                  color: styles.skeletonColor,
                  padding: "0 8px",
                  fontSize: 11,
                  lineHeight: "12px",
                }}
              >
                …
              </span>
            ) : (
              c.label
            );

            return (
              <React.Fragment key={`${c.routeKey || c.label}-${i}`}>
                <BreadcrumbItem data-testid={`app-breadcrumb-${i}`}>
                  {c.path && !isLast ? (
                    <BreadcrumbLink
                      asChild
                      style={{
                        color: styles.linkColor, fontWeight: 600,
                      }}
                    >
                      <Link to={c.path}>{rendered}</Link>
                    </BreadcrumbLink>
                  ) : (
                    <BreadcrumbPage
                      style={{
                        color: styles.currentColor,
                        fontWeight: isLast ? 700 : 500,
                      }}
                      data-testid={
                        isLast ? "app-breadcrumbs-current" : undefined}
                    >
                      {rendered}
                    </BreadcrumbPage>
                  )}
                </BreadcrumbItem>
                {i < crumbs.length - 1 ? (
                  <BreadcrumbSeparator
                    style={{ color: styles.separatorColor }}
                  />
                ) : null}
              </React.Fragment>
            );
          })}
        </BreadcrumbList>
      </Breadcrumb>
    </div>
  );
}
