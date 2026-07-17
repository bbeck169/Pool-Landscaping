/**
 * Phase 56.13b-followup — Training Certifications panel.
 *
 * Renders the "Certifications" section shown on the technician
 * profile (admin view + tech's own profile). Consumes:
 *
 *   • GET /api/training/certificates          — logged-in user's certs.
 *   • GET /api/training/certificates/admin    — admin fallback used when
 *     viewing another user's profile (filtered client-side).
 *
 * Each row has a "Download PDF" button that opens
 * `${API_BASE}/api/training/certificates/{id}/pdf` in a new tab
 * with the auth token embedded via a temporary blob download so
 * the pdf endpoint's `Authorization` header requirement is
 * respected (no cookie auth).
 */
import React, { useCallback, useEffect, useState } from "react";
import { FileDown, Award } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

async function downloadCertPdf(certId) {
  // Auth-header–backed download (the pdf endpoint requires JWT).
  const base = process.env.REACT_APP_BACKEND_URL || "";
  const token = localStorage.getItem("token") || localStorage.getItem("pool_crm_token") || "";
  const resp = await fetch(`${base}/api/training/certificates/${certId}/pdf`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) throw new Error(`Download failed (${resp.status})`);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${certId}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

export default function TrainingCertsPanel({ userId, isOwnProfile, isAdminViewer }) {
  const [state, setState] = useState({ loading: true, error: "", rows: [] });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: "" }));
    try {
      if (isOwnProfile) {
        const rows = await api.get("/training/certificates");
        setState({ loading: false, error: "", rows: Array.isArray(rows) ? rows : [] });
      } else if (isAdminViewer) {
        // The `/technician/:id` route param may be a technician_id OR a
        // user_id depending on how the caller navigated in. Certs
        // store `user_id` (and, when seeded via 56.13a-commit, also
        // `technician_id`), so we match either field to be safe.
        const rows = await api.get("/training/certificates/admin");
        const filtered = (Array.isArray(rows) ? rows : []).filter(
          (r) => r.user_id === userId || r.technician_id === userId
        );
        setState({ loading: false, error: "", rows: filtered });
      } else {
        setState({ loading: false, error: "Not authorized.", rows: [] });
      }
    } catch (e) {
      setState({ loading: false, error: e?.message || "Failed to load", rows: [] });
    }
  }, [userId, isOwnProfile, isAdminViewer]);

  useEffect(() => { load(); }, [load]);

  if (state.loading) {
    return <div className="text-sm" style={{ color: colors.muted }}>Loading certifications…</div>;
  }
  if (state.error) {
    return <div className="text-sm" style={{ color: "#DC2626" }}>{state.error}</div>;
  }

  if (!state.rows.length) {
    return (
      <div
        className="rounded-lg p-4 text-sm text-center"
        style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}
        data-testid="profile-certs-empty"
      >
        No certifications earned yet. Take a training module to earn one.
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="profile-certs-section">
      {state.rows.map((c) => {
        const pct = Math.round((c.quiz_score || 0) * 100);
        return (
          <div
            key={c.certificate_id}
            className="rounded-lg p-3 flex items-center gap-3"
            style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
            data-testid={`profile-cert-row-${c.certificate_id}`}
          >
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
              style={{ background: "#F0FDF4", color: "#166534" }}
            >
              <Award size={18} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-bold truncate" style={{ color: colors.onSurface }}>
                {c.module_title || c.module_code}
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>
                {c.certificate_id} · {pct}% · Awarded {(c.awarded_at || "").slice(0, 10)}
              </div>
            </div>
            <button
              type="button"
              onClick={() => downloadCertPdf(c.certificate_id)}
              className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
              style={{ background: colors.brand, color: "#fff", border: 0, cursor: "pointer" }}
              data-testid={`profile-cert-download-${c.certificate_id}`}
            >
              <FileDown size={12} /> Download PDF
            </button>
          </div>
        );
      })}
    </div>
  );
}
