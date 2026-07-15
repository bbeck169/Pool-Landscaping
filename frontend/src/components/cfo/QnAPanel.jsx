/**
 * Phase 33 · Step 2 — Ask AI CFO (NL Q&A panel, web).
 *
 * Sits below the CFO dashboard. Sends `POST /api/cfo/qna` with the
 * question + the same period the user picked for the dashboard, then
 * renders the Claude answer honestly (dims + `mocked-badge` when the
 * backend flags `mocked:true`). History drawer reads
 * `GET /api/cfo/qna/history?limit=20` (bare array — normalize here).
 * Quota-exceeded soft response surfaces a banner with a "Force submit"
 * retry that re-fires with `?force=true`.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Sparkles, Send, ChevronDown, ChevronUp, Loader2, Clock, RotateCw,
} from "lucide-react";
import { api } from "@/api";

const c = {
  brand: "#0EA5E9", brandDark: "#075985",
  border: "#E2E8F0", muted: "#64748B", onSurface: "#0F172A",
  surface: "#FFFFFF", surfaceAlt: "#F8FAFC",
  ok: "#059669", okBg: "#D1FAE5",
  warn: "#B45309", warnBg: "#FEF3C7",
  danger: "#B91C1C", dangerBg: "#FEE2E2",
};

function MockedBadge({ reason }) {
  return (
    <span
      title={reason || "Mocked — data source not wired"}
      className="ml-1 inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase"
      style={{ background: c.warnBg, color: c.warn }}
      data-testid="mocked-badge"
    >mocked</span>
  );
}

const relTime = (iso) => {
  if (!iso) return "";
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  return new Date(iso).toLocaleDateString();
};

export default function QnAPanel({ period, customStart, customEnd, onUsageChange }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null); // {answer, mocked, reason, tokens_used, question, created_at}
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [quotaHit, setQuotaHit] = useState(null); // usage snapshot when soft-blocked
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const abortRef = useRef(null);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const rows = await api.get(`/cfo/qna/history?limit=20`);
      setHistory(Array.isArray(rows) ? rows : rows?.items || []);
    } catch (_) { /* silent */ }
    finally { setHistoryLoading(false); }
  }, []);
  useEffect(() => { if (historyOpen) loadHistory(); }, [historyOpen, loadHistory]);

  const submit = async (force = false) => {
    if (!question.trim() || busy) return;
    setBusy(true); setErr(""); setQuotaHit(null); setAnswer(null);
    try {
      const body = { question: question.trim(), period };
      if (period === "custom" && customStart) body.start = customStart;
      if (period === "custom" && customEnd)   body.end   = customEnd;
      const path = `/cfo/qna${force ? "?force=true" : ""}`;
      const r = await api.post(path, body);
      if (r?.error === "quota_exceeded") {
        setQuotaHit(r.usage || null);
        return;
      }
      setAnswer({
        answer: r.answer || "",
        mocked: !!r.mocked,
        reason: r.reason,
        tokens_used: r.tokens_used || 0,
        question: question.trim(),
        history_id: r.history_id,
        created_at: new Date().toISOString(),
      });
      onUsageChange?.();
      if (historyOpen) loadHistory();
    } catch (e) {
      setErr(e?.message || "Q&A request failed.");
    } finally {
      setBusy(false);
    }
  };

  const loadFromHistory = (row) => {
    setAnswer({
      answer: row.answer || "",
      mocked: !!row.mocked,
      reason: row.reason,
      tokens_used: row.tokens_used || 0,
      question: row.question,
      history_id: row.id,
      created_at: row.created_at,
      readonly: true,
    });
    setQuestion(row.question || "");
  };

  return (
    <div className="rounded-xl p-4 mb-6"
         style={{ background: c.surface, border: `1px solid ${c.border}` }}
         data-testid="cfo-qna-panel">
      <div className="flex items-center gap-2 mb-3">
        <Sparkles size={16} color={c.brand} />
        <div className="text-sm font-bold" style={{ color: c.onSurface }}>Ask AI CFO</div>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => setHistoryOpen((x) => !x)}
          className="inline-flex items-center gap-1 text-xs font-semibold"
          style={{ background: "transparent", border: 0, cursor: "pointer", color: c.muted }}
          data-testid="cfo-qna-history-toggle"
        >
          {historyOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />} History
        </button>
      </div>

      <textarea
        rows={2}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Ask a question about your finances… e.g. How much did chemical costs go up last quarter?"
        className="w-full px-3 py-2 rounded-md text-sm mb-2"
        style={{ border: `1px solid ${c.border}`, background: c.surface, color: c.onSurface,
                  resize: "vertical" }}
        data-testid="cfo-qna-input"
        disabled={busy}
      />
      <div className="flex items-center gap-2">
        <div className="text-xs" style={{ color: c.muted }}>
          Context period: <b>{period.toUpperCase()}</b>
        </div>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => submit(false)}
          disabled={busy || !question.trim()}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-bold"
          style={{ background: c.brand, color: "#fff", border: 0,
                    cursor: busy ? "wait" : "pointer",
                    opacity: (busy || !question.trim()) ? 0.6 : 1 }}
          data-testid="cfo-qna-submit"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          Ask
        </button>
      </div>

      {err ? (
        <div className="mt-3 text-xs px-2 py-2 rounded"
             style={{ background: c.dangerBg, color: c.danger }}
             data-testid="cfo-qna-error">{err}</div>
      ) : null}

      {quotaHit ? (
        <div className="mt-3 text-xs px-3 py-2 rounded flex items-center gap-2"
             style={{ background: c.warnBg, color: c.warn }}
             data-testid="cfo-qna-quota-banner">
          <span style={{ flex: 1 }}>
            Daily quota reached ({quotaHit.request_count}/{quotaHit.quota}). Retry with
            force to override, or wait until tomorrow.
          </span>
          <button
            onClick={() => submit(true)}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-bold"
            style={{ background: c.warn, color: "#fff", border: 0, cursor: "pointer" }}
            data-testid="cfo-qna-force-submit"
          >
            <RotateCw size={12} /> Force submit
          </button>
        </div>
      ) : null}

      {/* Answer area */}
      {busy ? (
        <div className="mt-3 p-4 rounded-lg flex items-center justify-center"
             style={{ background: c.surfaceAlt, border: `1px dashed ${c.border}` }}
             data-testid="cfo-qna-loading">
          <Loader2 size={18} className="animate-spin" color={c.brand} />
          <span className="ml-2 text-xs" style={{ color: c.muted }}>Claude is thinking…</span>
        </div>
      ) : answer ? (
        <div className="mt-3 rounded-lg p-3 text-sm"
             style={{ background: c.surfaceAlt, border: `1px solid ${c.border}` }}
             data-testid="cfo-qna-answer">
          <div className="text-[11px] font-bold uppercase tracking-wider mb-1"
               style={{ color: c.muted }}>
            Q: {answer.question}
            {answer.mocked ? <MockedBadge reason={answer.reason} /> : null}
            {answer.readonly ? (
              <span className="ml-2 text-[10px] font-bold" style={{ color: c.muted }}>
                · from history
              </span>
            ) : null}
          </div>
          {answer.mocked && answer.reason ? (
            <div className="text-[11px] px-2 py-1 rounded mb-2"
                 style={{ background: c.warnBg, color: c.warn }}
                 data-testid="cfo-qna-mocked-reason">
              LLM unavailable — {answer.reason}
            </div>
          ) : null}
          <div className={answer.mocked ? "opacity-70" : ""}
               style={{ color: c.onSurface, whiteSpace: "pre-wrap" }}>
            {answer.answer || <span style={{ color: c.muted, fontStyle: "italic" }}>
              (No answer text returned.)
            </span>}
          </div>
          <div className="text-[10px] mt-2" style={{ color: c.muted }}>
            {relTime(answer.created_at)} · Tokens: {answer.tokens_used}
          </div>
        </div>
      ) : null}

      {/* History drawer */}
      {historyOpen ? (
        <div className="mt-4 border-t pt-3" style={{ borderColor: c.border }}
             data-testid="cfo-qna-history-list">
          <div className="text-[10px] font-bold uppercase tracking-wider mb-2"
               style={{ color: c.muted }}>
            History (latest 20)
          </div>
          {historyLoading ? (
            <div className="flex items-center gap-2 text-xs" style={{ color: c.muted }}>
              <Loader2 size={12} className="animate-spin" /> Loading…
            </div>
          ) : history.length === 0 ? (
            <div className="text-xs" style={{ color: c.muted }} data-testid="cfo-qna-history-empty">
              No questions asked yet — ask something above.
            </div>
          ) : history.map((row) => (
            <button
              key={row.id}
              onClick={() => loadFromHistory(row)}
              className="w-full flex items-center gap-2 text-left px-2 py-2 rounded"
              style={{ background: "transparent", border: 0, cursor: "pointer",
                        borderBottom: `1px solid ${c.border}` }}
              data-testid="cfo-qna-history-item"
            >
              <Clock size={11} color={c.muted} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="text-xs truncate" style={{ color: c.onSurface }}>
                  {row.question}
                </div>
                <div className="text-[10px]" style={{ color: c.muted }}>
                  {relTime(row.created_at)} · {row.tokens_used || 0} tokens
                  {row.mocked ? " · mocked" : ""}
                </div>
              </div>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
