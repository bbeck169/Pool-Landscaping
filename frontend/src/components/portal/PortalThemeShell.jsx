// DTP-1 · Feb-2026 — Portal theme shell.
//
// Wraps a subtree with the ``.dark portal-dark`` scoped class
// pair so:
//   * shadcn CSS variables (--background, --card, --primary, …)
//     flip to the portal dark palette
//     (see ``@/styles/portal-dark.css``).
//   * A handful of Tailwind atomics used by pilot pages
//     (bg-white, bg-slate-50, text-slate-500…) get overridden
//     inside the scope.
//
// The shell renders nothing else — no header, no chrome, no
// side-effects. It's a pure CSS-scope container and lives at
// ``AppLayout``'s portal outlet-wrapper level so every
// ``/portal/*`` route lands inside the dark scope automatically.
import React from "react";

export default function PortalThemeShell({ children }) {
  return (
    <div
      className="dark portal-dark"
      data-testid="portal-theme-shell"
    >
      {children}
    </div>
  );
}
