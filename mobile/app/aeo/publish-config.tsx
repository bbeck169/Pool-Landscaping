// Phase 16 · Feb-2026 — LLMs.txt Auto-Publish config (Manager+).
//
// Three provider cards (Netlify / Vercel / Cloudflare Pages). Each
// expands to a form. Tokens are masked once saved. Test + Publish now
// buttons use the Phase 9 provider endpoints.
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, Pressable, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { Card, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

type Provider = "netlify" | "vercel" | "cloudflare_pages";

const PROVIDER_META: Record<Provider, {
  title: string;
  icon: any;
  color: string;
  fields: { key: string; label: string; secure?: boolean; placeholder?: string }[];
}> = {
  netlify: {
    title: "Netlify",
    icon: "cloud-outline",
    color: "#3A9C8B",
    fields: [
      { key: "token", label: "Personal access token", secure: true, placeholder: "netlify_pat_…" },
      { key: "site_id", label: "Site ID" },
    ],
  },
  vercel: {
    title: "Vercel",
    icon: "triangle-outline",
    color: "#000000",
    fields: [
      { key: "token", label: "Access token", secure: true },
      { key: "project_id", label: "Project ID" },
      { key: "team_id", label: "Team ID (optional)" },
    ],
  },
  cloudflare_pages: {
    title: "Cloudflare Pages",
    icon: "flash-outline",
    color: "#F38020",
    fields: [
      { key: "api_token", label: "API token", secure: true },
      { key: "account_id", label: "Account ID" },
      { key: "project_name", label: "Project name" },
    ],
  },
};

type ProviderState = {
  configured?: boolean;
  masked_token?: string;
  last_publish_status?: string;
  last_publish_at?: string;
  fields?: Record<string, any>;
};

export default function PublishConfig() {
  const { showToast } = useToast();
  const [statuses, setStatuses] = useState<Record<Provider, ProviderState>>({
    netlify: {}, vercel: {}, cloudflare_pages: {},
  });
  const [expanded, setExpanded] = useState<Provider | null>(null);
  const [drafts, setDrafts] = useState<Record<Provider, Record<string, string>>>({
    netlify: {}, vercel: {}, cloudflare_pages: {},
  });
  const [saving, setSaving] = useState<Provider | null>(null);
  const [testing, setTesting] = useState<Provider | null>(null);
  const [publishing, setPublishing] = useState<Provider | null>(null);

  const load = useCallback(async () => {
    try {
      const j: any = await api.get("/aeo/llms-txt/publish/providers");
      const rows: any[] = j?.providers || j?.items || [];
      const next = { ...statuses };
      for (const r of rows) {
        const key = (r.provider || r.name) as Provider;
        if (next[key] !== undefined) {
          next[key] = {
            configured: !!r.configured,
            masked_token: r.masked_token,
            last_publish_status: r.last_publish_status || r.status,
            last_publish_at: r.last_publish_at,
            fields: r.fields || {},
          };
        }
      }
      setStatuses(next);
    } catch {
      // silent
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const setDraft = (p: Provider, k: string, v: string) =>
    setDrafts((d) => ({ ...d, [p]: { ...d[p], [k]: v } }));

  const save = async (p: Provider) => {
    setSaving(p);
    try {
      await api.post("/aeo/llms-txt/publish/config", { provider: p, ...drafts[p] });
      showToast(`${PROVIDER_META[p].title} config saved.`);
      await load();
    } catch (err: any) {
      showToast(String(err?.message || err), "error");
    } finally {
      setSaving(null);
    }
  };

  const test = async (p: Provider) => {
    setTesting(p);
    try {
      const j: any = await api.post(`/aeo/llms-txt/publish/test/${p}`, {});
      showToast(
        j?.ok ? "Connection successful." : (j?.error || "Test failed."),
        j?.ok ? "success" : "error",
      );
    } catch (err: any) {
      showToast(String(err?.message || err), "error");
    } finally {
      setTesting(null);
    }
  };

  const publish = async (p: Provider) => {
    setPublishing(p);
    try {
      const j: any = await api.post(`/aeo/llms-txt/publish/${p}`, {});
      showToast(
        j?.ok ? "llms.txt published successfully." : (j?.error || "Publish failed."),
        j?.ok ? "success" : "error",
      );
      await load();
    } catch (err: any) {
      showToast(String(err?.message || err), "error");
    } finally {
      setPublishing(null);
    }
  };

  return (
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="LLMs.txt Publish" />
        <ScrollView contentContainerStyle={styles.body}>
          {(Object.keys(PROVIDER_META) as Provider[]).map((p) => {
            const meta = PROVIDER_META[p];
            const state = statuses[p];
            const isOpen = expanded === p;
            return (
              <Card key={p}>
                <Pressable
                  testID={`publish-provider-${p}`}
                  onPress={() => setExpanded(isOpen ? null : p)}
                  style={styles.provRow}
                >
                  <View style={[styles.provIcon, { backgroundColor: `${meta.color}20` }]}>
                    <Ionicons name={meta.icon} size={20} color={meta.color} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.provTitle}>{meta.title}</Text>
                    <Text style={styles.provSub}>
                      {state.configured ? (state.masked_token || "Configured") : "Not configured"}
                      {state.last_publish_status ? ` · ${state.last_publish_status}` : ""}
                    </Text>
                  </View>
                  <Ionicons name={isOpen ? "chevron-up" : "chevron-down"} size={20} color={colors.muted} />
                </Pressable>

                {isOpen ? (
                  <View style={styles.form}>
                    {meta.fields.map((f) => (
                      <View key={f.key} style={styles.field}>
                        <Text style={styles.label}>{f.label}</Text>
                        <TextInput
                          testID={`publish-${p}-${f.key}`}
                          value={drafts[p][f.key] ?? ""}
                          onChangeText={(v) => setDraft(p, f.key, v)}
                          placeholder={f.placeholder || (f.secure ? "•••••••" : "")}
                          placeholderTextColor={colors.muted}
                          secureTextEntry={f.secure}
                          autoCapitalize="none"
                          style={styles.input}
                        />
                      </View>
                    ))}
                    <View style={{ height: spacing.sm }} />
                    <PrimaryButton
                      title={saving === p ? "Saving…" : "Save config"}
                      icon="save-outline"
                      onPress={() => save(p)}
                      loading={saving === p}
                      testID={`publish-${p}-save`}
                    />
                    <View style={{ height: spacing.xs }} />
                    <View style={styles.actionRow}>
                      <Pressable
                        testID={`publish-${p}-test`}
                        onPress={() => test(p)}
                        style={[styles.smBtn, { backgroundColor: colors.surfaceSecondary }]}
                        disabled={testing === p}
                      >
                        <Ionicons name="pulse-outline" size={16} color={colors.onSurfaceSecondary} />
                        <Text style={styles.smBtnText}>{testing === p ? "Testing…" : "Test"}</Text>
                      </Pressable>
                      <Pressable
                        testID={`publish-${p}-publish`}
                        onPress={() => publish(p)}
                        style={[styles.smBtn, { backgroundColor: "#DCFCE7" }]}
                        disabled={publishing === p}
                      >
                        <Ionicons name="cloud-upload-outline" size={16} color={colors.success} />
                        <Text style={[styles.smBtnText, { color: colors.success }]}>
                          {publishing === p ? "Publishing…" : "Publish now"}
                        </Text>
                      </Pressable>
                    </View>
                  </View>
                ) : null}
              </Card>
            );
          })}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  provRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  provIcon: { width: 40, height: 40, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  provTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  provSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  form: { marginTop: spacing.md, gap: spacing.sm },
  field: { gap: 4 },
  label: { fontFamily: font.medium, fontSize: 11, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface,
  },
  actionRow: { flexDirection: "row", gap: 6 },
  smBtn: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md, gap: 6 },
  smBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
});
