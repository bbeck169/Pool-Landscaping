// Phase 18b · Feb-2026 — Portal page shell wrapper.
//
// Propagates the Phase 3d-portal "outer white dashboard card"
// layout from PortalHome to every portal SUB-page. Pixel-identical
// classes + inline styles — grep-sourced from PortalHome.jsx (see
// the ``portal-dashboard-card`` block at lines 194-198 at ship
// time) so the two surfaces stay in visual lockstep.
//
// Structure mirrors PortalHome:
//
//   <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
//        data-testid={testid}>
//     <div className="rounded-3xl p-5 md:p-6 mb-5 shadow-lg
//                     portal-page-shell-card"
//          style={{ backgroundColor: "#FFFFFF",
//                   border: "1px solid #E5E7EB" }}
//          data-testid="portal-page-shell-card">
//       {children}
//     </div>
//   </div>
//
// The ``portal-page-shell-card`` class is a scope selector used
// by ``src/styles/portal-dark.css`` to carve the white card OUT
// of the ``.portal-dark`` text-color overrides. Same strategy as
// the pre-existing ``.portal-sign-scope`` carve-out for the
// signature capture page.
//
// EXCLUSIONS (unchanged, do NOT wrap):
//   * ``/portal/login``             — Login variant="customer"
//   * ``/portal/home``               — already carries its own
//                                      portal-dashboard-card
//   * ``/portal/sign/:token``        — PortalSign full-bleed
//                                      signature canvas
//   * ``/portal/review/submit``      — token-authed landing
//   * ``/portal/add-card``,
//     ``/portal/setup-success``,
//     ``/portal/setup-cancelled``    — public / token-only flows
//
import React from "react";


export default function PortalPageShell({
  children,
  testid = "portal-page-shell",
  className = "",
}) {
  return (
    <div
      className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
      data-testid={testid}
    >
      <div
        className={
          "rounded-3xl p-5 md:p-6 mb-5 shadow-lg portal-page-shell-card " +
          className
        }
        style={{ backgroundColor: "#FFFFFF", border: "1px solid #E5E7EB" }}
        data-testid="portal-page-shell-card"
      >
        {children}
      </div>
    </div>
  );
}
