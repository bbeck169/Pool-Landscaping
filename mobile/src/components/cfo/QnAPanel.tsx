/**
 * Phase 34c · Mobile Ask AI CFO (Q&A) panel.
 *
 * Mirror of `/app/frontend/src/components/cfo/QnAPanel.jsx`. Sends
 * `POST /api/cfo/qna` with the question + the same period the parent
 * dashboard is on. History drawer reads `GET /api/cfo/qna/history?limit=20`
 * (bare array — normalised here). Honest rendering — dims the answer
 * and shows a yellow banner when the backend flags `mocked:true`.
 * Quota soft response surfaces a "Force submit" retry that re-fires
 * with `?force=true`.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, Pressable, ScrollView, ActivityIndicator, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

type QnAAnswer = {
  answer: string;
  mocked: boolean;
  reason?: string;
  tokens_used: number;
  question: string;
  history_id?: string;
  created_at: string;
  readonly?: boolean;
};

type Usage = { request_count?: number; quota?: number };

const relTime = (iso?: string | null) => {
  if (!iso) return "";
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  return new Date(iso).toLocaleDateString();
};

export type QnAPanelProps = {
  period: "mtd" | "qtd" | "ytd";
  onUsageChange?: () => void;
  onContextSnapshot?: (snap: any) => void;
};

export default function QnAPanel({ period, onUsageChange, onContextSnapshot }: QnAPanelProps) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<QnAAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [quotaHit, setQuotaHit] = useState<Usage | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const rows: any = await api.get(`/cfo/qna/history?limit=20`);
      setHistory(Array.isArray(rows) ? rows : rows?.items || []);
    } catch (_) { /* silent */ }
    finally { setHistoryLoading(false); }
  }, []);
  useEffect(() => { if (historyOpen) loadHistory(); }, [historyOpen, loadHistory]);

  const submit = async (force = false) => {
    if (!question.trim() || busy) return;
    setBusy(true); setErr(""); setQuotaHit(null); setAnswer(null);
    try {
      const path = `/cfo/qna${force ? "?force=true" : ""}`;
      const r: any = await api.post(path, { question: question.trim(), period });
      if (r?.error === "quota_exceeded") { setQuotaHit(r.usage || {}); return; }
      setAnswer({
        answer: r.answer || "",
        mocked: !!r.mocked,
        reason: r.reason,
        tokens_used: r.tokens_used || 0,
        question: question.trim(),
        history_id: r.history_id,
        created_at: new Date().toISOString(),
      });
      if (r.context_snapshot) onContextSnapshot?.(r.context_snapshot);
      onUsageChange?.();
      if (historyOpen) loadHistory();
    } catch (e: any) {
      setErr(e?.message || "Q&A request failed.");
    } finally {
      setBusy(false);
    }
  };

  const loadFromHistory = (row: any) => {
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
    <View style={styles.card} testID="cfo-qna-panel">
      <View style={styles.headerRow}>
        <Ionicons name="sparkles-outline" size={16} color={colors.brand} />
        <Text style={styles.headerTitle}>Ask AI CFO</Text>
        <View style={{ flex: 1 }} />
        <Pressable
          onPress={() => setHistoryOpen((x) => !x)}
          testID="cfo-qna-history-toggle"
          style={styles.historyBtn}
          hitSlop={6}
        >
          <Ionicons name={historyOpen ? "chevron-up" : "chevron-down"} size={12} color={colors.muted} />
          <Text style={styles.historyBtnText}>History</Text>
        </Pressable>
      </View>

      <AppTextInput
        multiline
        numberOfLines={4}
        editable={!busy}
        value={question}
        onChangeText={setQuestion}
        placeholder="Ask a question about your finances..."
        placeholderTextColor={colors.muted}
        style={styles.input}
        testID="cfo-qna-input"
      />
      <View style={styles.actionRow}>
        <Text style={styles.hint}>
          Context period: <Text style={styles.hintStrong}>{period.toUpperCase()}</Text>
        </Text>
        <View style={{ flex: 1 }} />
        <Pressable
          onPress={() => submit(false)}
          disabled={busy || !question.trim()}
          style={[styles.submitBtn, (busy || !question.trim()) && styles.submitBtnDisabled]}
          testID="cfo-qna-submit"
        >
          {busy
            ? <ActivityIndicator size="small" color="#fff" />
            : <Ionicons name="send" size={12} color="#fff" />}
          <Text style={styles.submitText}>Ask</Text>
        </Pressable>
      </View>

      {err ? (
        <View style={styles.errBox} testID="cfo-qna-error">
          <Text style={styles.errText}>{err}</Text>
        </View>
      ) : null}

      {quotaHit ? (
        <View style={styles.quotaBox} testID="cfo-qna-quota-banner">
          <Text style={styles.quotaText}>
            Daily quota reached ({quotaHit.request_count}/{quotaHit.quota}). Retry with force to override.
          </Text>
          <Pressable
            onPress={() => submit(true)}
            style={styles.forceBtn}
            testID="cfo-qna-force-submit"
          >
            <Ionicons name="refresh" size={11} color="#fff" />
            <Text style={styles.forceText}>Force submit</Text>
          </Pressable>
        </View>
      ) : null}

      {busy ? (
        <View style={styles.loadingBox} testID="cfo-qna-loading">
          <ActivityIndicator size="small" color={colors.brand} />
          <Text style={styles.loadingText}>Claude is thinking…</Text>
        </View>
      ) : answer ? (
        <View style={styles.answerBox} testID="cfo-qna-answer">
          <Text style={styles.answerQ}>
            Q: {answer.question}
            {answer.mocked ? <Text style={styles.mockedInline}>  mocked</Text> : null}
            {answer.readonly ? <Text style={styles.fromHistoryInline}>  · from history</Text> : null}
          </Text>
          {answer.mocked && answer.reason ? (
            <View style={styles.mockedReason} testID="cfo-qna-mocked-reason">
              <Text style={styles.mockedReasonText}>LLM unavailable — {answer.reason}</Text>
            </View>
          ) : null}
          <Text style={[styles.answerText, answer.mocked && { opacity: 0.7 }]}>
            {answer.answer || "(No answer text returned.)"}
          </Text>
          <Text style={styles.answerFoot}>
            {relTime(answer.created_at)} · Tokens: {answer.tokens_used}
          </Text>
        </View>
      ) : null}

      {historyOpen ? (
        <View style={styles.historyList} testID="cfo-qna-history-list">
          <Text style={styles.historyTitle}>History (latest 20)</Text>
          {historyLoading ? (
            <View style={styles.historyLoading}>
              <ActivityIndicator size="small" color={colors.brand} />
              <Text style={styles.historyLoadingText}>Loading…</Text>
            </View>
          ) : history.length === 0 ? (
            <Text style={styles.historyEmpty} testID="cfo-qna-history-empty">
              No questions asked yet — ask something above.
            </Text>
          ) : (
            <ScrollView style={{ maxHeight: 220 }}>
              {history.map((row) => (
                <Pressable
                  key={row.id}
                  onPress={() => loadFromHistory(row)}
                  style={styles.historyItem}
                  testID="cfo-qna-history-item"
                >
                  <Ionicons name="time-outline" size={11} color={colors.muted} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.historyItemQ} numberOfLines={2}>{row.question}</Text>
                    <Text style={styles.historyItemMeta}>
                      {relTime(row.created_at)} · {row.tokens_used || 0} tokens
                      {row.mocked ? " · mocked" : ""}
                    </Text>
                  </View>
                </Pressable>
              ))}
            </ScrollView>
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    backgroundColor: colors.surface, padding: spacing.md, marginTop: spacing.md,
  },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: spacing.sm },
  headerTitle: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  historyBtn: { flexDirection: "row", alignItems: "center", gap: 4 },
  historyBtnText: { fontFamily: font.semibold, fontSize: 11, color: colors.muted },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: spacing.sm,
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface,
    textAlignVertical: "top", minHeight: 88, marginBottom: 8,
    backgroundColor: colors.surface,
  },
  actionRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  hint: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  hintStrong: { fontFamily: font.bold, color: colors.onSurface },
  submitBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brand, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: 8,
  },
  submitBtnDisabled: { opacity: 0.5 },
  submitText: { fontFamily: font.bold, fontSize: 12, color: "#fff" },
  errBox: {
    backgroundColor: "#FEE2E2", borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 6, marginTop: 8,
  },
  errText: { fontFamily: font.semibold, fontSize: 11, color: "#B91C1C" },
  quotaBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#FEF3C7", borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 8, marginTop: 8,
  },
  quotaText: { flex: 1, fontFamily: font.regular, fontSize: 11, color: "#B45309" },
  forceBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#B45309", borderRadius: radius.sm,
    paddingHorizontal: 8, paddingVertical: 4,
  },
  forceText: { fontFamily: font.bold, fontSize: 10, color: "#fff" },
  loadingBox: {
    marginTop: 12, borderRadius: radius.sm, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, borderStyle: "dashed",
    backgroundColor: colors.surfaceSecondary || "#F8FAFC",
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  loadingText: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  answerBox: {
    marginTop: 12, borderRadius: radius.sm, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary || "#F8FAFC",
  },
  answerQ: {
    fontFamily: font.bold, fontSize: 10, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 6,
  },
  mockedInline: {
    fontFamily: font.bold, fontSize: 9, color: "#B45309",
    backgroundColor: "#FEF3C7",
  },
  fromHistoryInline: { fontFamily: font.bold, fontSize: 10, color: colors.muted },
  mockedReason: {
    backgroundColor: "#FEF3C7", borderRadius: radius.sm,
    paddingHorizontal: 8, paddingVertical: 6, marginBottom: 6,
  },
  mockedReasonText: { fontFamily: font.regular, fontSize: 11, color: "#B45309" },
  answerText: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface,
    lineHeight: 20,
  },
  answerFoot: {
    fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 6,
  },
  historyList: {
    marginTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.border,
    paddingTop: spacing.sm,
  },
  historyTitle: {
    fontFamily: font.bold, fontSize: 10, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 6,
  },
  historyLoading: { flexDirection: "row", alignItems: "center", gap: 6 },
  historyLoadingText: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  historyEmpty: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  historyItem: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  historyItemQ: { fontFamily: font.semibold, fontSize: 12, color: colors.onSurface },
  historyItemMeta: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 2 },
});
