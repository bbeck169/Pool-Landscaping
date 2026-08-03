// Phase 39 · Feb-2026 — public entry point for the Terms of Service.
//
// ``mobile/app/portal/_layout.tsx`` gates ``/portal/**`` behind an
// auth ``<Redirect href="/login" />``, which would bounce an
// un-authenticated visitor away from ``/portal/terms``. The login
// screen's ToS link therefore routes here instead — a top-level
// route (no ``portal/`` prefix, so no gate) that renders the exact
// same ``PortalTerms`` component. The component itself is auth-aware:
// the acknowledge widget is hidden when ``user`` is null, so the
// document text is still fully readable pre-login.
export { default } from "./portal/terms";
