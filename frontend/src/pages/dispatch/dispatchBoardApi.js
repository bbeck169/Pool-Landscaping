// Phase 17 · Feb-2026 — Thin API client for the Dispatch Board page.
//
// Keeps every fetch inside a single module so the page component
// stays pure UI and the Vitest suite can mock a single import.
import { api } from "@/api";

const q = (p) => {
  const parts = Object.entries(p || {})
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  return parts.length ? `?${parts.join("&")}` : "";
};

export function fetchBoard({ day, tech_user_id, route_type, global_view, date } = {}) {
  return api.get(`/dispatch/board${q({
    day: day || "all",
    tech_user_id: tech_user_id || undefined,
    route_type: route_type || "all",
    global: global_view ? "true" : undefined,
    // Feb-2026 · concrete calendar date triggers the db.jobs
    // fallback in the backend when the customer-denorm path yields
    // empty. Omit for backwards-compat behaviour.
    date: date || undefined,
  })}`);
}

export function optimizeBoard({ day, tech_user_id, stop_customer_ids, start_lat, start_lng }) {
  return api.post(`/dispatch/board/optimize`, {
    day, tech_user_id, stop_customer_ids,
    start_lat: start_lat ?? null,
    start_lng: start_lng ?? null,
  });
}

export function applyBoardOrder({ day, tech_user_id, ordered_customer_ids }) {
  return api.post(`/dispatch/board/apply-order`, {
    day, tech_user_id, ordered_customer_ids,
  });
}
