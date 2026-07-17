/**
 * Phase 56.13b · Training — Admin management page.
 * V1 scope: read-only table of modules + system-module viewer. Full
 * CRUD for tenant-custom modules is a future ship (called out in
 * HANDOFF).
 */
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { GraduationCap, ArrowLeft, Lock } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { PageHeader } from "@/components/ui-kit";

export default function AdminTraining() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/training/modules");
        setRows(Array.isArray(r) ? r : []);
      } catch (e) {
        setError(e?.message || "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="max-w-5xl mx-auto py-6 px-4 space-y-4" data-testid="training-admin-page">
      <Link
        to="/tests"
        className="inline-flex items-center gap-1 text-xs font-bold"
        style={{ color: colors.brand, textDecoration: "none" }}
      ><ArrowLeft size={12} /> Back to Training</Link>

      <PageHeader
        icon={GraduationCap}
        title="Manage training modules"
        subtitle="System modules (e.g. CPO Prep) are read-only. Tenant-custom modules will be editable in a future ship."
      />

      {loading ? (
        <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>
      ) : error ? (
        <div className="text-sm" style={{ color: "#DC2626" }}>{error}</div>
      ) : (
        <div className="rounded-lg overflow-hidden"
             style={{ background: "#fff", border: `1px solid ${colors.border}` }}>
          <table className="w-full text-xs" data-testid="training-admin-table">
            <thead style={{ background: colors.surfaceAlt }}>
              <tr>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Title</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Code</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Dept</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>System</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Lessons</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Quiz</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-4 text-center"
                      style={{ color: colors.muted }}
                      data-testid="training-admin-empty">
                    No modules yet.
                  </td>
                </tr>
              ) : rows.map((m) => (
                <tr key={m.code} data-testid={`training-admin-row-${m.code}`}>
                  <td className="px-3 py-2 font-bold" style={{ color: colors.onSurface }}>{m.title}</td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>{m.code}</td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>{m.department}</td>
                  <td className="px-3 py-2">
                    {m.is_system ? (
                      <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase px-2 py-0.5 rounded-full"
                            style={{ background: "#F1F5F9", color: colors.muted }}>
                        <Lock size={10} /> System
                      </span>
                    ) : "—"}
                  </td>
                  <td className="px-3 py-2 text-right" style={{ color: colors.muted }}>{m.lesson_count}</td>
                  <td className="px-3 py-2 text-right" style={{ color: colors.muted }}>{m.question_count}</td>
                  <td className="px-3 py-2">
                    <Link
                      to={`/tests/${m.code}`}
                      className="text-xs font-bold"
                      style={{ color: colors.brand, textDecoration: "none" }}
                      data-testid={`training-admin-view-${m.code}`}
                    >View →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="text-[11px]" style={{ color: colors.muted }}>
        Tenant-custom module editor + drag-reorder + leaderboard land in a follow-up ship.
      </div>
    </div>
  );
}
