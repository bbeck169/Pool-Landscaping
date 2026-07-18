import React from "react";
import { FilePlus2, LibraryBig } from "lucide-react";
import { colors, brandGradientCss } from "@/theme";
import { CATEGORY_LABEL } from "@/api/templates";

/**
 * Card representing a single template definition on the library page.
 * `onCreate` receives the template code and creates a draft instance.
 */
export default function TemplateCard({ definition, onCreate, busy = false }) {
  const cat = CATEGORY_LABEL[definition.category] || definition.category;
  return (
    <div
      className="rounded-2xl p-5 flex flex-col h-full transition-shadow hover:shadow-lg"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={`template-card-${definition.code}`}
    >
      <div className="flex items-start justify-between mb-2 gap-2">
        <div
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
          style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
        >
          <LibraryBig size={11} /> {cat}
        </div>
        {definition.is_system && (
          <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
            System
          </span>
        )}
      </div>
      <h3 className="text-base font-bold mb-1" style={{ color: colors.onSurface }}>
        {definition.title}
      </h3>
      {definition.description && (
        <p className="text-sm mb-4 flex-1" style={{ color: colors.onSurfaceSecondary }}>
          {definition.description}
        </p>
      )}
      <button
        onClick={() => onCreate?.(definition.code)}
        disabled={busy}
        className="mt-auto inline-flex items-center justify-center gap-1 px-3 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
        style={{ background: brandGradientCss }}
        data-testid={`template-card-create-${definition.code}`}
      >
        <FilePlus2 size={14} /> New from template
      </button>
    </div>
  );
}
