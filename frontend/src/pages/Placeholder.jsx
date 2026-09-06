import React from "react";
import { useAuth } from "@/auth";
import { colors, gradients } from "@/theme";
import { Info } from "lucide-react";

/**
 * Generic Phase 1 placeholder. Non-Dashboard nav entries route here.
 */
export default function Placeholder({ title, phase = 2, note }) {
  const { user } = useAuth();
  return (
    <div
      className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10"
      data-testid={`placeholder-${title.toLowerCase().replace(/\s+/g, "-")}`}
    >
      <p
        className="text-xs uppercase tracking-widest font-semibold mb-2"
        style={{ color: colors.brand }}
      >
        COMING IN PHASE {phase}
      </p>
      <h1 className="text-3xl font-bold mb-3" style={{ color: colors.onSurface }}>
        {title}
      </h1>
      <p className="text-base mb-6" style={{ color: colors.onSurfaceSecondary }}>
        This screen ships in <strong>Phase {phase}</strong>. Auth + shell + backend are already
        wired — you&apos;re signed in as <strong>{user?.role}</strong>.
      </p>
      {note ? (
        <div
          className="flex items-start gap-3 rounded-xl p-4 mb-6"
          style={{
            backgroundColor: colors.brandTertiary,
            color: colors.onBrandTertiary,
          }}
        >
          <Info size={18} className="flex-shrink-0 mt-0.5" />
          <p className="text-sm">{note}</p>
        </div>
      ) : null}
      <div
        className="rounded-2xl p-6"
        style={{
          background: gradients.navyToGreen.css,
          color: "#fff",
        }}
      >
        <p className="text-sm opacity-90">
          Meanwhile the Expo mobile app already ships this screen — visit the mobile web
          preview to try it end-to-end.
        </p>
      </div>
    </div>
  );
}
