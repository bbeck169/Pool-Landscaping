/**
 * Slice P · <Breadcrumbs> — cross-cutting hierarchy nav.
 *
 * Usage:
 *   <Breadcrumbs />                         → auto-derives from pathname
 *   <Breadcrumbs items={[...]} />           → explicit override
 *   <Breadcrumbs dynamic={{ '/jobs/:id': 'Job A1B2' }} />
 *                                            → override label for dynamic route
 *
 * Renders as <nav aria-label="Breadcrumb"><ol>. Last crumb carries
 * aria-current="page" and no link. On narrow screens, middle crumbs
 * collapse into an ellipsis button that opens a dropdown.
 */
import React, { useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ChevronRight, MoreHorizontal } from "lucide-react";
import { buildCrumbs } from "./routeMeta";

const ITEMS_MOBILE_MAX = 3;

export default function Breadcrumbs({ items, dynamic, className }) {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  const crumbs = useMemo(() => {
    if (Array.isArray(items) && items.length) return items;
    return buildCrumbs(location.pathname, dynamic || {});
  }, [items, dynamic, location.pathname]);

  if (!crumbs.length) return null;

  // Mobile collapse: on narrow screens, show first + last + optional
  // ellipsis for anything in the middle.
  const collapsed = crumbs.length > ITEMS_MOBILE_MAX;

  return (
    <nav
      aria-label="Breadcrumb"
      className={`px-3 py-2 text-xs ${className || ""}`}
      data-testid="breadcrumbs"
      style={{ borderBottom: "1px solid #E5E7EB", background: "#F9FAFB" }}
    >
      <ol className="flex items-center gap-1 flex-wrap">
        {crumbs.map((c, i) => {
          const isLast = i === crumbs.length - 1;
          const isMiddle = collapsed && i > 0 && i < crumbs.length - 1;
          const hideOnMobile = isMiddle;
          return (
            <React.Fragment key={`${c.label}-${i}`}>
              <li
                className={hideOnMobile ? "hidden sm:inline-flex items-center" : "inline-flex items-center"}
                data-testid={`breadcrumb-${i}`}
              >
                {c.path && !isLast ? (
                  <Link
                    to={c.path}
                    className="hover:underline"
                    style={{ color: "#0369A1", fontWeight: 600 }}
                  >
                    {c.label}
                  </Link>
                ) : (
                  <span
                    aria-current={isLast ? "page" : undefined}
                    style={{
                      color: isLast ? "#0F172A" : "#6B7280",
                      fontWeight: isLast ? 700 : 500,
                    }}
                  >
                    {c.label}
                  </span>
                )}
              </li>
              {i < crumbs.length - 1 ? (
                <li
                  aria-hidden="true"
                  className={hideOnMobile ? "hidden sm:inline-flex items-center" : "inline-flex items-center"}
                  style={{ color: "#9CA3AF" }}
                >
                  <ChevronRight size={12} />
                </li>
              ) : null}
            </React.Fragment>
          );
        })}
        {collapsed ? (
          <li className="inline-flex sm:hidden items-center relative">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="inline-flex items-center gap-0.5 px-1 py-0.5 rounded"
              style={{ color: "#6B7280", background: "transparent", border: 0 }}
              data-testid="breadcrumb-mobile-ellipsis"
              aria-label="Show hidden breadcrumb levels"
            >
              <MoreHorizontal size={14} />
            </button>
            {menuOpen ? (
              <div
                className="absolute top-full left-0 mt-1 rounded-md shadow-lg z-40 py-1"
                style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", minWidth: 160 }}
                data-testid="breadcrumb-mobile-menu"
                role="menu"
              >
                {crumbs.slice(1, -1).map((c, i) => (
                  <Link
                    key={i}
                    to={c.path || "#"}
                    onClick={() => setMenuOpen(false)}
                    className="block px-3 py-1.5 text-xs hover:bg-gray-50"
                    style={{ color: "#0F172A" }}
                    role="menuitem"
                  >
                    {c.label}
                  </Link>
                ))}
              </div>
            ) : null}
          </li>
        ) : null}
      </ol>
    </nav>
  );
}
