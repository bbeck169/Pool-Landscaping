/**
 * Phase 4 · Batch B / D6 — Admin onboarding dashboard.
 * Route: `/admin/onboarding` — per-user completion + drill-down.
 */
import React, { useEffect, useState } from "react";
import { Users, Filter } from "lucide-react";
import { colors, brandGradientCss } from "@/theme";
import { getOnboardingDashboard, getUserProgress } from "@/api/handbook";

export default function AdminOnboardingDashboardPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [role, setRole] = useState("");
  const [selected, setSelected] = useState(null);
  const [selectedProg, setSelectedProg] = useState(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try { setData(await getOnboardingDashboard(role || undefined)); } finally { setLoading(false); }
    })();
  }, [role]);

  const drillIn = async (row) => {
    setSelected(row);
    setSelectedProg(null);
    try { setSelectedProg(await getUserProgress(row.user_id)); } catch {}
  };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="admin-onboarding-page">
      <h1 className="text-3xl font-bold flex items-center gap-2 mb-3" style={{ color: colors.onSurface }}>
        <Users size={28} style={{ color: colors.brand }} /> Onboarding Dashboard
      </h1>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <Filter size={14} style={{ color: colors.muted }} />
        {["", "admin", "pool_tech", "landscape_tech", "customer"].map((r) => (
          <button key={r || "all"} onClick={() => setRole(r)}
            className="px-3 py-1.5 rounded-full text-xs font-bold"
            style={{
              backgroundColor: role === r ? colors.brand : colors.surface,
              color: role === r ? "#fff" : colors.onSurface,
              border: `1px solid ${role === r ? colors.brand : colors.border}`,
            }} data-testid={`admin-onboarding-filter-${r || "all"}`}>
            {r || "All roles"}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>
      ) : !data ? null : (
        <>
          <div className="rounded-2xl p-4 mb-4" style={{ background: brandGradientCss, color: "#fff" }}>
            <div className="text-3xl font-bold">{Math.round(data.avg_pct)}%</div>
            <div className="text-sm opacity-90">average completion · {data.total_users} users</div>
          </div>

          <div className="rounded-2xl overflow-hidden" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }} data-testid="admin-onboarding-rows">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                  <th className="px-3 py-2 text-left text-[11px] font-bold uppercase" style={{ color: colors.onSurfaceSecondary }}>User</th>
                  <th className="px-3 py-2 text-left text-[11px] font-bold uppercase" style={{ color: colors.onSurfaceSecondary }}>Role</th>
                  <th className="px-3 py-2 text-left text-[11px] font-bold uppercase" style={{ color: colors.onSurfaceSecondary }}>Progress</th>
                  <th className="px-3 py-2 text-right text-[11px] font-bold uppercase" style={{ color: colors.onSurfaceSecondary }}>%</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.user_id} onClick={() => drillIn(r)}
                    className="cursor-pointer hover:bg-slate-50"
                    style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`admin-onboarding-row-${r.user_id}`}>
                    <td className="px-3 py-2" style={{ color: colors.onSurface }}>{r.name || r.email}</td>
                    <td className="px-3 py-2 text-xs" style={{ color: colors.muted }}>{r.role}</td>
                    <td className="px-3 py-2 text-xs" style={{ color: colors.muted }}>{r.complete} / {r.total}</td>
                    <td className="px-3 py-2 text-right font-bold" style={{ color: r.pct >= 100 ? colors.success : r.pct >= 50 ? colors.warning : colors.error }}>
                      {Math.round(r.pct)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selected && (
            <div className="fixed inset-0 z-40 flex items-center justify-center p-4" style={{ backgroundColor: "rgba(0,0,0,0.55)" }} onClick={() => setSelected(null)} data-testid="admin-onboarding-drill">
              <div onClick={(e) => e.stopPropagation()} className="bg-white rounded-2xl max-w-2xl w-full max-h-[80vh] overflow-y-auto p-5" style={{ border: `1px solid ${colors.border}` }}>
                <h2 className="text-lg font-bold mb-2" style={{ color: colors.onSurface }}>{selected.name || selected.email}</h2>
                <p className="text-xs mb-3" style={{ color: colors.muted }}>{selected.role} · {selected.complete}/{selected.total} tasks · {Math.round(selected.pct)}%</p>
                {!selectedProg ? <div className="text-sm" style={{ color: colors.muted }}>Loading…</div> : (
                  <div className="space-y-1">
                    {selectedProg.rows.map((t) => (
                      <div key={t.code} className="flex items-center justify-between px-3 py-2 rounded-lg text-sm"
                        style={{ backgroundColor: colors.surfaceSecondary }}>
                        <span style={{ color: colors.onSurface }}>{t.title}</span>
                        <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full"
                          style={{
                            backgroundColor: t.progress.status === "complete" ? "#DCFCE7" : "#FEF9C3",
                            color: t.progress.status === "complete" ? "#166534" : "#A16207",
                          }}>
                          {t.progress.status}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                <div className="mt-4 text-right">
                  <button onClick={() => setSelected(null)}
                    className="px-3 py-2 rounded-xl text-sm font-semibold"
                    style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}>
                    Close
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
