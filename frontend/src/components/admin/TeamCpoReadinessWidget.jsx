/**
 * Phase 56.13b-followup — Team CPO Readiness widget with ACCURATE
 * in-progress counter powered by the new bulk-progress endpoint
 * (`GET /api/training/progress/admin?module_code=cpo-prep`).
 *
 * Certified   → user has a passing cert for cpo-prep.
 * In progress → has a `training_progress` doc with
 *                lessons_completed.length > 0 AND no passing cert.
 * Not started → neither.
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { GraduationCap, ChevronDown, ChevronRight, Send, X } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

export default function TeamCpoReadinessWidget() {
  const [expand, setExpand] = useState(false);
  const [state, setState] = useState({ loading: true, error: "", rows: [] });
  const [nudge, setNudge] = useState(null);   // {message, include_email, result?, err?}

  const openNudge = () => setNudge({
    message: "The CPO Prep training module is now live in your Tests menu. It takes ~2 hours and earns you a completion certificate. Let me know if you have questions.",
    include_email: false,
    result: null, err: null,
  });
  const closeNudge = () => setNudge(null);
  const sendNudge = async () => {
    try {
      const r = await api.post("/training/nudge-non-starters", {
        module_code: "cpo-prep",
        message: nudge.message,
        include_email: !!nudge.include_email,
      });
      setNudge({ ...nudge, result: r, err: null });
    } catch (e) {
      setNudge({ ...nudge, err: e.message });
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const [certs, users, progress] = await Promise.all([
          api.get("/training/certificates/admin"),
          api.get("/team"),
          // Phase 56.13b-followup — bulk-progress endpoint. Small
          // response (one row per user × module), tenant-scoped.
          api.get("/training/progress/admin?module_code=cpo-prep"),
        ]);

        const cpoCerts = (Array.isArray(certs) ? certs : []).filter(
          (c) => c.module_code === "cpo-prep"
        );
        const certByUserId = new Map(cpoCerts.map((c) => [c.user_id, c]));

        const progressByUserId = new Map(
          (Array.isArray(progress) ? progress : []).map((p) => [p.user_id, p])
        );

        const techs = (Array.isArray(users) ? users : []).filter((u) => {
          const role = (u.role || "").toLowerCase();
          const dept = (u.department || "").toLowerCase();
          return role === "technician" && (dept === "pool" || dept === "both" || dept === "");
        });

        const rows = techs.map((t) => {
          const cert = certByUserId.get(t.id);
          const p = progressByUserId.get(t.id);
          let status;
          if (cert) status = "Certified";
          else if (p && (p.lessons_completed || []).length > 0) status = "In progress";
          else status = "Not started";
          return {
            id: t.id,
            name: t.name || t.email,
            status,
            score: cert ? Math.round((cert.quiz_score || 0) * 100) : null,
            awarded_at: cert?.awarded_at || null,
            lessons_completed: (p?.lessons_completed || []).length,
          };
        });

        setState({ loading: false, error: "", rows });
      } catch (e) {
        setState({ loading: false, error: e?.message || "Failed to load", rows: [] });
      }
    })();
  }, []);

  const certified = state.rows.filter((r) => r.status === "Certified").length;
  const inProg = state.rows.filter((r) => r.status === "In progress").length;
  const total = state.rows.length;
  const notStarted = total - certified - inProg;
  const nonStarters = state.rows.filter((r) => r.status === "Not started");

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

      {!state.loading && !state.error && notStarted > 0 ? (
        <div className="mt-2">
          <button onClick={openNudge}
                  className="text-xs font-semibold rounded-lg px-3 py-1.5 inline-flex items-center gap-1"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="cpo-nudge-btn">
            <Send size={11} /> Nudge {notStarted} non-starter{notStarted === 1 ? "" : "s"}
          </button>
        </div>
      ) : null}

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
                      style={{
                        color: r.status === "Certified"
                          ? "#059669"
                          : r.status === "In progress"
                          ? "#B45309"
                          : colors.muted,
                      }}>
                    {r.status}
                    {r.status === "In progress" ? (
                      <span className="ml-1 text-[10px]" style={{ color: colors.muted }}>
                        ({r.lessons_completed} lessons)
                      </span>
                    ) : null}
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
            In-progress counter accurate as of last widget load.
            <Link to="/admin/training" className="ml-2" style={{ color: colors.brand, textDecoration: "underline" }}>
              Manage training →
            </Link>
          </div>
        </div>
      ) : null}

      {nudge ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center p-6 overflow-y-auto"
             style={{ backgroundColor: "rgba(0,0,0,0.4)" }}
             data-testid="cpo-nudge-modal">
          <div className="rounded-2xl max-w-lg w-full my-4"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
            <div className="flex items-center justify-between p-4"
                 style={{ borderBottom: `1px solid ${colors.border}` }}>
              <div>
                <div className="text-lg font-bold" style={{ color: colors.onSurface }}>
                  Nudge non-starters
                </div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  {nonStarters.length} tech{nonStarters.length === 1 ? "" : "s"} · CPO Prep module
                </div>
              </div>
              <button onClick={closeNudge} data-testid="cpo-nudge-close">
                <X size={18} color={colors.muted} />
              </button>
            </div>
            <div className="p-4 space-y-3">
              <div className="rounded-lg p-2 text-xs"
                   style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}` }}>
                <div className="font-semibold mb-1" style={{ color: colors.muted }}>
                  Non-starters
                </div>
                <ul className="text-xs space-y-0.5" style={{ color: colors.onSurface }}>
                  {nonStarters.map((r) => (
                    <li key={r.id}>{r.name}</li>
                  ))}
                </ul>
              </div>
              <label className="block">
                <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
                  Message
                </span>
                <textarea value={nudge.message}
                          onChange={(e) => setNudge({ ...nudge, message: e.target.value })}
                          rows={5}
                          className="mt-1 w-full rounded-lg px-3 py-2 text-sm"
                          style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                          data-testid="cpo-nudge-message" />
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={nudge.include_email}
                       onChange={(e) => setNudge({ ...nudge, include_email: e.target.checked })}
                       data-testid="cpo-nudge-include-email" />
                <span className="text-sm" style={{ color: colors.onSurface }}>
                  Also draft email
                </span>
                <span className="text-xs" style={{ color: colors.muted }}>
                  (delivered if RESEND_API_KEY set; else audit row only)
                </span>
              </label>
              {nudge.result ? (
                <div className="rounded-lg p-2 text-xs" data-testid="cpo-nudge-result"
                     style={{ backgroundColor: "#DCFCE7", color: "#166534" }}>
                  Nudged <b>{nudge.result.count_nudged}</b> tech{nudge.result.count_nudged === 1 ? "" : "s"}.
                  {" "}Skipped <b>{nudge.result.count_skipped_idempotent}</b> already-nudged this week.
                  {nudge.result.email_ids?.length ? ` Emails queued: ${nudge.result.email_ids.length}.` : ""}
                </div>
              ) : null}
              {nudge.err ? (
                <div className="rounded-lg p-2 text-xs" data-testid="cpo-nudge-error"
                     style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}>
                  {nudge.err}
                </div>
              ) : null}
            </div>
            <div className="p-4 flex items-center justify-end gap-2"
                 style={{ borderTop: `1px solid ${colors.border}` }}>
              <button onClick={closeNudge}
                      className="text-sm font-semibold px-3 py-2 rounded-lg"
                      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="cpo-nudge-cancel">
                Cancel
              </button>
              <button onClick={sendNudge}
                      className="text-sm font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1"
                      style={{ backgroundColor: colors.brand, color: "#fff" }}
                      data-testid="cpo-nudge-send">
                <Send size={13} /> Send Nudge
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
