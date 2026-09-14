/**
 * Phase D · Multi-industry — canonical industry enum + labels for mobile.
 *
 * Byte-parallel to ``frontend/src/config/industries.js``.
 * 25 slugs, ordered to match the backend source of truth.
 */

export const INDUSTRIES: readonly string[] = Object.freeze([
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

export const INDUSTRY_LABELS: Readonly<Record<string, string>> = Object.freeze({
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

export function isValidIndustry(slug: string): boolean {
  return typeof slug === "string" && slug in INDUSTRY_LABELS;
}
