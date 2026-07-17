/**
 * Phase 56.13b · Training — Module list.
 * `/tests` and `/training` route to this page.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { GraduationCap, Award, PlayCircle, RotateCcw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { usePermissions } from "@/hooks/usePermissions";
import { PageHeader } from "@/components/ui-kit";

function ProgressRing({ percent }) {
  const p = Math.max(0, Math.min(1, percent || 0));
  const R = 18, C = 2 * Math.PI * R;
  const dash = C * p;
  return (
    <svg width="44" height="44" viewBox="0 0 44 44">
      <circle cx="22" cy="22" r={R} fill="none" stroke={colors.border} strokeWidth="4" />
      <circle
        cx="22" cy="22" r={R} fill="none"
        stroke={p >= 1 ? "#10B981" : colors.brand}
        strokeWidth="4"
        strokeDasharray={`${dash} ${C}`}
        transform="rotate(-90 22 22)"
        strokeLinecap="round"
      />
      <text
        x="22" y="26"
        textAnchor="middle"
        fontSize="11"
        fontWeight="700"
        fill={colors.onSurface}
      >{Math.round(p * 100)}%</text>
    </svg>
  );
}

function ModuleCard({ m }) {
  const percent = (m.progress?.percent) || 0;
  const completed = percent >= 1;
  const started = percent > 0 && percent < 1;
  const label = completed ? "Review" : started ? "Resume" : "Start";
  const Icon = completed ? Award : started ? RotateCcw : PlayCircle;
  return (
    <Link
      to={`/tests/${m.code}`}
      className="block rounded-lg p-4 transition"
      style={{
        background: "#fff",
        border: `1px solid ${colors.border}`,
        color: colors.onSurface,
        textDecoration: "none",
      }}
      data-testid={`training-module-card-${m.code}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span
              className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full"
              style={{
                background: m.department === "landscaping" ? "#DCFCE7" :
                            m.department === "both" ? "#FEF3C7" : "#DBEAFE",
                color: m.department === "landscaping" ? "#166534" :
                       m.department === "both" ? "#92400E" : "#1E40AF",
              }}
            >
              {(m.department || "pool").toUpperCase()}
            </span>
            {m.is_system ? (
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full"
                    style={{ background: "#F1F5F9", color: colors.muted }}>System</span>
            ) : null}
          </div>
          <div className="font-bold text-base">{m.title}</div>
          {m.description ? (
            <div className="text-xs mt-1" style={{ color: colors.muted }}>{m.description}</div>
          ) : null}
          <div className="text-[11px] mt-2" style={{ color: colors.muted }}>
            {m.lesson_count} lessons · {m.question_count} quiz questions
          </div>
        </div>
        <ProgressRing percent={percent} />
      </div>
      <div className="mt-3 flex items-center justify-end">
        <span
          className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
          style={{ background: completed ? "#10B981" : colors.brand, color: "#fff" }}
        >
          <Icon size={12} /> {label}
        </span>
      </div>
    </Link>
  );
}

export default function TrainingList() {
  const { role } = usePermissions();
  const [modules, setModules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get("/training/modules");
        setModules(Array.isArray(res) ? res : []);
      } catch (e) {
        setError(e?.message || "Could not load training modules");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const isAdmin = role === "admin" || role === "super_admin";
  const grouped = useMemo(() => {
    const pool = modules.filter((m) => m.department === "pool");
    const land = modules.filter((m) => m.department === "landscaping");
    const both = modules.filter((m) => m.department === "both");
    return { pool, land, both };
  }, [modules]);

  return (
    <div className="max-w-5xl mx-auto py-6 px-4 space-y-6" data-testid="training-list-page">
      <PageHeader
        icon={GraduationCap}
        title="Training / Tests"
        subtitle="Take courses, pass quizzes, earn internal completion badges."
        right={
          isAdmin ? (
            <Link
              to="/admin/training"
              className="text-xs font-bold px-3 py-1.5 rounded-md"
              style={{ background: "#fff", border: `1px solid ${colors.border}`, color: colors.onSurface, textDecoration: "none" }}
              data-testid="training-admin-manage-btn"
            >Manage modules</Link>
          ) : null
        }
      />

      {loading ? (
        <div className="text-sm" style={{ color: colors.muted }}>Loading modules…</div>
      ) : error ? (
        <div className="text-sm" style={{ color: "#DC2626" }} data-testid="training-list-error">{error}</div>
      ) : modules.length === 0 ? (
        <div className="rounded-lg p-6 text-center text-sm"
             style={{ background: "#fff", border: `1px dashed ${colors.border}`, color: colors.muted }}
             data-testid="training-list-empty">
          No training modules are available for your department yet.
        </div>
      ) : (
        <div className="space-y-6">
          {grouped.pool.length > 0 ? (
            <div>
              <div className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors.muted }}>Pool</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {grouped.pool.map((m) => <ModuleCard key={m.code} m={m} />)}
              </div>
            </div>
          ) : null}
          {grouped.land.length > 0 ? (
            <div>
              <div className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors.muted }}>Landscape</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {grouped.land.map((m) => <ModuleCard key={m.code} m={m} />)}
              </div>
            </div>
          ) : null}
          {grouped.both.length > 0 ? (
            <div>
              <div className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors.muted }}>Cross-Department</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {grouped.both.map((m) => <ModuleCard key={m.code} m={m} />)}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
