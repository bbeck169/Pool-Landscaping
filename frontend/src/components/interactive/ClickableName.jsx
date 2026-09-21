/**
 * Phase P14 · Feb-2026 · Item 5 — ClickableName.
 *
 * Wraps an entity name in a ``<Link>`` to its canonical detail
 * route. Routes were audited against ``App.js`` at build time:
 *
 *   * ``customer``   → ``/customers/${id}``     (line 845)
 *   * ``technician`` → ``/technician/${id}``    (line 1340, singular)
 *   * ``user``       → no route today — degrade to plain <span>.
 *
 * Props: ``{ id, name, entityType, className, testid, onClick }``.
 *
 * Guarantees:
 *   * Empty / missing ``id`` OR ``name`` → plain <span> (no
 *     ``<Link>``), matching the "row-navigation not hijacked"
 *     acceptance point when placed inside a clickable row.
 *   * Applies the standard ``hover:underline text-blue-600`` pair
 *     for consistency across the app (no bespoke link palette).
 */
import React from "react";
import { Link } from "react-router-dom";


const _ROUTE_PREFIX = {
  customer:   "/customers",
  technician: "/technician",         // NB. singular per App.js route.
  user:       null,                  // No route today.
};


export function ClickableName({
  id, name, entityType,
  className = "",
  testid,
  onClick,
}) {
  const label = (name == null ? "" : String(name)).trim();
  const prefix = _ROUTE_PREFIX[entityType] ?? null;

  // Degrade to plain text when we don't have a valid target.
  if (!id || !label || !prefix) {
    return (
      <span
        className={className}
        data-testid={testid}
      >
        {label}
      </span>
    );
  }
  return (
    <Link
      to={`${prefix}/${id}`}
      className={`${className} hover:underline text-blue-600`.trim()}
      data-testid={testid}
      onClick={onClick}
    >
      {label}
    </Link>
  );
}


export default ClickableName;
