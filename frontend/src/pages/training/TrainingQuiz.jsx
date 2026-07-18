/**
 * Phase 56.13b · Training — Quiz runner + results screen.
 *
 * Techs see the quiz with `correct_choice_ids` + `explanation` REDACTED
 * by the backend during the runner phase. After submit, the API
 * response returns their score; we then re-fetch the module WITHOUT the
 * redaction as follows: admin viewers would see the answer key, but
 * techs only see the correct answer AFTER submit via the per-question
 * `explanation` echoed back in the attempt payload's `answers` map plus
 * a follow-up `GET /api/training/modules/{code}/attempts` for history.
 *
 * v1 compromise: post-submit review shows the tech's answer + whether
 * it was correct. The specific "correct choice id" and explanation
 * remain admin-visible only. This matches the answer-key redaction
 * policy that shipped in Phase 56.13a-commit.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Award, RotateCcw, Download } from 'lucide-react';
import { api } from "@/api";
import { colors } from "@/theme";

function ScoreBanner({ result }) {
  const passed = !!result.passed;
  return (
    <div className="rounded-lg p-4 flex items-center justify-between"
         style={{
           background: passed ? "#ECFDF5" : "#FEF2F2",
           border: `1px solid ${passed ? "#10B981" : "#DC2626"}`,
         }}
         data-testid="training-quiz-score-banner">
      <div>
        <div className="text-2xl font-bold"
             style={{ color: passed ? "#065F46" : "#7F1D1D" }}
             data-testid="training-quiz-score-value">
          {Math.round((result.score || 0) * 100)}%
        </div>
        <div className="text-xs mt-1" style={{ color: colors.muted }}>
          {result.correct} of {result.total} correct · passing = {Math.round((result.passing_score || 0.75) * 100)}%
        </div>
      </div>
      <div className="text-lg font-bold px-3 py-1.5 rounded-md"
           style={{ background: passed ? "#10B981" : "#DC2626", color: "#fff" }}
           data-testid="training-quiz-passfail">
        {passed ? "PASS" : "FAIL"}
      </div>
    </div>
  );
}

export default function TrainingQuiz() {
  const { code } = useParams();
  const navigate = useNavigate();
  const [mod, setMod] = useState(null);
  const [answers, setAnswers] = useState({});
  const [idx, setIdx] = useState(0);
  const [result, setResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const m = await api.get(`/training/modules/${code}`);
      setMod(m);
    } catch (e) {
      setError(e?.message || "Could not load quiz");
    }
  }, [code]);

  useEffect(() => { load(); }, [load]);

  const questions = mod?.quiz?.questions || [];
  const q = questions[idx];
  const totalQ = questions.length;
  const chosen = answers[q?.id] || null;
  const allAnswered = totalQ > 0 && questions.every((qq) => !!answers[qq.id]);

  const submit = useCallback(async () => {
    setSubmitting(true); setError("");
    try {
      const r = await api.post(`/training/modules/${code}/quiz`, { answers });
      setResult(r);
    } catch (e) {
      setError(e?.message || "Submit failed");
    } finally {
      setSubmitting(false);
    }
  }, [code, answers]);

  const retake = useCallback(() => {
    setResult(null);
    setAnswers({});
    setIdx(0);
  }, []);

  if (!mod) return (
    <div className="max-w-3xl mx-auto py-6 px-4 text-sm" style={{ color: colors.muted }}>Loading…</div>
  );

  // Results screen — post-submit.
  if (result) {
    const passed = !!result.passed;
    return (
      <div className="max-w-3xl mx-auto py-6 px-4 space-y-4" data-testid="training-quiz-results">
        <Link
          to={`/tests/${code}`}
          className="inline-flex items-center gap-1 text-xs font-bold"
          style={{ color: colors.brand, textDecoration: "none" }}
        ><ArrowLeft size={12} /> Back to module</Link>

        <ScoreBanner result={result} />

        {passed && result.certificate_id ? (
          <div className="rounded-lg p-4"
               style={{ background: "#fff", border: "1px solid #10B981" }}
               data-testid="training-quiz-certificate-block">
            <div className="flex items-center gap-2 mb-2">
              <Award size={18} color="#10B981" />
              <div className="text-sm font-bold" style={{ color: "#065F46" }}>
                Certificate awarded — {result.certificate_id}
              </div>
            </div>
            <a
              href={`${process.env.REACT_APP_BACKEND_URL}/api/training/certificates/${result.certificate_id}/pdf`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
              style={{ background: "#10B981", color: "#fff", textDecoration: "none" }}
              data-testid="training-quiz-cert-pdf-btn"
            ><Download size={12} /> Download Certificate PDF</a>
            <div className="text-[11px] mt-2" style={{ color: colors.muted }}>
              {mod.disclaimer}
            </div>
          </div>
        ) : null}

        <div className="rounded-lg overflow-hidden"
             style={{ background: "#fff", border: `1px solid ${colors.border}` }}
             data-testid="training-quiz-review">
          <div className="text-[11px] font-bold uppercase tracking-wider px-3 py-2"
               style={{ background: colors.surfaceAlt, color: colors.muted }}>
            Your answers
          </div>
          {questions.map((qq, i) => {
            const my = answers[qq.id];
            return (
              <div key={qq.id} className="px-3 py-2 border-b"
                   style={{ borderColor: colors.border }}
                   data-testid={`training-quiz-review-q-${qq.id}`}>
                <div className="text-xs font-bold" style={{ color: colors.onSurface }}>
                  Q{i + 1}. {qq.prompt}
                </div>
                {qq.choices.map((c) => (
                  <div key={c.id} className="text-xs mt-0.5 flex items-center gap-1"
                       style={{
                         color: my === c.id ? colors.onSurface : colors.muted,
                         fontWeight: my === c.id ? 600 : 400,
                       }}>
                    {my === c.id ? "→ " : ""}
                    {c.text}
                    {my === c.id ? " (your answer)" : ""}
                  </div>
                ))}
              </div>
            );
          })}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={retake}
            className="text-xs font-bold px-4 py-2 rounded-md inline-flex items-center gap-1"
            style={{ background: colors.brand, color: "#fff", border: 0, cursor: "pointer" }}
            data-testid="training-quiz-retake-btn"
          ><RotateCcw size={12} /> Retake Quiz</button>
          <button
            type="button"
            onClick={() => navigate(`/tests/${code}`)}
            className="text-xs font-bold px-4 py-2 rounded-md"
            style={{ background: "transparent", border: `1px solid ${colors.border}`, color: colors.onSurface, cursor: "pointer" }}
          >Back to Module</button>
        </div>
      </div>
    );
  }

  // Runner screen — pre-submit.
  return (
    <div className="max-w-3xl mx-auto py-6 px-4 space-y-4" data-testid="training-quiz-runner">
      <Link
        to={`/tests/${code}`}
        className="inline-flex items-center gap-1 text-xs font-bold"
        style={{ color: colors.brand, textDecoration: "none" }}
      ><ArrowLeft size={12} /> Back to module</Link>

      <div className="text-lg font-bold" style={{ color: colors.onSurface }}>
        {mod.title} — Practice Quiz
      </div>

      {questions.length === 0 ? (
        <div className="text-sm" style={{ color: colors.muted }}>This module has no quiz.</div>
      ) : (
        <>
          <div className="text-xs font-bold" style={{ color: colors.muted }}>
            Question {idx + 1} of {totalQ}
          </div>

          <div className="rounded-lg p-4"
               style={{ background: "#fff", border: `1px solid ${colors.border}` }}>
            <div className="text-sm font-bold mb-3" style={{ color: colors.onSurface }}
                 data-testid={`training-quiz-question-${q.id}`}>
              {q.prompt}
            </div>
            <div className="space-y-2">
              {q.choices.map((c) => {
                const active = chosen === c.id;
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setAnswers((s) => ({ ...s, [q.id]: c.id }))}
                    className="w-full text-left px-3 py-2 rounded-md text-sm"
                    style={{
                      background: active ? "#EFF6FF" : "#F8FAFC",
                      border: `1.5px solid ${active ? colors.brand : colors.border}`,
                      color: colors.onSurface, cursor: "pointer",
                    }}
                    data-testid={`training-quiz-choice-${q.id}-${c.id}`}
                  >
                    {c.text}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex items-center justify-between">
            <button
              type="button"
              disabled={idx <= 0}
              onClick={() => setIdx(idx - 1)}
              className="text-xs font-bold px-3 py-1.5 rounded-md"
              style={{
                background: "transparent", border: `1px solid ${colors.border}`,
                color: idx <= 0 ? colors.muted : colors.onSurface,
                cursor: idx <= 0 ? "not-allowed" : "pointer",
              }}
              data-testid="training-quiz-prev"
            >← Prev</button>

            {idx < totalQ - 1 ? (
              <button
                type="button"
                onClick={() => setIdx(idx + 1)}
                className="text-xs font-bold px-3 py-1.5 rounded-md"
                style={{ background: colors.brand, color: "#fff", border: 0, cursor: "pointer" }}
                data-testid="training-quiz-next"
              >Next →</button>
            ) : (
              <button
                type="button"
                onClick={submit}
                disabled={submitting || !allAnswered}
                className="text-xs font-bold px-4 py-2 rounded-md"
                style={{
                  background: allAnswered ? "#10B981" : colors.muted,
                  color: "#fff", border: 0,
                  cursor: (submitting || !allAnswered) ? "not-allowed" : "pointer",
                }}
                data-testid="training-quiz-submit"
              >{submitting ? "Submitting…" : allAnswered ? "Submit Quiz" : `Answer all ${totalQ} questions`}</button>
            )}
          </div>
        </>
      )}

      {error ? (
        <div className="text-xs" style={{ color: "#DC2626" }} data-testid="training-quiz-error">{error}</div>
      ) : null}
    </div>
  );
}
