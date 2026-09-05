/**
 * Phase K56 · Feb-2026 — feature-flag registry regression.
 *
 * Guards: `FEATURE_STOCK_SEARCH` and `FEATURE_REMOVE_BG` are BOTH
 * off by default so no client-side UI accidentally calls
 * `/api/media/image/search` or `/api/media/image/remove-background`
 * — both of which the Emergent-only provider does not support
 * (see `services/media_provider.py::EmergentFallbackProvider`).
 */
import { describe, it, expect } from "vitest";
import { FEATURE_FLAGS, isFeatureEnabled } from "@/config/featureFlags";

describe("K56 · frontend feature-flag registry", () => {
  it("FEATURE_STOCK_SEARCH defaults OFF", () => {
    expect(FEATURE_FLAGS.FEATURE_STOCK_SEARCH).toBe(false);
    expect(isFeatureEnabled("FEATURE_STOCK_SEARCH")).toBe(false);
  });

  it("FEATURE_REMOVE_BG defaults OFF", () => {
    expect(FEATURE_FLAGS.FEATURE_REMOVE_BG).toBe(false);
    expect(isFeatureEnabled("FEATURE_REMOVE_BG")).toBe(false);
  });

  it("isFeatureEnabled returns false for unknown flag", () => {
    expect(isFeatureEnabled("FEATURE_THAT_DOES_NOT_EXIST")).toBe(false);
  });

  it("FEATURE_FLAGS object is frozen so callers cannot mutate", () => {
    expect(Object.isFrozen(FEATURE_FLAGS)).toBe(true);
  });
});
