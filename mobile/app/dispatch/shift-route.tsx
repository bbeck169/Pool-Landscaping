// Phase 38 · Feb-2026 — Mobile ShiftRoute (P1.4).
//
// Web parity: `frontend/src/pages/dispatch/ShiftRouteDialog.jsx`.
// Backend: POST /api/dispatch/reassign.
// Screen params: source tech + optional day + optional preselected
// customer_ids. Simplifed mobile version — supports the two most
// common flows (whole route temp/permanent + partial with pre-selected).
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, Pressable,
} from "react-native";
import { router, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, Loading, PrimaryButton, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";
import { showConfirm } from "@/src/components/ConfirmModal";

type Scope = "whole_route" | "partial";
type Duration = "temporary" | "permanent";

export default function ShiftRoutePage() {
  const params = useLocalSearchParams<{
    source: string; day?: string; sourceName?: string;
    customerIds?: string; scope?: Scope;
  }>();
  const [techs, setTechs] = useState<any[]>([]);
  const [target, setTarget] = useState<string>("");
  const [scope, setScope] = useState<Scope>((params.scope as Scope) || "whole_route");
  const [duration, setDuration] = useState<Duration>("temporary");
  const [notes, setNotes] = useState("");
  const [ack, setAck] = useState(false);  // permanent-ack
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const preselected = params.customerIds
    ? String(params.customerIds).split(",").filter(Boolean) : [];

  useEffect(() => {
    (async () => {
      try {
        const r: any = await api.get("/dispatch/technician-skills");
        const rows = Array.isArray(r) ? r : r?.items || [];
        setTechs(rows.filter((t: any) => (t.user_id || t.id) !== params.source));
      } catch { setTechs([]); }
    })();
  }, [params.source]);

  const submit = useCallback((force = false) => {
    if (!target) { setErr("Pick a target tech"); return; }
    if (duration === "permanent" && !ack) { setErr("Acknowledge the permanent flag"); return; }
    setErr("");
    const doIt = async () => {
      setBusy(true);
      try {
        const body: any = {
          source_tech_user_id: params.source,
          target_tech_user_id: target,
          scope,
          duration,
          day: params.day || null,
          notes: notes || undefined,
          force,
        };
        if (scope === "partial") body.customer_ids = preselected;
        const r: any = await api.post("/dispatch/reassign", body);
        if (r?.warning === "existing_override_conflict" && !force) {
          showConfirm({
            title: "Existing override conflict",
            description:
              `${(r.conflicts || []).length} customer(s) already have an active override. Proceed anyway?`,
            confirmLabel: "Override",
            destructive: true,
            testID: "shift-route-conflict-confirm",
            onConfirm: () => submit(true),
          });
          return;
        }
        router.back();
      } catch (e: any) {
        setErr(e?.body?.detail || e?.message || "Failed");
      } finally {
        setBusy(false);
      }
    };
    if (duration === "permanent") {
      showConfirm({
        title: "Apply PERMANENT reassignment?",
        description:
          "Permanent shifts rewrite the customer's master tech list. This can't be undone from mobile.",
        confirmLabel: "Apply permanent",
        destructive: true,
        testID: "shift-route-permanent-confirm",
        onConfirm: doIt,
      });
    } else {
      doIt();
    }
  }, [target, duration, scope, notes, ack, preselected, params.source, params.day]);

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="dispatch-shift-route-page">
        <Header title="Shift Route" />
        <ScrollView contentContainerStyle={styles.body}>
          <Card style={styles.summary}>
            <Text style={styles.head}>Source</Text>
            <Text style={styles.tech}>{params.sourceName || params.source}</Text>
            {params.day ? <Text style={styles.day}>Day · {params.day}</Text> : null}
            {preselected.length > 0 && (
              <Text style={styles.pre}>
                {preselected.length} pre-selected customer(s)
              </Text>
            )}
          </Card>

          <Text style={styles.section}>Target tech</Text>
          <View style={styles.pills} testID="shift-route-targets">
            {techs.length === 0 ? (
              <Text style={styles.emptyText}>Loading techs…</Text>
            ) : techs.map((t) => {
              const id = t.user_id || t.id;
              return (
                <Pressable
                  key={id}
                  onPress={() => setTarget(id)}
                  style={[styles.pill, target === id && styles.pillOn]}
                  testID={`shift-route-target-${id}`}
                >
                  <Text style={[styles.pillText, target === id && styles.pillTextOn]}>{t.name || id}</Text>
                </Pressable>
              );
            })}
          </View>

          <Text style={styles.section}>Scope</Text>
          <View style={styles.pills}>
            {(["whole_route", "partial"] as Scope[]).map((s) => (
              <Pressable
                key={s}
                onPress={() => setScope(s)}
                style={[styles.pill, scope === s && styles.pillOn]}
                disabled={s === "partial" && preselected.length === 0}
                testID={`shift-route-scope-${s}`}
              >
                <Text style={[styles.pillText, scope === s && styles.pillTextOn]}>
                  {s === "whole_route" ? "Whole route" : `Partial (${preselected.length})`}
                </Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.section}>Duration</Text>
          <View style={styles.pills}>
            {(["temporary", "permanent"] as Duration[]).map((d) => (
              <Pressable
                key={d}
                onPress={() => setDuration(d)}
                style={[styles.pill, duration === d && styles.pillOn]}
                testID={`shift-route-duration-${d}`}
              >
                <Text style={[styles.pillText, duration === d && styles.pillTextOn]}>
                  {d === "temporary" ? "Temporary" : "Permanent"}
                </Text>
              </Pressable>
            ))}
          </View>

          {duration === "permanent" && (
            <Pressable
              onPress={() => setAck((a) => !a)}
              style={styles.ack}
              testID="shift-route-ack"
            >
              <Text style={[styles.ackBox, ack && styles.ackBoxOn]}>{ack ? "✓" : ""}</Text>
              <Text style={styles.ackText}>
                I understand this rewrites the master tech list.
              </Text>
            </Pressable>
          )}

          <TextInput
            value={notes}
            onChangeText={setNotes}
            placeholder="Notes (optional)"
            multiline
            style={styles.input}
            testID="shift-route-notes"
          />

          {err ? <Text style={styles.err}>{err}</Text> : null}

          <PrimaryButton
            label={busy ? "Applying…" : "Apply reassignment"}
            onPress={() => submit(false)}
            disabled={busy || !target || (duration === "permanent" && !ack)}
            testID="shift-route-apply"
          />
        </ScrollView>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.sm, paddingBottom: spacing["3xl"] },
  summary: { gap: 4 },
  head: { fontFamily: font.medium, fontSize: 10, textTransform: "uppercase", color: colors.muted, letterSpacing: 0.5 },
  tech: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface },
  day: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  pre: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.brand },
  section: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, textTransform: "uppercase", letterSpacing: 0.5, marginTop: spacing.sm },
  pills: { flexDirection: "row", gap: spacing.xs, flexWrap: "wrap" },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  pillOn: { backgroundColor: colors.brandTertiary, borderColor: colors.brand },
  pillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  pillTextOn: { color: colors.brand },
  ack: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.sm, borderRadius: radius.sm, backgroundColor: colors.surfaceSecondary },
  ackBox: { width: 22, height: 22, borderRadius: 4, borderWidth: 1, borderColor: colors.border, textAlign: "center", lineHeight: 20, fontFamily: font.bold, color: colors.brand },
  ackBoxOn: { backgroundColor: colors.brandTertiary, borderColor: colors.brand },
  ackText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface, flex: 1 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, padding: spacing.sm, fontFamily: font.regular, fontSize: fontSize.md, backgroundColor: colors.surface, minHeight: 60 },
  err: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, fontStyle: "italic" },
});
