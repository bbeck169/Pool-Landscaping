/**
 * Feb-2026 · K56 — Frontend feature-flag registry.
 *
 * Single source of truth for tenant-agnostic client-side feature
 * gates.  Import as:
 *
 *     import { FEATURE_FLAGS, isFeatureEnabled } from "@/config/featureFlags";
 *     if (isFeatureEnabled("FEATURE_STOCK_SEARCH")) { ... }
 *
 * Flags are compile-time constants for now (no runtime override
 * surface).  When a future ticket wires a tenant-level flag store,
 * `isFeatureEnabled` is the single call site to teach about it.
 *
 * Feb-2026 · K56 — Stock search + background removal were surfaced
 * behind the SuperCool integration which was retired in K55.b.  The
 * Emergent-only image provider does NOT support these operations
 * (see `services/media_provider.py::EmergentFallbackProvider`).  Both
 * flags default OFF and gate any UI that would call
 * `/api/media/image/search` or `/api/media/image/remove-background`.
 */

// K56.1: flip on when Unsplash/remove.bg backends are wired.
export const FEATURE_FLAGS = Object.freeze({
  FEATURE_STOCK_SEARCH: false,
  FEATURE_REMOVE_BG: false,
});

export function isFeatureEnabled(flagName) {
  return Boolean(FEATURE_FLAGS[flagName]);
}
