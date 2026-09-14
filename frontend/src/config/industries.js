/**
 * Phase Feb-2026 · Multi-industry Phase A — canonical industry
 * enum + labels for the frontend.
 *
 * MUST stay in exact parity with
 * ``backend/services/industries.py``. The Vitest suite
 * ``multi-industry-phase-a.test.jsx`` snapshots the two lists and
 * fails loud if they drift.
 *
 * Phase A scope: expose the enum + a ``useIndustries()`` hook.
 * NO UI, NO gating changes in this dispatch — see the phase memo
 * for Phase B (multi-select settings UI) and Phase C (re-gating
 * existing pool/landscape branches) roadmap.
 */

export const INDUSTRIES = Object.freeze([
  "pools",
  "landscaping",
  "hvac",
  "plumbing",
  "pest_control",
  "notary",
  "photography",
  "handyman",
  "electrical",
  "pressure_washing",
  "window_cleaning",
  "pet_waste_removal",
  "trash_can_cleaning",
  "moving",
  "snow_removal",
  "lighting_installation",
  "epoxy_coating",
  "garage_storage",
  "custom_closets",
  "pet_grooming",
  "beauty",
  "garage_door",
  "roofing",
  "flooring",
  "automotive",
]);

export const INDUSTRY_LABELS = Object.freeze({
  pools:                 "Pools",
  landscaping:           "Landscaping",
  hvac:                  "HVAC",
  plumbing:              "Plumbing",
  pest_control:          "Pest Control",
  notary:                "Notary",
  photography:           "Photography",
  handyman:              "Handyman",
  electrical:            "Electrical",
  pressure_washing:      "Pressure Washing",
  window_cleaning:       "Window Cleaning",
  pet_waste_removal:     "Pet Waste Removal",
  trash_can_cleaning:    "Trash Can Cleaning",
  moving:                "Moving",
  snow_removal:          "Snow Removal",
  lighting_installation: "Lighting Installation",
  epoxy_coating:         "Epoxy Coating",
  garage_storage:        "Garage Storage",
  custom_closets:        "Custom Closets",
  pet_grooming:          "Pet Grooming",
  beauty:                "Beauty",
  garage_door:           "Garage Door",
  roofing:               "Roofing",
  flooring:              "Flooring",
  automotive:            "Automotive",
});

export const DEFAULT_INDUSTRY = "pools";

export function isValidIndustry(slug) {
  return typeof slug === "string" && slug in INDUSTRY_LABELS;
}
