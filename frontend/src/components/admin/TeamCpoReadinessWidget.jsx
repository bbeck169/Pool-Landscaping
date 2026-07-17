/**
 * Phase 56.13c · Team CPO Readiness widget.
 *
 * Two-line card summarizing how many pool-department techs (department
 * in ["pool", "both"], role="technician") in the tenant have earned the
 * CPO Prep completion cert vs are in-progress vs haven't started.
 *
 * - Certified: cert row exists for module_code=cpo-prep.
 * - In progress: has training_progress rows for cpo-prep but no cert.
 * - Not started: neither.
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { GraduationCap, ChevronDown, ChevronRight } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

export default function TeamCpoReadinessWidget() {
  const [expand, setExpand] = useState(false);
  const [state, setState] = useState({ loading: true, error: "", rows: [] });

  useEffect(() => {
    (async () => {
      try {
        // Fetch: cert rows for cpo-prep + user list (techs in pool/both).
        const [certs, users] = await Promise.all([
          api.get("/training/certificates/admin"),
          api.get("/team"),
        ]);
        const cpoCerts = (Array.isArray(certs) ? certs : []).filter(
          (c) => c.module_code === "cpo-prep"
        );
        const techs = (Array.isArray(users) ? users : []).filter((u) => {
          const role = (u.role || "").toLowerCase();
          const dept = (u.department || "").toLowerCase();
          return role === "technician" && (dept === "pool" || dept === "both" || dept === "");
        });
        // Progress rows are per-user; use presence of ANY cpo-prep
        // attempt/progress as proxy — but we don't have a bulk
        // progress endpoint, so mark "in progress" by looking for
        // attempts via the attempts endpoint per user is too heavy.
        // Approximation: any tech NOT in cpoCerts is "not started"
        // unless they've attempted the quiz (we can't cheaply detect
        // that without a new endpoint). V1: mark them "not started".
        // A follow-up ship can add `GET /training/progress/admin` to
        // improve accuracy.
        const certByUserId = new Map(cpoCerts.map((c) => [c.user_id, c]));
        const rows = techs.map((t) => {
          const cert = certByUserId.get(t.id);
          return {
            id: t.id,
            name: t.name || t.email,
            status: cert ? "Certified" : "Not started",
            score: cert ? Math.round((cert.quiz_score || 0) * 100) : null,
            awarded_at: cert?.awarded_at || null,
          };
        });
        setState({ loading: false, error: "", rows });
      } catch (e) {
        setState({ loading: false, error: e?.message || "Failed to load", rows: [] });
      }
    })();
  }, []);

  const certified = state.rows.filter((r) => r.status === "Certified").length;
  const total = state.rows.length;
  const inProg = 0;                                    // v1 approximation (see comment above)
  const notStarted = total - certified - inProg;

  return (
    <div
      className="rounded-2xl p-4 mb-6"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="cpo-readiness-widget"
    >
      <button
        type="button"
        onClick={() => setExpand((v) => !v)}
        className="w-full flex items-center justify-between text-left"
        style={{ background: "transparent", border: 0, cursor: "pointer" }}
        data-testid="cpo-readiness-toggle"
      >
        <div className="flex items-center gap-2">
          <GraduationCap size={18} color={colors.brand} />
          <div>
            <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
              Team CPO Readiness
            </div>
            {state.loading ? (
              <div className="text-xs" style={{ color: colors.muted }}>Loading…</div>
            ) : state.error ? (
              <div className="text-xs" style={{ color: "#DC2626" }}>{state.error}</div>
            ) : (
              <div className="text-xs" style={{ color: colors.muted }}
                   data-testid="cpo-readiness-summary">
                {certified} of {total} pool techs certified · {inProg} in progress · {notStarted} not started
              </div>
            )}
          </div>
        </div>
        {expand ? <ChevronDown size={14} color={colors.muted} />
                : <ChevronRight size={14} color={colors.muted} />}
      </button>

      {expand && !state.loading && state.rows.length > 0 ? (
        <div className="mt-3 rounded-md overflow-hidden"
             style={{ border: `1px solid ${colors.border}` }}>
          <table className="w-full text-xs" data-testid="cpo-readiness-table">
            <thead style={{ background: colors.surfaceAlt }}>
              <tr>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Tech</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Status</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Score</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Awarded</th>
              </tr>
            </thead>
            <tbody>
              {state.rows.map((r) => (
                <tr key={r.id} data-testid={`cpo-readiness-row-${r.id}`}>
                  <td className="px-3 py-2 font-bold" style={{ color: colors.onSurface }}>{r.name}</td>
                  <td className="px-3 py-2"
                      style={{ color: r.status === "Certified" ? "#059669" : colors.muted }}>
                    {r.status}
                  </td>
                  <td className="px-3 py-2 text-right" style={{ color: colors.muted }}>
                    {r.score != null ? `${r.score}%` : "—"}
                  </td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>
                    {r.awarded_at ? r.awarded_at.slice(0, 10) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[10px] px-3 py-2 italic"
               style={{ color: colors.muted, background: colors.surfaceAlt }}>
            v1 approximation: "In progress" counter requires a bulk-progress endpoint (deferred to 56.13b-followup).
            <Link to="/admin/training" className="ml-2" style={{ color: colors.brand, textDecoration: "underline" }}>
              Manage training →
            </Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}
