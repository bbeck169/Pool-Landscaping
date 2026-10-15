/**
 * Form submission detail (read-only): every answer (labelled from the
 * form schema when available), metadata (time, IP, UA, page), and
 * destination (lead / customer). Fields flagged `pii_tag` (or
 * `is_customer_facing === false`) are masked until tapped.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";

import { Header } from "@/src/components/widgets";
import CommsAdminGate from "@/src/components/comms/CommsAdminGate";
import { getForm, listFormSubmissions, type FormSubmission } from "@/src/api/marketingForms";
import { answersOf, formatAnswer, isSensitive } from "@/src/utils/formSubmissions";
import { colors, font, fontSize, spacing } from "@/src/theme";

export default function FormSubmissionDetailScreen() {
  return (
    <CommsAdminGate title="Submission">
      <DetailBody />
    </CommsAdminGate>
  );
}

function Row({ k, v, sensitive, testID }: { k: string; v: string; sensitive?: boolean; testID: string }) {
  const [shown, setShown] = useState(!sensitive);
  return (
    <View style={s.row} testID={testID}>
      <Text style={s.k}>{k}</Text>
      {shown ? (
        <Text style={s.v} selectable>{v}</Text>
      ) : (
        <Pressable onPress={() => setShown(true)} hitSlop={8} testID={`${testID}-reveal`}><Text style={s.masked}>••••• Tap to reveal</Text></Pressable>
      )}
    </View>
  );
}

function DetailBody() {
  const { sid, fid } = useLocalSearchParams<{ sid: string; fid: string }>();
  const router = useRouter();
  const [sub, setSub] = useState<FormSubmission | null>(null);
  const [fields, setFields] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listFormSubmissions(String(fid), 500), getForm(String(fid)).catch(() => null)])
      .then(([rows, form]) => {
        const hit = rows.find((r) => r.id === sid) || null;
        if (!hit) setErr("Submission not found.");
        setSub(hit);
        setFields(form?.fields || []);
      })
      .catch((e) => setErr(e?.message || "Couldn't load submission."));
  }, [sid, fid]);

  const byName = Object.fromEntries(fields.map((f) => [f.name || f.id, f]));
  const answers = sub ? answersOf(sub) : {};
  return (
    <View style={s.root} testID="form-submission-detail">
      <Header title={sub?.form_name || "Submission"} subtitle={sub?.created_at ? new Date(sub.created_at).toLocaleString() : undefined} back />
      <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
        {err ? <Text style={s.err} testID="form-submission-error">{err}</Text> : !sub ? (
          <ActivityIndicator color={colors.brand} testID="form-submission-loader" />
        ) : (
          <>
            <Text style={s.section}>Answers</Text>
            {Object.keys(answers).map((k) => (
              <Row key={k} k={byName[k]?.label || k} v={formatAnswer(answers[k])} sensitive={isSensitive(byName[k])} testID={`form-submission-answer-${k}`} />
            ))}
            {(sub.file_uploads || []).length ? (
              <Row k="Files" v={(sub.file_uploads || []).map((f: any) => f?.filename || f?.name || "file").join(", ")} testID="form-submission-files" />
            ) : null}
            <Text style={s.section}>Destination</Text>
            {sub.customer_id ? (
              <Pressable onPress={() => router.push(`/customer/${sub.customer_id}` as any)} testID="form-submission-customer-link">
                <Row k="Customer" v={`${sub.customer_id} ›`} testID="form-submission-customer" />
              </Pressable>
            ) : null}
            {sub.lead_id ? <Row k="Lead" v={sub.lead_id} testID="form-submission-lead" /> : null}
            {!sub.customer_id && !sub.lead_id ? <Row k="Routed to" v="Not linked to a lead or customer" testID="form-submission-unrouted" /> : null}
            <Text style={s.section}>Metadata</Text>
            <Row k="Submitted" v={sub.created_at ? new Date(sub.created_at).toLocaleString() : "—"} testID="form-submission-meta-at" />
            <Row k="IP" v={sub.ip || "—"} testID="form-submission-meta-ip" />
            <Row k="User agent" v={sub.user_agent || "—"} testID="form-submission-meta-ua" />
            <Row k="Page" v={sub.page_url || "—"} testID="form-submission-meta-page" />
            {sub.submission_kind ? <Row k="Kind" v={sub.submission_kind} testID="form-submission-meta-kind" /> : null}
          </>
        )}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  section: { fontFamily: font.bold, fontSize: 11, color: colors.muted, letterSpacing: 0.5, textTransform: "uppercase", marginTop: spacing.lg, marginBottom: 4 },
  row: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border, gap: 2 },
  k: { fontFamily: font.medium, fontSize: 12, color: colors.muted },
  v: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  masked: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  err: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error },
});
