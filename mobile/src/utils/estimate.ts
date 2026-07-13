// Gross-margin pricing with overhead recovery. Mirrors backend routers/estimates.py.
export type EstimateLine = {
  category: string; // Material | Labor | Subcontractor | Equipment | Other
  description: string;
  quantity: number;
  unit_cost: number;
  item_id?: string | null;
};

export const CATEGORIES = ["Material", "Labor", "Subcontractor", "Equipment", "Other"] as const;

export const CATEGORY_META: Record<string, { color: string; icon: string }> = {
  Material: { color: "#0284C7", icon: "cube-outline" },
  Labor: { color: "#7C3AED", icon: "hammer-outline" },
  Subcontractor: { color: "#D97706", icon: "people-outline" },
  Equipment: { color: "#0891B2", icon: "construct-outline" },
  Other: { color: "#64748B", icon: "ellipsis-horizontal-outline" },
};

export function computeEstimate(lines: EstimateLine[], overheadPct: number, marginPct: number) {
  const direct = lines.reduce((s, l) => s + (Number(l.quantity) || 0) * (Number(l.unit_cost) || 0), 0);
  const oh = Math.max(0, Number(overheadPct) || 0);
  const m = Math.min(Math.max(0, Number(marginPct) || 0), 99) / 100;
  const directCost = round2(direct);
  const overheadAmount = round2(directCost * oh / 100);
  const totalCost = round2(directCost + overheadAmount);
  const sellPrice = m < 1 ? round2(totalCost / (1 - m)) : totalCost;
  const profitAmount = round2(sellPrice - totalCost);
  const grossMarginPct = sellPrice ? round2((profitAmount / sellPrice) * 100) : 0;
  return { directCost, overheadAmount, totalCost, sellPrice, profitAmount, grossMarginPct };
}

function round2(n: number) {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}
