/**
 * Phase 56.13b · Training — Module detail (lesson viewer).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { ArrowLeft, CheckCircle, Circle, ChevronLeft, ChevronRight, Trophy } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

export default function TrainingModuleDetail() {
  const { code } = useParams();
  const navigate = useNavigate();
  const [mod, setMod] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const m = await api.get(`/training/modules/${code}`);
      setMod(m);
      if (!selectedId && (m.lessons || []).length) setSelectedId(m.lessons[0].id);
    } catch (e) {
      setError(e?.message || "Could not load module");
    }
  }, [code, selectedId]);

  useEffect(() => { load(); }, [load]);

  const lessons = mod?.lessons || []; // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: derived value stable-by-reference; downstream useMemo already tracks the real source deps
  const completedIds = useMemo(() => new Set(mod?.progress?.lessons_completed || []), [mod]);
  const selected = useMemo(
    () => lessons.find((l) => l.id === selectedId) || lessons[0] || null,
    [lessons, selectedId]
  );
  const selectedIdx = lessons.findIndex((l) => l.id === selected?.id);
  const allDone = lessons.length > 0 && lessons.every((l) => completedIds.has(l.id));

  const markComplete = useCallback(async () => {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      await api.post(`/training/modules/${code}/progress`, { lesson_id: selected.id });
      await load();
    } catch (e) {
      setError(e?.message || "Could not mark complete");
    } finally {
      setBusy(false);
    }
  }, [code, selected, load]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: memoized deps are stable by value; wrapping the source in its own useMemo would obscure the read

  if (!mod) return (
    <div className="max-w-5xl mx-auto py-6 px-4">
      {error ? <div className="text-sm" style={{ color: "#DC2626" }}>{error}</div>
             : <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>}
    </div>
  );

  return (
    <div className="max-w-6xl mx-auto py-6 px-4" data-testid="training-module-detail-page">
      <Link
        to="/tests"
        className="inline-flex items-center gap-1 text-xs font-bold mb-3"
        style={{ color: colors.brand, textDecoration: "none" }}
        data-testid="training-back-to-list"
      ><ArrowLeft size={12} /> All modules</Link>

      <div className="mb-4">
        <div className="text-lg font-bold" style={{ color: colors.onSurface }}>{mod.title}</div>
        {mod.description ? (
          <div className="text-xs mt-1" style={{ color: colors.muted }}>{mod.description}</div>
        ) : null}
        {mod.disclaimer ? (
          <div className="text-[11px] mt-2 p-2 rounded-md"
               style={{ background: "#FEF3C7", color: "#7C2D12", border: "1px solid #FCD34D" }}
               data-testid="training-module-disclaimer">{mod.disclaimer}</div>
        ) : null}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[280px_1fr] gap-4">
        <aside className="rounded-lg overflow-hidden"
               style={{ background: "#fff", border: `1px solid ${colors.border}` }}
               data-testid="training-lesson-list">
          <div className="text-[11px] font-bold uppercase tracking-wider px-3 py-2"
               style={{ background: colors.surfaceAlt, color: colors.muted }}>
            Lessons ({completedIds.size} / {lessons.length})
          </div>
          {lessons.map((l) => {
            const done = completedIds.has(l.id);
            const active = l.id === selected?.id;
            return (
              <button
                key={l.id}
                type="button"
                onClick={() => setSelectedId(l.id)}
                className="w-full text-left px-3 py-2 border-b flex items-start gap-2"
                style={{
                  borderColor: colors.border,
                  background: active ? "#EFF6FF" : "#fff",
                  cursor: "pointer",
                }}
                data-testid={`training-lesson-item-${l.id}`}
              >
                {done ? <CheckCircle size={14} color="#10B981" className="mt-0.5" /> :
                        <Circle size={14} color={colors.muted} className="mt-0.5" />}
                <span className="text-xs flex-1" style={{ color: colors.onSurface }}>
                  <span className="font-bold">{String(l.order).padStart(2, "0")}.</span> {l.title}
                </span>
              </button>
            );
          })}
        </aside>

        <main className="rounded-lg overflow-hidden"
              style={{ background: "#fff", border: `1px solid ${colors.border}` }}>
          {selected ? (
            <>
              <article className="p-5 prose prose-sm max-w-none" data-testid="training-lesson-body">
                <ReactMarkdown
                  components={{
                    h1: (p) => <h1 className="text-xl font-bold mb-2" {...p} />,
                    h2: (p) => <h2 className="text-base font-bold mt-4 mb-1" {...p} />,
                    p: (p) => <p className="text-sm my-2 leading-relaxed" style={{ color: colors.onSurface }} {...p} />,
                    li: (p) => <li className="text-sm my-1" {...p} />,
                    a: (p) => <a className="underline" style={{ color: colors.brand }} target="_blank" rel="noreferrer" {...p} />,
                    code: (p) => <code className="text-xs px-1 py-0.5 rounded" style={{ background: colors.surfaceAlt }} {...p} />,
                  }}
                >
                  {selected.body_md || ""}
                </ReactMarkdown>
              </article>
              <div className="p-3 flex items-center justify-between border-t"
                   style={{ borderColor: colors.border }}>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={selectedIdx <= 0}
                    onClick={() => setSelectedId(lessons[selectedIdx - 1]?.id)}
                    className="text-xs font-bold px-3 py-1.5 rounded-md inline-flex items-center gap-1"
                    style={{
                      background: "transparent", border: `1px solid ${colors.border}`,
                      color: selectedIdx <= 0 ? colors.muted : colors.onSurface,
                      cursor: selectedIdx <= 0 ? "not-allowed" : "pointer",
                    }}
                    data-testid="training-lesson-prev"
                  ><ChevronLeft size={12} /> Prev</button>
                  <button
                    type="button"
                    disabled={selectedIdx >= lessons.length - 1}
                    onClick={() => setSelectedId(lessons[selectedIdx + 1]?.id)}
                    className="text-xs font-bold px-3 py-1.5 rounded-md inline-flex items-center gap-1"
                    style={{
                      background: "transparent", border: `1px solid ${colors.border}`,
                      color: selectedIdx >= lessons.length - 1 ? colors.muted : colors.onSurface,
                      cursor: selectedIdx >= lessons.length - 1 ? "not-allowed" : "pointer",
                    }}
                    data-testid="training-lesson-next"
                  >Next <ChevronRight size={12} /></button>
                </div>
                <button
                  type="button"
                  onClick={markComplete}
                  disabled={busy || completedIds.has(selected.id)}
                  className="text-xs font-bold px-3 py-1.5 rounded-md inline-flex items-center gap-1"
                  style={{
                    background: completedIds.has(selected.id) ? colors.muted : "#10B981",
                    color: "#fff", border: 0,
                    cursor: (busy || completedIds.has(selected.id)) ? "not-allowed" : "pointer",
                  }}
                  data-testid="training-lesson-mark-complete"
                >
                  {completedIds.has(selected.id) ? "Completed" : busy ? "Saving…" : "Mark as complete"}
                </button>
              </div>
            </>
          ) : (
            <div className="p-5 text-sm" style={{ color: colors.muted }}>This module has no lessons yet.</div>
          )}
        </main>
      </div>

      {allDone ? (
        <div className="mt-4 rounded-lg p-4 flex items-center justify-between"
             style={{ background: "#ECFDF5", border: "1px solid #10B981" }}
             data-testid="training-take-quiz-banner">
          <div className="text-sm font-bold" style={{ color: "#065F46" }}>
            <Trophy size={14} className="inline mr-1" /> All lessons complete — ready to take the quiz.
          </div>
          <button
            type="button"
            onClick={() => navigate(`/tests/${code}/quiz`)}
            className="text-xs font-bold px-4 py-2 rounded-md"
            style={{ background: "#10B981", color: "#fff", border: 0, cursor: "pointer" }}
            data-testid="training-take-quiz-btn"
          >Take Quiz</button>
        </div>
      ) : null}

      {error ? (
        <div className="mt-3 text-xs" style={{ color: "#DC2626" }} data-testid="training-detail-error">{error}</div>
      ) : null}
    </div>
  );
}
