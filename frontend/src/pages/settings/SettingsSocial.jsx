/**
 * SettingsSocial · Feb-2026 · Consolidated Settings.
 *
 * Moves the 8-platform Soshie connect grid out of /soshie into
 * /settings/social so admins have a single OAuth / credential
 * management surface. The Soshie page itself keeps the Brand Brain,
 * Autopilot, and Review Queue tabs — only the "connect" grid moves.
 *
 * This page reuses ``AutopilotSchedulesTab``'s platform config grid
 * via a direct fetch of the same endpoints — the underlying REST
 * surface (``/soshie/platforms``, ``/soshie/autopilot/config``) is
 * unchanged. Cadence editing lives here alongside connection
 * status, so admins see everything about a platform in one place.
 */
import React from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, ImageIcon } from "lucide-react";
import { colors } from "@/theme";
import AutopilotSchedulesTab from "@/pages/soshie/AutopilotSchedulesTab";

export default function SettingsSocial() {
  return (
    <div className="space-y-4" data-testid="settings-social-page">
      <div className="rounded-2xl p-5"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold"
                 style={{ color: colors.onSurface }}>
              Social connections
            </h2>
            <p className="text-sm mt-1"
                style={{ color: colors.muted }}>
              Manage OAuth + cadence for every social channel the app
              publishes to. Brand Brain / Autopilot / Review Queue for
              content orchestration live on the Soshie workspace.
            </p>
          </div>
          <Link
            to="/soshie"
            className="inline-flex items-center gap-1 text-sm font-semibold px-3 py-1.5 rounded-md hover:brightness-95"
            style={{ backgroundColor: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}`,
                      color: colors.brand }}
            data-testid="settings-social-open-soshie"
          >
            <ImageIcon size={14} /> Open Soshie <ArrowUpRight size={12} />
          </Link>
        </div>
      </div>

      {/* Embed the platform config grid (same component used on
          /soshie so behaviour stays consistent). */}
      <AutopilotSchedulesTab />
    </div>
  );
}
