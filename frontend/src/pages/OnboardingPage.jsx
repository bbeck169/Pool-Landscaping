/**
 * Phase 4 · Batch B / D6 — Employee onboarding checklist.
 * Route: `/onboarding` — user's own tasks with deep links.
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ClipboardList, CheckCircle2, Circle, Play, Loader2 } from "lucide-react";
import { colors, gradients } from "@/theme";
import {
  getUserProgress, markTaskComplete, TASK_KIND_LABEL, taskDeepLink,
} from "@/api/handbook";

export default function OnboardingPage() {
  const [prog, setProg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);

  const reload = async () => {
    setLoading(true);
    try {
      setProg(await getUserProgress("me"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { reload(); }, []);

  const complete = async (code) => {
    setBusy(code);
    try { await markTaskComplete(code); await reload(); } finally { setBusy(null); }
  };

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="onboarding-page">
      <h1 className="text-3xl font-bold flex items-center gap-2 mb-1" style={{ color: colors.onSurface }}>
        <ClipboardList size={28} style={{ color: colors.brand }} /> Your Onboarding
      </h1>
      <p className="text-sm mb-4" style={{ color: colors.onSurfaceSecondary }}>
        Work through this checklist during your first weeks. Reading a handbook section for 30 seconds auto-completes that task; finalizing a template form auto-completes its task.
      </p>

      {loading ? (
        <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>
      ) : !prog ? null : (
        <>
          <div className="rounded-2xl p-4 mb-4" style={{ background: gradients.navyToGreen.css, color: "#fff" }} data-testid="onboarding-summary">
            <div className="text-3xl font-bold">{prog.complete} / {prog.total}</div>
            <div className="text-sm opacity-90">tasks complete · {Math.round(prog.pct)}%</div>
            <div className="w-full h-2 rounded-full mt-2" style={{ backgroundColor: "rgba(255,255,255,0.25)" }}>
              <div className="h-2 rounded-full" style={{ width: `${prog.pct}%`, backgroundColor: "#fff" }} />
            </div>
          </div>

          <div className="rounded-2xl overflow-hidden" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
            {prog.rows.map((t) => {
              const done = t.progress.status === "complete";
              return (
                <div key={t.code}
                  className="flex items-center gap-3 px-4 py-3"
                  style={{ borderBottom: `1px solid ${colors.border}` }}
                  data-testid={`onboarding-task-${t.code}`}>
                  {done ? (
                    <CheckCircle2 size={20} style={{ color: colors.success }} />
                  ) : (
                    <Circle size={20} style={{ color: colors.muted }} />
                  )}
                  <div className="flex-1">
                    <div className="text-sm font-bold" style={{ color: done ? colors.muted : colors.onSurface, textDecoration: done ? "line-through" : "none" }}>
                      {t.title}
                    </div>
                    <div className="text-[11px]" style={{ color: colors.muted }}>
                      {TASK_KIND_LABEL[t.kind] || t.kind}
                      {t.description ? ` · ${t.description}` : ""}
                    </div>
                  </div>
                  {!done && (
                    <div className="flex items-center gap-1">
                      <Link to={taskDeepLink(t)}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold"
                        style={{ backgroundColor: colors.brandTertiary, color: colors.brand, border: `1px solid ${colors.border}` }}
                        data-testid={`onboarding-task-start-${t.code}`}>
                        <Play size={12} /> Start
                      </Link>
                      <button onClick={() => complete(t.code)} disabled={busy === t.code}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
                        style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                        data-testid={`onboarding-task-complete-${t.code}`}>
                        {busy === t.code ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
                        Mark done
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
