// Phase 17 · Feb-2026 — Tech load strip.
//
// Renders the small "Tech Load" side panel on the right column of
// the dispatch board: a compact row per tech with a color swatch,
// name, and drop count. Selecting a tech proxies to the parent so
// the map + route list re-filter for that tech.
import React from "react";
import { UserRound } from "lucide-react";
import { colors } from "@/theme";

export default function TechLoadStrip({
  loads = [],
  selectedTechId = null,
  onSelect = () => {},
}) {
  if (!loads.length) {
    return (
      <div
        className="text-xs p-3 rounded-lg text-center"
        style={{ color: colors.muted, border: `1px dashed ${colors.border}` }}
        data-testid="dispatch-tech-load-empty"
      >
        No techs assigned to visible pins.
      </div>
    );
  }
  return (
    <ul className="space-y-1.5" data-testid="dispatch-tech-load-list">
      {loads.map((t) => {
        const active = selectedTechId === t.tech_user_id;
        return (
          <li key={t.tech_user_id}>
            <button
              type="button"
              onClick={() => onSelect(active ? null : t.tech_user_id)}
              className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-left transition hover:brightness-95"
              style={{
                backgroundColor: active ? colors.brandTertiary : colors.surface,
                border: `1px solid ${active ? colors.brand : colors.border}`,
                color: active ? colors.onBrandTertiary : colors.onSurface,
              }}
              data-testid={`dispatch-tech-load-${t.tech_user_id}`}
            >
              <span
                aria-hidden
                style={{
                  width: 14, height: 14, borderRadius: 999,
                  backgroundColor: t.color_hex || "#0EA5E9",
                  border: "2px solid #fff",
                  boxShadow: "0 0 0 1px rgba(0,0,0,0.1)",
                }}
              />
              <UserRound size={13} style={{ color: colors.muted }} />
              <span className="flex-1 text-sm font-semibold truncate">
                {t.name || t.tech_user_id}
              </span>
              <span
                className="text-xs font-bold px-1.5 py-0.5 rounded-full"
                style={{
                  background: active ? colors.brand : colors.surfaceSecondary,
                  color: active ? "#fff" : colors.onSurface,
                }}
              >
                {t.count}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
