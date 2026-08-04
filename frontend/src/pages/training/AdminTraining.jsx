/**
 * Phase 56.13b (rewritten in 56.13b-followup) — Admin training console.
 *
 * Three sections behind a segmented control:
 *   1. Modules — read-only table + full CRUD for tenant-custom modules.
 *      System modules (is_system=true) show a Lock badge and cannot be
 *      edited or deleted; the backend enforces this at the router
 *      level (`PATCH /training/modules/{code}` on cpo-prep → 409).
 *   2. Leaderboard — per-tech rollup (modules completed, quizzes
 *      passed, certs earned, avg score) over the last 90 days, sortable
 *      by any column + CSV export.
 *
 * Non-goals (called out explicitly): no rich text editor for lesson
 * bodies (markdown-in-textarea), no drag-drop reorder (up/down
 * arrows), no video embed beyond a URL field, no AI-assisted authoring.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  GraduationCap, ArrowLeft, Lock, Plus, Pencil, Trash2, X,
  ArrowUp, ArrowDown, Download,
} from "lucide-react";
import { api } from "@/api";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { colors } from "@/theme";
import { PageHeader } from "@/components/ui-kit";

const DEPT_OPTIONS = ["pool", "landscaping", "both"];

function newId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

// Slugify + validate codes to match the backend `TrainingModuleIn._check_code`.
function isValidCode(v) {
  return /^[a-z0-9][a-z0-9_-]{1,60}$/.test(v || "");
}

export default function AdminTraining() {
  const [view, setView] = useState("modules"); // modules | leaderboard
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null); // module doc | { __new: true }
  const [toast, setToast] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const r = await api.get("/training/modules");
      setRows(Array.isArray(r) ? r : []);
    } catch (e) {
      setError(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const showToast = (msg) => {
    setToast(msg);
    window.setTimeout(() => setToast(""), 2400);
  };

  return (
    <div className="max-w-5xl mx-auto py-6 px-4 space-y-4" data-testid="training-admin-page">
      <Link
        to="/tests"
        className="inline-flex items-center gap-1 text-xs font-bold"
        style={{ color: colors.brand, textDecoration: "none" }}
      ><ArrowLeft size={12} /> Back to Training</Link>

      <PageHeader
        icon={GraduationCap}
        title="Manage training"
        subtitle="Author tenant-custom modules, view module progress, and export a leaderboard. System modules (e.g. CPO Prep) are read-only."
      />

      {/* Segmented control */}
      <div className="flex gap-2 border-b" style={{ borderColor: colors.border }}>
        {[
          { k: "modules", label: "Modules" },
          { k: "leaderboard", label: "Leaderboard" },
        ].map((t) => (
          <button
            key={t.k}
            type="button"
            onClick={() => setView(t.k)}
            className="px-3 py-2 text-sm font-semibold border-b-2 -mb-px"
            style={{
              borderColor: view === t.k ? colors.brand : "transparent",
              color: view === t.k ? colors.brand : colors.muted,
              background: "transparent",
              cursor: "pointer",
            }}
            data-testid={`training-admin-tab-${t.k}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {view === "modules" ? (
        <ModulesTable
          rows={rows}
          loading={loading}
          error={error}
          onCreate={() => setEditing({ __new: true, code: "", title: "", description: "",
            department: "pool", lessons: [], quiz: { passing_score: 0.75, questions: [] } })}
          onEdit={setEditing}
          onDelete={async (m) => {
            if (!(await mustConfirm({
              title: `Delete tenant module "${m.title}"?`,
              description: "The module and its quiz will be removed. Existing completions stay.",
              tone: "danger", confirmText: "Delete", requireTypeConfirm: true,
            }))) return;
            try {
              await api.del(`/training/modules/${m.code}`);
              showToast(`Deleted "${m.title}"`);
              load();
            } catch (e) {
              alert(e?.message || "Delete failed");
            }
          }}
        />
      ) : (
        <Leaderboard />
      )}

      {editing ? (
        <ModuleEditorSheet
          module={editing}
          isNew={!!editing.__new}
          onClose={() => setEditing(null)}
          onSaved={(msg) => { setEditing(null); showToast(msg); load(); }}
        />
      ) : null}

      {toast ? (
        <div
          className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl text-sm text-white shadow-lg"
          style={{ backgroundColor: colors.onSurface }}
          data-testid="training-admin-toast"
        >
          {toast}
        </div>
      ) : null}
    </div>
  );
}

/* ── modules table ──────────────────────────────────────────────────── */
function ModulesTable({ rows, loading, error, onCreate, onEdit, onDelete }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-xs" style={{ color: colors.muted }}>
          Tenant-custom modules are editable. System modules are read-only.
        </div>
        <button
          type="button"
          onClick={onCreate}
          className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
          style={{ background: colors.brand, color: "#fff", border: 0, cursor: "pointer" }}
          data-testid="training-admin-new-module"
        >
          <Plus size={12} /> New tenant module
        </button>
      </div>

      {loading ? (
        <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>
      ) : error ? (
        <div className="text-sm" style={{ color: "#DC2626" }}>{error}</div>
      ) : (
        <div
          className="rounded-lg overflow-hidden"
          style={{ background: "#fff", border: `1px solid ${colors.border}` }}
        >
          <table className="w-full text-xs" data-testid="training-admin-table">
            <thead style={{ background: colors.surfaceAlt }}>
              <tr>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Title</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Code</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>Dept</th>
                <th className="text-left px-3 py-2" style={{ color: colors.muted }}>System</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Lessons</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Quiz</th>
                <th className="text-right px-3 py-2" style={{ color: colors.muted }}>Actions</th>
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
                  <td className="px-3 py-2 text-right">
                    <div className="inline-flex items-center gap-2">
                      <Link
                        to={`/tests/${m.code}`}
                        className="text-xs font-bold"
                        style={{ color: colors.brand, textDecoration: "none" }}
                        data-testid={`training-admin-view-${m.code}`}
                      >View</Link>
                      {m.is_system ? null : (
                        <>
                          <button
                            type="button"
                            onClick={() => onEdit(m)}
                            className="text-xs inline-flex items-center gap-1"
                            style={{ color: colors.brand, background: "transparent", border: 0, cursor: "pointer" }}
                            data-testid={`training-admin-edit-${m.code}`}
                          ><Pencil size={11} /> Edit</button>
                          <button
                            type="button"
                            onClick={() => onDelete(m)}
                            className="text-xs inline-flex items-center gap-1"
                            style={{ color: "#DC2626", background: "transparent", border: 0, cursor: "pointer" }}
                            data-testid={`training-admin-delete-${m.code}`}
                          ><Trash2 size={11} /> Delete</button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ── editor sheet — right-side slide-over ───────────────────────────── */
function ModuleEditorSheet({ module, isNew, onClose, onSaved }) {
  const [form, setForm] = useState(() => normalize(module));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { setForm(normalize(module)); }, [module]);

  const save = async () => {
    setErr("");
    if (isNew && !isValidCode(form.code)) {
      setErr("Code must be lowercase 2–61 chars, letters/digits/underscore/hyphen.");
      return;
    }
    if (!form.title.trim()) { setErr("Title is required."); return; }
    if (!DEPT_OPTIONS.includes(form.department)) { setErr("Invalid department."); return; }

    // Validate quiz — every question must have exactly one marked correct choice.
    for (const q of form.quiz.questions || []) {
      if (!q.prompt.trim()) { setErr("Every quiz question needs a prompt."); return; }
      if (!q.choices || q.choices.length < 2) { setErr("Every question needs at least 2 choices."); return; }
      const correct = q.correct_choice_ids || [];
      if (correct.length !== 1) { setErr(`Question "${q.prompt.slice(0, 30)}" must have exactly one correct choice.`); return; }
    }

    setSaving(true);
    try {
      const body = {
        title: form.title.trim(),
        description: form.description || "",
        department: form.department,
        lessons: (form.lessons || []).map((l, i) => ({
          ...l,
          order: i,
          estimated_minutes: Number(l.estimated_minutes) || 0,
        })),
        quiz: {
          passing_score: Number(form.quiz.passing_score) || 0.75,
          questions: (form.quiz.questions || []).map((q) => ({
            id: q.id,
            prompt: q.prompt.trim(),
            choices: (q.choices || []).map((ch) => ({
              id: ch.id,
              text: (ch.text || "").trim(),
            })),
            correct_choice_ids: q.correct_choice_ids || [],
            explanation: q.explanation || "",
            chapter_ref: q.chapter_ref || null,
          })),
        },
        badge_label: form.badge_label || "",
        disclaimer: form.disclaimer || "",
      };
      if (isNew) {
        body.code = form.code.trim();
        await api.post("/training/modules", body);
      } else {
        await api.patch(`/training/modules/${form.code}`, body);
      }
      onSaved(isNew ? `Created "${form.title}"` : `Updated "${form.title}"`);
    } catch (e) {
      setErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onClick={onClose}
      data-testid="training-admin-editor-sheet"
    >
      <div
        className="w-full max-w-2xl h-full overflow-y-auto"
        style={{ background: "#fff" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="px-5 py-3 flex items-center justify-between sticky top-0"
          style={{ background: "#fff", borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="font-bold text-sm">
            {isNew ? "New training module" : `Edit — ${form.title || form.code}`}
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{ background: "transparent", border: 0, cursor: "pointer" }}
            data-testid="training-admin-editor-close"
          >
            <X size={16} color={colors.muted} />
          </button>
        </div>

        <div className="p-5 space-y-5 text-sm">
          {err ? (
            <div className="px-3 py-2 rounded-md"
                 style={{ background: "#FEE2E2", color: "#991B1B" }}
                 data-testid="training-admin-editor-error">{err}</div>
          ) : null}

          <FieldGroup title="Basics">
            <TextInput
              label="Code (URL slug)"
              value={form.code}
              onChange={(v) => setForm({ ...form, code: v })}
              disabled={!isNew}
              placeholder="e.g. pool-safety-basics"
              testid="training-admin-editor-code"
            />
            <TextInput
              label="Title"
              value={form.title}
              onChange={(v) => setForm({ ...form, title: v })}
              testid="training-admin-editor-title"
            />
            <TextArea
              label="Description"
              value={form.description}
              onChange={(v) => setForm({ ...form, description: v })}
              testid="training-admin-editor-description"
            />
            <div className="flex gap-3">
              <div className="flex-1">
                <Label>Department</Label>
                <select
                  className="w-full text-sm px-2 py-2 rounded-md"
                  style={{ border: `1px solid ${colors.border}` }}
                  value={form.department}
                  onChange={(e) => setForm({ ...form, department: e.target.value })}
                  data-testid="training-admin-editor-department"
                >
                  {DEPT_OPTIONS.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </div>
              <div className="w-40">
                <Label>Passing score</Label>
                <input
                  className="w-full text-sm px-2 py-2 rounded-md"
                  style={{ border: `1px solid ${colors.border}` }}
                  type="number" min="0" max="1" step="0.05"
                  value={form.quiz.passing_score}
                  onChange={(e) => setForm({
                    ...form,
                    quiz: { ...form.quiz, passing_score: Number(e.target.value) },
                  })}
                  data-testid="training-admin-editor-passing-score"
                />
                <div className="text-[10px] mt-0.5" style={{ color: colors.muted }}>
                  0.0 – 1.0 (0.75 = 75%)
                </div>
              </div>
            </div>
          </FieldGroup>

          <LessonsEditor
            lessons={form.lessons || []}
            onChange={(lessons) => setForm({ ...form, lessons })}
          />

          <QuizEditor
            quiz={form.quiz}
            onChange={(quiz) => setForm({ ...form, quiz })}
          />
        </div>

        <div
          className="px-5 py-3 sticky bottom-0 flex items-center justify-end gap-2"
          style={{ background: "#fff", borderTop: `1px solid ${colors.border}` }}
        >
          <button
            type="button"
            onClick={onClose}
            className="text-xs font-bold px-3 py-2 rounded-md"
            style={{ background: "transparent", border: `1px solid ${colors.border}`, cursor: "pointer", color: colors.onSurface }}
          >Cancel</button>
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="text-xs font-bold px-4 py-2 rounded-md"
            style={{ background: colors.brand, color: "#fff", border: 0, cursor: saving ? "wait" : "pointer" }}
            data-testid="training-admin-editor-save"
          >
            {saving ? "Saving…" : (isNew ? "Create module" : "Save changes")}
          </button>
        </div>
      </div>
    </div>
  );
}

function normalize(m) {
  return {
    __new: !!m.__new,
    code: m.code || "",
    title: m.title || "",
    description: m.description || "",
    department: m.department || "pool",
    badge_label: m.badge_label || "",
    disclaimer: m.disclaimer || "",
    lessons: (m.lessons || []).map((l) => ({
      id: l.id || newId(),
      title: l.title || "",
      body_md: l.body_md || "",
      estimated_minutes: l.estimated_minutes ?? 0,
      video_url: l.video_url || "",
      order: l.order ?? 0,
      word_count: l.word_count ?? 0,
    })),
    quiz: {
      passing_score: (m.quiz && typeof m.quiz.passing_score === "number") ? m.quiz.passing_score : 0.75,
      questions: (m.quiz?.questions || []).map((q) => ({
        id: q.id || newId(),
        prompt: q.prompt || "",
        choices: (q.choices || []).map((c) => ({ id: c.id || newId(), text: c.text || "" })),
        correct_choice_ids: q.correct_choice_ids || [],
        explanation: q.explanation || "",
        chapter_ref: q.chapter_ref || null,
      })),
    },
  };
}

/* ── lessons + quiz editors ────────────────────────────────────────── */
function LessonsEditor({ lessons, onChange }) {
  const add = () => onChange([
    ...lessons,
    { id: newId(), title: "", body_md: "", estimated_minutes: 5, video_url: "", order: lessons.length, word_count: 0 },
  ]);
  const remove = (i) => onChange(lessons.filter((_, idx) => idx !== i));
  const move = (i, dir) => {
    const j = i + dir;
    if (j < 0 || j >= lessons.length) return;
    const next = [...lessons];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };
  const patch = (i, key, val) => {
    const next = [...lessons];
    next[i] = { ...next[i], [key]: val };
    onChange(next);
  };

  return (
    <FieldGroup title={`Lessons (${lessons.length})`}>
      {lessons.length === 0 ? (
        <div className="text-xs" style={{ color: colors.muted }}>No lessons yet.</div>
      ) : lessons.map((l, i) => (
        <div
          key={l.id}
          className="rounded-md p-3 space-y-2"
          style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid={`training-admin-editor-lesson-${i}`}
        >
          <div className="flex items-center gap-1">
            <span className="text-xs font-bold" style={{ color: colors.muted }}>#{i + 1}</span>
            <button type="button" onClick={() => move(i, -1)} disabled={i === 0}
              style={{ background: "transparent", border: 0, cursor: i === 0 ? "not-allowed" : "pointer", opacity: i === 0 ? 0.4 : 1 }}
              data-testid={`training-admin-editor-lesson-up-${i}`}
            ><ArrowUp size={12} color={colors.muted} /></button>
            <button type="button" onClick={() => move(i, 1)} disabled={i === lessons.length - 1}
              style={{ background: "transparent", border: 0, cursor: i === lessons.length - 1 ? "not-allowed" : "pointer", opacity: i === lessons.length - 1 ? 0.4 : 1 }}
              data-testid={`training-admin-editor-lesson-down-${i}`}
            ><ArrowDown size={12} color={colors.muted} /></button>
            <div className="flex-1" />
            <button type="button" onClick={() => remove(i)}
              className="text-xs inline-flex items-center gap-1"
              style={{ color: "#DC2626", background: "transparent", border: 0, cursor: "pointer" }}
              data-testid={`training-admin-editor-lesson-remove-${i}`}
            ><Trash2 size={11} /> Remove</button>
          </div>
          <TextInput label="Title" value={l.title} onChange={(v) => patch(i, "title", v)} />
          <TextArea label="Body (markdown)" rows={5} value={l.body_md} onChange={(v) => patch(i, "body_md", v)} />
          <div className="flex gap-3">
            <div className="w-32">
              <Label>Minutes</Label>
              <input
                type="number" min="0"
                className="w-full text-sm px-2 py-2 rounded-md"
                style={{ border: `1px solid ${colors.border}` }}
                value={l.estimated_minutes}
                onChange={(e) => patch(i, "estimated_minutes", e.target.value)}
              />
            </div>
            <div className="flex-1">
              <Label>Video URL (optional)</Label>
              <input
                type="url"
                className="w-full text-sm px-2 py-2 rounded-md"
                style={{ border: `1px solid ${colors.border}` }}
                value={l.video_url}
                onChange={(e) => patch(i, "video_url", e.target.value)}
                placeholder="https://…"
              />
            </div>
          </div>
        </div>
      ))}
      <button type="button" onClick={add}
        className="text-xs font-bold inline-flex items-center gap-1 px-3 py-1.5 rounded-md"
        style={{ background: colors.surfaceAlt, color: colors.onSurface, border: `1px solid ${colors.border}`, cursor: "pointer" }}
        data-testid="training-admin-editor-lesson-add"
      ><Plus size={11} /> Add lesson</button>
    </FieldGroup>
  );
}

function QuizEditor({ quiz, onChange }) {
  const questions = quiz.questions || [];

  const addQuestion = () => {
    const cIds = [newId(), newId(), newId(), newId()];
    onChange({
      ...quiz,
      questions: [
        ...questions,
        {
          id: newId(),
          prompt: "",
          choices: cIds.map((id) => ({ id, text: "" })),
          correct_choice_ids: [cIds[0]],
          explanation: "",
        },
      ],
    });
  };
  const removeQuestion = (qi) => {
    onChange({ ...quiz, questions: questions.filter((_, idx) => idx !== qi) });
  };
  const move = (qi, dir) => {
    const qj = qi + dir;
    if (qj < 0 || qj >= questions.length) return;
    const next = [...questions];
    [next[qi], next[qj]] = [next[qj], next[qi]];
    onChange({ ...quiz, questions: next });
  };
  const patchQuestion = (qi, patch) => {
    const next = [...questions];
    next[qi] = { ...next[qi], ...patch };
    onChange({ ...quiz, questions: next });
  };
  const patchChoice = (qi, ci, patch) => {
    const next = [...questions];
    const choices = [...(next[qi].choices || [])];
    choices[ci] = { ...choices[ci], ...patch };
    next[qi] = { ...next[qi], choices };
    onChange({ ...quiz, questions: next });
  };

  return (
    <FieldGroup title={`Quiz (${questions.length} question${questions.length === 1 ? "" : "s"})`}>
      {questions.length === 0 ? (
        <div className="text-xs" style={{ color: colors.muted }}>No quiz questions yet.</div>
      ) : questions.map((q, qi) => (
        <div
          key={q.id}
          className="rounded-md p-3 space-y-2"
          style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid={`training-admin-editor-question-${qi}`}
        >
          <div className="flex items-center gap-1">
            <span className="text-xs font-bold" style={{ color: colors.muted }}>Q{qi + 1}</span>
            <button type="button" onClick={() => move(qi, -1)} disabled={qi === 0}
              style={{ background: "transparent", border: 0, cursor: qi === 0 ? "not-allowed" : "pointer", opacity: qi === 0 ? 0.4 : 1 }}
              data-testid={`training-admin-editor-question-up-${qi}`}
            ><ArrowUp size={12} color={colors.muted} /></button>
            <button type="button" onClick={() => move(qi, 1)} disabled={qi === questions.length - 1}
              style={{ background: "transparent", border: 0, cursor: qi === questions.length - 1 ? "not-allowed" : "pointer", opacity: qi === questions.length - 1 ? 0.4 : 1 }}
              data-testid={`training-admin-editor-question-down-${qi}`}
            ><ArrowDown size={12} color={colors.muted} /></button>
            <div className="flex-1" />
            <button type="button" onClick={() => removeQuestion(qi)}
              className="text-xs inline-flex items-center gap-1"
              style={{ color: "#DC2626", background: "transparent", border: 0, cursor: "pointer" }}
              data-testid={`training-admin-editor-question-remove-${qi}`}
            ><Trash2 size={11} /> Remove</button>
          </div>
          <TextArea label="Prompt" rows={2} value={q.prompt}
            onChange={(v) => patchQuestion(qi, { prompt: v })} />
          <Label>Choices — mark the correct one</Label>
          <div className="space-y-1.5">
            {(q.choices || []).map((c, ci) => {
              const isCorrect = (q.correct_choice_ids || []).includes(c.id);
              return (
                <div key={c.id} className="flex items-center gap-2"
                     data-testid={`training-admin-editor-choice-${qi}-${ci}`}>
                  <input
                    type="radio"
                    name={`correct-${q.id}`}
                    checked={isCorrect}
                    onChange={() => patchQuestion(qi, { correct_choice_ids: [c.id] })}
                    data-testid={`training-admin-editor-choice-correct-${qi}-${ci}`}
                  />
                  <input
                    type="text"
                    className="flex-1 text-sm px-2 py-1.5 rounded-md"
                    style={{ border: `1px solid ${colors.border}` }}
                    value={c.text}
                    placeholder={`Choice ${ci + 1}`}
                    onChange={(e) => patchChoice(qi, ci, { text: e.target.value })}
                  />
                </div>
              );
            })}
          </div>
          <TextArea label="Explanation (shown after quiz)" rows={2} value={q.explanation}
            onChange={(v) => patchQuestion(qi, { explanation: v })} />
        </div>
      ))}
      <button type="button" onClick={addQuestion}
        className="text-xs font-bold inline-flex items-center gap-1 px-3 py-1.5 rounded-md"
        style={{ background: colors.surfaceAlt, color: colors.onSurface, border: `1px solid ${colors.border}`, cursor: "pointer" }}
        data-testid="training-admin-editor-question-add"
      ><Plus size={11} /> Add question</button>
    </FieldGroup>
  );
}

/* ── leaderboard ───────────────────────────────────────────────────── */
function Leaderboard() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState({ key: "certificates_earned", dir: "desc" });

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/training/leaderboard");
        setRows(Array.isArray(r) ? r : []);
      } catch (e) {
        setError(e?.message || "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const sorted = useMemo(() => {
    const s = [...rows];
    s.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      const an = av == null ? -Infinity : (typeof av === "number" ? av : String(av).toLowerCase());
      const bn = bv == null ? -Infinity : (typeof bv === "number" ? bv : String(bv).toLowerCase());
      if (an < bn) return sort.dir === "asc" ? -1 : 1;
      if (an > bn) return sort.dir === "asc" ? 1 : -1;
      return 0;
    });
    return s;
  }, [rows, sort]);

  const bump = (key) => {
    setSort((s) => s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" });
  };

  const csv = () => {
    const header = ["User","Email","Department","Role","Modules Completed","Quizzes Passed","Attempts","Certificates","Avg Score %"];
    const rows2 = sorted.map((r) => [
      r.name, r.email || "", r.department || "", r.role || "",
      r.modules_completed, r.quizzes_passed, r.quiz_attempts,
      r.certificates_earned, r.avg_score == null ? "" : Math.round(r.avg_score * 100),
    ]);
    const escape = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const body = [header, ...rows2].map((row) => row.map(escape).join(",")).join("\r\n");
    const blob = new Blob([body], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `training-leaderboard-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  };

  const COLS = [
    { k: "name", label: "Tech" },
    { k: "department", label: "Dept" },
    { k: "modules_completed", label: "Modules" },
    { k: "quizzes_passed", label: "Passed" },
    { k: "quiz_attempts", label: "Attempts" },
    { k: "certificates_earned", label: "Certs" },
    { k: "avg_score", label: "Avg %" },
  ];

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-xs" style={{ color: colors.muted }}>
          Last 90 days. Sort by any column.
        </div>
        <button
          type="button"
          onClick={csv}
          className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
          style={{ background: colors.brand, color: "#fff", border: 0, cursor: "pointer" }}
          data-testid="training-leaderboard-csv"
        >
          <Download size={12} /> Export CSV
        </button>
      </div>
      {loading ? (
        <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>
      ) : error ? (
        <div className="text-sm" style={{ color: "#DC2626" }}>{error}</div>
      ) : (
        <div className="rounded-lg overflow-hidden" style={{ background: "#fff", border: `1px solid ${colors.border}` }}>
          <table className="w-full text-xs" data-testid="training-leaderboard-table">
            <thead style={{ background: colors.surfaceAlt }}>
              <tr>
                {COLS.map((c) => (
                  <th
                    key={c.k}
                    className="text-left px-3 py-2 cursor-pointer select-none"
                    style={{ color: colors.muted }}
                    onClick={() => bump(c.k)}
                    data-testid={`training-leaderboard-col-${c.k}`}
                  >
                    {c.label}
                    {sort.key === c.k ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.length === 0 ? (
                <tr>
                  <td colSpan={COLS.length} className="px-3 py-4 text-center"
                      style={{ color: colors.muted }}
                      data-testid="training-leaderboard-empty">
                    No training activity in the last 90 days.
                  </td>
                </tr>
              ) : sorted.map((r) => (
                <tr key={r.user_id} data-testid={`training-leaderboard-row-${r.user_id}`}>
                  <td className="px-3 py-2 font-bold" style={{ color: colors.onSurface }}>{r.name}</td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>{r.department || "—"}</td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>{r.modules_completed}</td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>{r.quizzes_passed}</td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>{r.quiz_attempts}</td>
                  <td className="px-3 py-2 font-bold" style={{ color: r.certificates_earned > 0 ? "#059669" : colors.muted }}>
                    {r.certificates_earned}
                  </td>
                  <td className="px-3 py-2" style={{ color: colors.muted }}>
                    {r.avg_score == null ? "—" : `${Math.round(r.avg_score * 100)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ── tiny form primitives ──────────────────────────────────────────── */
function Label({ children }) {
  return (
    <div className="text-[10px] uppercase font-bold mb-1" style={{ color: colors.muted, letterSpacing: 0.4 }}>
      {children}
    </div>
  );
}
function FieldGroup({ title, children }) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>{title}</div>
      {children}
    </div>
  );
}
function TextInput({ label, value, onChange, placeholder, disabled, testid }) {
  return (
    <div>
      {label ? <Label>{label}</Label> : null}
      <input
        type="text"
        className="w-full text-sm px-2 py-2 rounded-md"
        style={{ border: `1px solid ${colors.border}`, background: disabled ? colors.surfaceAlt : "#fff" }}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testid}
      />
    </div>
  );
}
function TextArea({ label, value, onChange, rows = 3, testid }) {
  return (
    <div>
      {label ? <Label>{label}</Label> : null}
      <textarea
        className="w-full text-sm px-2 py-2 rounded-md"
        style={{ border: `1px solid ${colors.border}` }}
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testid}
      />
    </div>
  );
}
