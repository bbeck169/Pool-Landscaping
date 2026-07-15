/**
 * Phase 37 · CHEM_TYPES — shared config for the Chemicals Added
 * dropdown stack. Order matters (rendered top-to-bottom). Options are
 * pre-computed at module load so the render loop stays cheap.
 *
 * Kept as a plain JS module (not JSON) so the mobile TS mirror can
 * re-declare an identical config without importing across platform
 * boundaries.
 */

const gallons = [
  { label: "1/8 Gallon",   quantity: 0.125 },
  { label: "1/4 Gallon",   quantity: 0.25 },
  { label: "1/3 Gallon",   quantity: 0.333 },
  { label: "1/2 Gallon",   quantity: 0.5 },
  { label: "2/3 Gallon",   quantity: 0.667 },
  { label: "3/4 Gallon",   quantity: 0.75 },
  { label: "1 Gallon",     quantity: 1 },
  { label: "1.5 Gallons",  quantity: 1.5 },
  { label: "2 Gallons",    quantity: 2 },
];
const ounces = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20].map((n) => ({
  label: `${n} Ounces`,
  quantity: n,
}));
const tabs = Array.from({ length: 10 }, (_, i) => {
  const n = i + 1;
  return { label: `${n} Tab${n > 1 ? "s" : ""}`, quantity: n };
});
const calhypoPounds = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6].map((n) => ({
  label: n === 0.5 ? "1/2 Pound" : `${n} Pound${n > 1 ? "s" : ""}`,
  quantity: n,
}));
const saltBags = Array.from({ length: 10 }, (_, i) => {
  const n = i + 1;
  return { label: `${n} bag${n > 1 ? "s" : ""} of Salt`, quantity: n };
});

export const CHEM_TYPES = [
  {
    slug: "chlorine-tablets",
    name: "Chlorine Tablets",
    aliases: ["3 inch tabs", "chlorine tabs", "chlorine tablets 3 inch"],
    noOptionLabel: "No Tabs Used",
    sectionLabel: "~ 3 Inch tabs ~",
    unit: "tabs",
    options: tabs,
  },
  {
    slug: "liquid-chlorine",
    name: "Liquid Chlorine",
    aliases: ["chlorine liquid", "sodium hypochlorite"],
    noOptionLabel: "No Liquid Chlorine Used",
    unit: "gal",
    options: gallons,
  },
  {
    slug: "liquid-acid",
    name: "Liquid Acid (Muriatic)",
    aliases: ["muriatic acid", "liquid acid", "hydrochloric acid"],
    noOptionLabel: "No Liquid Acid Used",
    unit: "gal",
    options: gallons,
  },
  {
    slug: "calhypo-shock",
    name: "CalHypo Shock",
    aliases: ["calcium hypochlorite", "shock", "cal-hypo", "calhypo"],
    noOptionLabel: "No Calhypo Added",
    unit: "lbs",
    options: calhypoPounds,
  },
  {
    slug: "clarifier",
    name: "Clarifier",
    aliases: ["pool clarifier"],
    noOptionLabel: "No clarifier added",
    sectionLabel: "~ Ounces Measurement ~",
    unit: "oz",
    options: ounces,
  },
  {
    slug: "phosphate-remover",
    name: "Phosphate Remover",
    aliases: ["phosphate remover", "phos remover", "phosfree"],
    noOptionLabel: "No Phosphate Remover Added",
    unit: "oz",
    options: ounces,
  },
  {
    slug: "salt",
    name: "Salt",
    aliases: ["pool salt", "sodium chloride"],
    noOptionLabel: "No Salt Added",
    sectionLabel: "~ Salt ~",
    unit: "bags",
    options: saltBags,
  },
  {
    slug: "pool-enzymes",
    name: "Pool Enzymes",
    aliases: ["enzymes", "enzyme"],
    noOptionLabel: "No Pool Enzymes Added",
    unit: "oz",
    options: ounces,
  },
  {
    slug: "algaecide",
    name: "Algaecide",
    aliases: ["algicide", "polyquat", "algae killer"],
    noOptionLabel: "No Algaecide Added",
    unit: "oz",
    options: ounces,
  },
];
