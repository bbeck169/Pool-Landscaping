/**
 * PORTAL-QUOTE-DECLINE-REQUIRE-REASON · Feb-2026.
 *
 * Display labels for the customer-facing quote decline reason
 * dropdown.  Stored values (snake_case) MUST stay in sync with the
 * backend enum at
 * ``backend/services/quote_decline_reasons.py`` — if you change
 * either file, change both and run both test suites.
 */

// Keep in lock-step with
// ``backend/services/quote_decline_reasons.py::DECLINE_REASON_CATEGORIES``.
export const DECLINE_REASON_CATEGORIES = [
  { value: "too_expensive",              label: "Too expensive" },
  { value: "going_with_another_provider", label: "Going with another provider" },
  { value: "timing_not_right",           label: "Timing not right" },
  { value: "changed_my_mind",            label: "Changed my mind" },
  { value: "scope_not_what_expected",    label: "Scope not what I expected" },
  { value: "other",                      label: "Other" },
];

// Validation bounds for the free-text explanation.  Mirror the
// server-side bounds in
// ``backend/services/quote_decline_reasons.py``.
export const DECLINE_REASON_TEXT_MIN_LEN = 10;
export const DECLINE_REASON_TEXT_MAX_LEN = 500;

/** Lookup helper: snake_case value → display label (or value if
 *  unknown).  Used by the admin DeclineReasonBlock on
 *  QuoteInvoiceDetail. */
export function declineReasonLabel(value) {
  const match = DECLINE_REASON_CATEGORIES.find((c) => c.value === value);
  return match ? match.label : (value || "");
}
