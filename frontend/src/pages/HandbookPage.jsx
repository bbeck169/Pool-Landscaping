/**
 * Phase 4 · Batch B / D6 — Handbook viewer (admin + user).
 * Route: `/handbook` (list) and `/handbook/:code` (viewer).
 * Admin can edit tenant-custom sections; system sections are read-only.
 */
import React, { useEffect, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { BookOpen, Search, Edit3, Save, Lock, X } from "lucide-react";
import { colors, gradients } from "@/theme";
import { useAuth } from "@/auth";
import {
  listHandbookSections, getHandbookSection, updateHandbookSection,
} from "@/api/handbook";
import { markTaskComplete, listOnboardingTasks } from "@/api/handbook";

export default function HandbookPage() {
  const { code } = useParams();
  const _navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = ["admin", "super_admin"].includes(user?.role || "");

  const [sections, setSections] = useState([]);
  const [active, setActive] = useState(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(false);
  const [editBody, setEditBody] = useState("");
  const [saveState, setSaveState] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const r = await listHandbookSections();
        setSections(r?.rows || []);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!code) { setActive(null); return; }
    (async () => {
      try { setActive(await getHandbookSection(code)); } catch (e) { setActive({ error: e.message }); }
    })();
  }, [code]);

  // Track 30-second read on the active section; when hit, look up any
  // matching read_handbook_section onboarding task and auto-mark it.
  useEffect(() => {
    if (!active || active.error) return;
    const t = setTimeout(async () => {
      try {
        const tasks = await listOnboardingTasks();
        const match = (tasks?.rows || []).find(
          (x) => x.kind === "read_handbook_section" && x.related_ref === active.code);
        if (match) await markTaskComplete(match.code, { source: "auto_read_30s" });
      } catch {}
    }, 30000);
    return () => clearTimeout(t);
  }, [active]);

  const filtered = sections.filter((s) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (s.title || "").toLowerCase().includes(q) || (s.code || "").toLowerCase().includes(q);
  });

  const startEdit = () => {
    if (!active || active.is_system) return;
    setEditBody(active.markdown_body || "");
    setEditing(true);
  };

  const saveEdit = async () => {
    setSaveState("saving");
    try {
      const updated = await updateHandbookSection(active.code, { markdown_body: editBody });
      setActive(updated);
      setEditing(false);
      setSaveState("saved");
      setTimeout(() => setSaveState(""), 2000);
    } catch (e) {
      setSaveState(`error: ${e.message}`);
    }
  };

  if (!code) {
    return (
      <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="handbook-list-page">
        <h1 className="text-3xl font-bold flex items-center gap-2 mb-2" style={{ color: colors.onSurface }}>
          <BookOpen size={28} style={{ color: colors.brand }} /> Company Handbook
        </h1>
        <p className="text-sm mb-4" style={{ color: colors.onSurfaceSecondary }}>
          Policies, procedures, and expectations. Reading a section for at least 30 seconds automatically completes the matching onboarding task.
        </p>
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <Search size={14} style={{ color: colors.muted }} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search sections…"
                 className="flex-1 outline-none text-sm bg-transparent"
                 data-testid="handbook-search" />
        </div>
        {loading ? (
          <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3" data-testid="handbook-cards">
            {filtered.map((s) => (
              <Link key={s.code} to={`/handbook/${encodeURIComponent(s.code)}`}
                className="rounded-2xl p-4 hover:shadow-md transition-shadow block"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid={`handbook-card-${s.code}`}>
                <div className="text-xs mb-1" style={{ color: colors.muted }}>
                  {s.is_system ? "System" : "Custom"} · v{s.version || 1}
                </div>
                <div className="text-base font-bold" style={{ color: colors.onSurface }}>{s.title}</div>
              </Link>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="handbook-section-page">
      <Link to="/handbook" className="text-sm font-semibold" style={{ color: colors.brand }}
        data-testid="handbook-back">← Back to Handbook</Link>

      {!active && <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>}
      {active?.error && (
        <div className="mt-4 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "#FEE2E2", color: colors.error }}>
          {active.error}
        </div>
      )}
      {active && !active.error && (
        <div className="mt-3 rounded-2xl p-5" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }} data-testid="handbook-title">
                {active.title}
              </h1>
              <div className="text-xs mt-1" style={{ color: colors.muted }}>
                {active.is_system ? (
                  <span className="inline-flex items-center gap-1"><Lock size={11} /> System — read-only</span>
                ) : (
                  <>Tenant-custom · v{active.version || 1}</>
                )}
              </div>
            </div>
            {isAdmin && !active.is_system && !editing && (
              <button onClick={startEdit}
                className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
                style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                data-testid="handbook-edit-btn">
                <Edit3 size={14} /> Edit
              </button>
            )}
          </div>

          {editing ? (
            <>
              <textarea value={editBody} onChange={(e) => setEditBody(e.target.value)} rows={20}
                className="w-full px-3 py-2 rounded-lg text-sm font-mono"
                style={{ border: `1px solid ${colors.border}` }}
                data-testid="handbook-edit-textarea" />
              <div className="flex justify-end gap-2 mt-3">
                <button onClick={() => setEditing(false)}
                  className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
                  style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                  data-testid="handbook-edit-cancel">
                  <X size={14} /> Cancel
                </button>
                <button onClick={saveEdit}
                  className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-bold text-white"
                  style={{ background: gradients.navyToGreen.css }} data-testid="handbook-edit-save">
                  <Save size={14} /> Save
                </button>
              </div>
              {saveState && <div className="text-xs mt-2" style={{ color: saveState.startsWith("error") ? colors.error : colors.success }}>{saveState}</div>}
            </>
          ) : (
            <div className="prose prose-sm max-w-none whitespace-pre-wrap" style={{ color: colors.onSurface }} data-testid="handbook-body">
              {active.markdown_body}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
