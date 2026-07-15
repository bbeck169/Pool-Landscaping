import React from "react";
import { usePermissions, AVAILABLE_ROLES } from "@/hooks/usePermissions";
import { colors } from "@/theme";
import { EyeOff, Eye } from "lucide-react";

/**
 * "Test as Role" picker — a compact `<select>` designed to sit in the
 * top-right of the web shell.
 *
 * Only real admins / super-admins ever see it (`canPreview`); when a role is
 * selected, the app UI switches to enforce that role's matrix. All API calls
 * still go under the real user's JWT — the backend RBAC is unaffected.
 *
 * A tiny eye icon flips between hollow (real role) and filled (previewing)
 * so the switcher is visually distinguishable from ordinary form controls.
 */
export default function RolePreviewSwitcher() {
  const { canPreview, previewRole, setPreviewRole, isPreviewing, role } = usePermissions();
  if (!canPreview) return null;

  const value = previewRole || "";

  return (
    <div
      data-testid="role-preview-switcher"
      title={
        isPreviewing
          ? `Previewing UI as ${previewRole}. Your API calls still carry your admin JWT — server enforcement is unaffected.`
          : `Preview the app as a different role (UI-only; server RBAC unaffected). Real role: ${role}.`
      }
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 6px 4px 10px",
        borderRadius: 999,
        border: `1px solid ${isPreviewing ? "#B45309" : colors.border}`,
        background: isPreviewing ? "#FEF3C7" : colors.surface,
        color: isPreviewing ? "#92400E" : colors.onSurface,
        fontSize: 12,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {isPreviewing ? <Eye size={12} /> : <EyeOff size={12} />}
      <span data-testid="role-preview-label">
        {isPreviewing ? "Previewing" : "Test as"}
      </span>
      <select
        value={value}
        onChange={(e) => setPreviewRole(e.target.value || null)}
        style={{
          background: "transparent",
          border: "none",
          color: "inherit",
          fontWeight: 700,
          fontSize: 12,
          padding: "2px 4px",
          borderRadius: 6,
          cursor: "pointer",
          outline: "none",
        }}
        data-testid="role-preview-select"
      >
        <option value="">— off (real role)</option>
        {AVAILABLE_ROLES.map((r) => (
          <option key={r} value={r}>{r}</option>
        ))}
      </select>
      {isPreviewing ? (
        <button
          type="button"
          onClick={() => setPreviewRole(null)}
          style={{
            border: "none",
            background: "#B45309",
            color: "#fff",
            fontSize: 10,
            fontWeight: 800,
            padding: "3px 8px",
            borderRadius: 999,
            cursor: "pointer",
          }}
          data-testid="role-preview-exit"
        >
          Exit
        </button>
      ) : null}
    </div>
  );
}
