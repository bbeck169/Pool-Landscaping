/**
 * Mobile feature flags.
 *
 * Mirrors frontend/src/config/featureFlags.js.
 * Positive polarity: SHOW_* = false hides the feature.
 */
export const FEATURE_FLAGS = Object.freeze({
  SHOW_CHECKLIST_CHEMICAL_READINGS: false,
} as const);
