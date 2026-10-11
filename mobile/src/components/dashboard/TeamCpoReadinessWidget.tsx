/**
 * Phase 39C · mobile port of web `admin/TeamCpoReadinessWidget.jsx`.
 *
 * Reads (parallel): GET /training/certificates/admin, GET /team,
 * GET /training/progress/admin?module_code=cpo-prep → per pool-tech
 * Certified / In progress / Not started.
 *
 * Write: POST /training/nudge-non-starters {module_code, message,
 * include_email} — a single bulk nudge (web has no per-member nudge).
 * Optimistic: non-starter rows flip to "Nudged" + button locks while
 * in flight; rolled back (+ error toast) on failure.
 *
 * Gate: backend is admin / super_admin only; parent mounts accordingly.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Switch } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { Sheet } from "@/src/components/ui";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { useToast } from "@/src/components/ToastProvider";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export const DEFAULT_NUDGE_MESSAGE =
  "The CPO Prep training module is now live in your Tests menu. It takes ~2 hours and earns you a completion certificate. Let me know if you have questions.";

type Row = { id: string; name: string; status: "Certified" | "In progress" | "Not started"; score: number | null; awarded_at: string | null; lessons_completed: number };

export function buildCpoRows(certs: any, users: any, progress: any): Row[] {
  const certBy = new Map((Array.isArray(certs) ? certs : []).filter((c: any) => c.module_code === "cpo-prep").map((c: any) => [c.user_id, c]));
  const progBy = new Map((Array.isArray(progress) ? progress : []).map((p: any) => [p.user_id, p]));
  const techs = (Array.isArray(users) ? users : []).filter((u: any) => {
    const dept = String(u.department || "").toLowerCase();
    return String(u.role || "").toLowerCase() === "technician" && (dept === "pool" || dept === "both" || dept === "");
  });
  return techs.map((t: any) => {
    const cert: any = certBy.get(t.id);
    const p: any = progBy.get(t.id);
    const lessons = (p?.lessons_completed || []).length;
    const status = cert ? "Certified" : lessons > 0 ? "In progress" : "Not started";
    return { id: t.id, name: t.name || t.email, status, score: cert ? Math.round((cert.quiz_score || 0) * 100) : null, awarded_at: cert?.awarded_at || null, lessons_completed: lessons };
  });
}

const STATUS_COLOR: Record<string, string> = { Certified: "#059669", "In progress": "#B45309", "Not started": colors.muted };

function CpoRow({ r, nudged }: { r: Row; nudged: boolean }) {
  return (
    <View style={s.row} testID={`cpo-readiness-row-${r.id}`}>
      <View style={{ flex: 1 }}>
        <Text style={s.rowName} numberOfLines={1}>{r.name}</Text>
        <Text style={[s.rowStatus, { color: STATUS_COLOR[r.status] }]}>
          {r.status}{r.status === "In progress" ? ` (${r.lessons_completed} lessons)` : ""}
        </Text>
      </View>
      {nudged ? <View style={s.nudgedChip} testID={`cpo-readiness-row-${r.id}-nudged`}><Text style={s.nudgedText}>Nudged</Text></View> : null}
      <View style={s.rowRight}>
        <Text style={s.rowMeta}>{r.score != null ? `${r.score}%` : "—"}</Text>
        <Text style={s.rowMeta}>{r.awarded_at ? r.awarded_at.slice(0, 10) : "—"}</Text>
      </View>
    </View>
  );
}

export default function TeamCpoReadinessWidget() {
  const router = useRouter();
  const { showToast } = useToast();
  const [expand, setExpand] = useState(false);
  const [state, setState] = useState<{ loading: boolean; error: string; rows: Row[] }>({ loading: true, error: "", rows: [] });
  const [sheet, setSheet] = useState(false);
  const [message, setMessage] = useState(DEFAULT_NUDGE_MESSAGE);
  const [includeEmail, setIncludeEmail] = useState(false);
  const [sending, setSending] = useState(false);
  const [nudgedIds, setNudgedIds] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [certs, users, progress] = await Promise.all([
        api.get("/training/certificates/admin"),
        api.get("/team"),
        api.get("/training/progress/admin?module_code=cpo-prep"),
      ]);
      setState({ loading: false, error: "", rows: buildCpoRows(certs, users, progress) });
    } catch (e: any) {
      setState({ loading: false, error: e?.message || "Failed to load", rows: [] });
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const certified = state.rows.filter((r) => r.status === "Certified").length;
  const inProg = state.rows.filter((r) => r.status === "In progress").length;
  const total = state.rows.length;
  const nonStarters = state.rows.filter((r) => r.status === "Not started");
  const notStarted = nonStarters.length;
  const allNudged = notStarted > 0 && nonStarters.every((r) => nudgedIds.has(r.id));

  const openNudge = () => { setResult(null); setErr(""); setSheet(true); };

  const sendNudge = async () => {
    const prev = nudgedIds;
    setNudgedIds(new Set([...prev, ...nonStarters.map((r) => r.id)])); // optimistic
    setSending(true); setErr(""); setResult(null);
    try {
      const r = await api.post("/training/nudge-non-starters", { module_code: "cpo-prep", message, include_email: !!includeEmail });
      setResult(r || {});
      showToast(`Nudged ${r?.count_nudged ?? notStarted} tech${(r?.count_nudged ?? notStarted) === 1 ? "" : "s"}.`, "success");
    } catch (e: any) {
      setNudgedIds(prev); // rollback
      setErr(e?.message || "Nudge failed");
      showToast(e?.message || "Could not send nudge.", "error");
    } finally {
      setSending(false);
    }
  };

  return (
    <View style={s.card} testID="cpo-readiness-widget">
      <Pressable onPress={() => setExpand((v) => !v)} style={s.head} testID="cpo-readiness-toggle">
        <Ionicons name="school-outline" size={18} color={colors.brand} />
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Team CPO Readiness</Text>
          {state.loading ? <Text style={s.sub}>Loading…</Text>
            : state.error ? <Text style={[s.sub, { color: colors.error }]} testID="cpo-readiness-error">{state.error}</Text>
            : <Text style={s.sub} testID="cpo-readiness-summary">{certified} of {total} pool techs certified · {inProg} in progress · {notStarted} not started</Text>}
        </View>
        <Ionicons name={expand ? "chevron-down" : "chevron-forward"} size={16} color={colors.muted} />
      </Pressable>

      {!state.loading && !state.error && notStarted > 0 ? (
        <Pressable onPress={openNudge} disabled={sending || allNudged} style={[s.nudgeBtn, (sending || allNudged) && { opacity: 0.6 }]} testID="cpo-nudge-btn">
          {sending ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name={allNudged ? "checkmark" : "send"} size={12} color="#fff" />}
          <Text style={s.nudgeBtnText}>{allNudged ? `Nudged ${notStarted} non-starter${notStarted === 1 ? "" : "s"}` : `Nudge ${notStarted} non-starter${notStarted === 1 ? "" : "s"}`}</Text>
        </Pressable>
      ) : null}

      {expand && !state.loading && total > 0 ? (
        <View style={s.table} testID="cpo-readiness-table">
          {state.rows.map((r) => <CpoRow key={r.id} r={r} nudged={nudgedIds.has(r.id)} />)}
          <Pressable onPress={() => router.push("/(app)/tests" as any)} style={s.footer} testID="cpo-readiness-manage-link">
            <Text style={s.footerText}>In-progress counter accurate as of last widget load. </Text>
            <Text style={s.link}>Manage training →</Text>
          </Pressable>
        </View>
      ) : null}

      <Sheet visible={sheet} onClose={() => setSheet(false)} title="Nudge non-starters" testID="cpo-nudge-modal">
        <Text style={s.sub}>{notStarted} tech{notStarted === 1 ? "" : "s"} · CPO Prep module</Text>
        <View style={s.listBox}>{nonStarters.map((r) => <Text key={r.id} style={s.listItem}>{r.name}</Text>)}</View>
        <Text style={s.label}>Message</Text>
        <AppTextInput value={message} onChangeText={setMessage} multiline style={s.input} testID="cpo-nudge-message" />
        <View style={s.emailRow}>
          <Switch value={includeEmail} onValueChange={setIncludeEmail} testID="cpo-nudge-include-email" />
          <Text style={s.emailText}>Also draft email</Text>
        </View>
        {result ? (
          <View style={[s.banner, s.ok]} testID="cpo-nudge-result">
            <Text style={s.okText}>Nudged {result.count_nudged ?? 0} tech{result.count_nudged === 1 ? "" : "s"}. Skipped {result.count_skipped_idempotent ?? 0} already-nudged this week.{result.email_ids?.length ? ` Emails queued: ${result.email_ids.length}.` : ""}</Text>
          </View>
        ) : null}
        {err ? <View style={[s.banner, s.bad]} testID="cpo-nudge-error"><Text style={s.badText}>{err}</Text></View> : null}
        <View style={s.actions}>
          <Pressable onPress={() => setSheet(false)} style={s.cancel} testID="cpo-nudge-cancel"><Text style={s.cancelText}>{result ? "Done" : "Cancel"}</Text></Pressable>
          <Pressable onPress={sendNudge} disabled={sending || !!result} style={[s.send, (sending || !!result) && { opacity: 0.6 }]} testID="cpo-nudge-send">
            {sending ? <ActivityIndicator size="small" color="#fff" testID="cpo-nudge-sending" /> : <Ionicons name="send" size={13} color="#fff" />}
            <Text style={s.sendText}>Send Nudge</Text>
          </Pressable>
        </View>
      </Sheet>
    </View>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginTop: spacing.lg },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44 },
  title: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: 12, color: colors.muted, marginTop: 2 },
  nudgeBtn: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", minHeight: 36, paddingHorizontal: spacing.md, borderRadius: radius.md, backgroundColor: colors.brand, marginTop: spacing.sm },
  nudgeBtnText: { fontFamily: font.semibold, fontSize: 12, color: "#fff" },
  table: { marginTop: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, overflow: "hidden" },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border },
  rowName: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  rowStatus: { fontFamily: font.medium, fontSize: 11, marginTop: 1 },
  rowRight: { alignItems: "flex-end" },
  rowMeta: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  nudgedChip: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: colors.brandTertiary },
  nudgedText: { fontFamily: font.bold, fontSize: 10, color: colors.brand },
  footer: { flexDirection: "row", flexWrap: "wrap", padding: spacing.md, backgroundColor: colors.surfaceSecondary },
  footerText: { fontFamily: font.regular, fontStyle: "italic", fontSize: 10, color: colors.muted },
  link: { fontFamily: font.semibold, fontSize: 10, color: colors.brand, textDecorationLine: "underline" },
  listBox: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.sm, marginTop: spacing.sm },
  listItem: { fontFamily: font.regular, fontSize: 12, color: colors.onSurface, paddingVertical: 1 },
  label: { fontFamily: font.bold, fontSize: 11, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.6, marginTop: spacing.md },
  input: { minHeight: 110, textAlignVertical: "top", borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, marginTop: 4, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  emailRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.md },
  emailText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  banner: { borderRadius: radius.md, padding: spacing.sm, marginTop: spacing.md },
  ok: { backgroundColor: "#DCFCE7" }, okText: { fontFamily: font.regular, fontSize: 12, color: "#166534" },
  bad: { backgroundColor: "#FEE2E2" }, badText: { fontFamily: font.regular, fontSize: 12, color: "#991B1B" },
  actions: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.lg },
  cancel: { minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  cancelText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  send: { minHeight: 44, flexDirection: "row", gap: 6, paddingHorizontal: spacing.lg, borderRadius: radius.md, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  sendText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
});
