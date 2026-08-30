/**
 * Phase S2 · Brand Brain tab — read-only brand memory + re-ingest modal.
 * Mirrors frontend/src/pages/soshie/BrandBrainTab.jsx
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, TextInput, Alert,
  Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { Card, PrimaryButton, Sheet, EmptyState } from "@/src/components/ui";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/* ── Skeleton ─────────────────────────────────────────────────── */
function Skeleton({ height = 80 }: { height?: number }) {
  return (
    <View
      style={[s.skeleton, { height }]}
      testID="brand-brain-skeleton"
    />
  );
}

/* ── Section card ─────────────────────────────────────────────── */
function Section({
  title, icon, children, testID,
}: {
  title: string; icon?: string; children: React.ReactNode; testID?: string;
}) {
  return (
    <Card style={s.sectionCard}>
      <View style={s.sectionHeader} testID={testID}>
        {icon ? (
          <Ionicons name={icon as any} size={15} color={colors.muted} />
        ) : null}
        <Text style={s.sectionTitle}>{title}</Text>
      </View>
      {children}
    </Card>
  );
}

/* ── Ingest modal ─────────────────────────────────────────────── */
function IngestModal({
  visible, onClose, onDone,
}: {
  visible: boolean; onClose: () => void; onDone: () => void;
}) {
  const [url, setUrl] = useState("");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!url.trim()) {
      Alert.alert("Missing URL", "Enter a website URL first.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/soshie/ingest-website", {
        website_url: url.trim(),
      });
      Alert.alert("Done", "Website ingested — brand memory refreshed.");
      onDone();
      onClose();
    } catch (e: any) {
      Alert.alert("Ingest failed", e?.message || "Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      visible={visible}
      onClose={onClose}
      title="Re-ingest brand memory"
      testID="brand-brain-ingest-modal"
    >
      <View style={s.modalBody}>
        <Text style={s.label}>Website URL</Text>
        <TextInput
          style={s.input}
          placeholder="https://your-company.com"
          placeholderTextColor={colors.muted}
          value={url}
          onChangeText={setUrl}
          autoCapitalize="none"
          keyboardType="url"
          testID="ingest-url-input"
          accessibilityLabel="Website URL"
        />

        <Text style={[s.label, { marginTop: spacing.md }]}>
          Optional additional paths (one per line)
        </Text>
        <TextInput
          style={[s.input, { minHeight: 80, textAlignVertical: "top" }]}
          multiline
          placeholder={"/services\n/about"}
          placeholderTextColor={colors.muted}
          value={extra}
          onChangeText={setExtra}
          testID="ingest-extra-input"
          accessibilityLabel="Additional paths"
        />
        <Text style={s.hint}>
          Home page ingest is enough for most brands. Extra paths will be
          crawled if provided.
        </Text>

        <View style={s.modalActions}>
          <Pressable
            style={s.cancelBtn}
            onPress={onClose}
            disabled={busy}
            testID="ingest-cancel"
            accessibilityRole="button"
            accessibilityLabel="Cancel"
          >
            <Text style={s.cancelText}>Cancel</Text>
          </Pressable>
          <PrimaryButton
            title={busy ? "Ingesting…" : "Ingest website"}
            onPress={submit}
            loading={busy}
            disabled={busy}
            testID="ingest-submit"
          />
        </View>
      </View>
    </Sheet>
  );
}

/* ── Main tab ─────────────────────────────────────────────────── */
export default function BrandBrainTab({ disabled }: { disabled?: boolean }) {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [data, setData] = useState<any>({ brand_brain: null, latest_ingest: null });
  const [ingestOpen, setIngestOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/soshie/brand-brain");
      setData(r || {});
      setErr("");
    } catch (e: any) {
      setErr(e?.message || "Couldn't load brand memory");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!disabled) load();
  }, [load, disabled]);

  if (loading) {
    return (
      <View style={s.skeletonWrap} testID="brand-brain-loading">
        <Skeleton height={80} />
        <Skeleton height={120} />
        <Skeleton height={80} />
      </View>
    );
  }

  if (err) {
    return (
      <Card style={s.sectionCard}>
        <Text style={s.errorText} testID="brand-brain-error">{err}</Text>
      </Card>
    );
  }

  const bb = data.brand_brain || {};
  const ingest = data.latest_ingest;
  const isEmpty =
    !bb.tone && !bb.audience && !(bb.talking_points || []).length && !ingest;

  if (isEmpty) {
    return (
      <View testID="brand-brain-empty">
        <EmptyState
          icon="globe-outline"
          title="No brand memory yet"
          subtitle="Ingest your website to teach Soshie your voice, services, and region."
          testID="brand-brain-empty-state"
        />
        <View style={s.emptyCta}>
          <PrimaryButton
            title="Ingest your website"
            onPress={() => setIngestOpen(true)}
            testID="ingest-empty-cta"
            disabled={disabled}
          />
        </View>
        <IngestModal
          visible={ingestOpen}
          onClose={() => setIngestOpen(false)}
          onDone={load}
        />
      </View>
    );
  }

  return (
    <View testID="brand-brain-content">
      {/* Header card */}
      <Card style={s.sectionCard}>
        <View style={s.headerRow}>
          <View style={{ flex: 1 }}>
            <Text style={s.headerTitle}>Brand memory</Text>
            {ingest ? (
              <Text style={s.headerMeta} testID="brand-brain-last-ingest">
                Last ingested{" "}
                {ingest.ingested_at
                  ? new Date(ingest.ingested_at).toLocaleDateString()
                  : "recently"}
                {ingest.url ? ` · ${ingest.url}` : ""}
              </Text>
            ) : (
              <Text style={s.headerMeta} testID="brand-brain-manual">
                Brand memory is manually authored (no website ingest yet).
              </Text>
            )}
          </View>
          <Pressable
            style={s.reingestBtn}
            onPress={() => setIngestOpen(true)}
            disabled={disabled}
            testID="brand-brain-reingest-btn"
            accessibilityRole="button"
            accessibilityLabel="Re-ingest from website"
          >
            <Ionicons name="refresh" size={14} color={colors.brand} />
            <Text style={s.reingestText}>Re-ingest</Text>
          </Pressable>
        </View>
      </Card>

      {/* Tone */}
      {bb.tone ? (
        <Section title="Brand voice / tone" icon="chatbubble-outline" testID="section-tone">
          <Text style={s.bodyText} testID="brand-brain-tone">{bb.tone}</Text>
          {bb.brand_voice_snippet ? (
            <Text style={s.snippet} testID="brand-brain-voice-snippet">
              {`"${bb.brand_voice_snippet}"`}
            </Text>
          ) : null}
        </Section>
      ) : null}

      {/* Audience */}
      {bb.audience ? (
        <Section title="Target audience" testID="section-audience">
          <Text style={s.bodyText} testID="brand-brain-audience">
            {bb.audience}
          </Text>
        </Section>
      ) : null}

      {/* Talking points */}
      {(bb.talking_points || []).length ? (
        <Section title="Key talking points" testID="section-talking-points">
          {bb.talking_points.map((p: string, i: number) => (
            <View key={i} style={s.bulletRow}>
              <Text style={s.bullet}>•</Text>
              <Text style={s.bodyText}>{p}</Text>
            </View>
          ))}
        </Section>
      ) : null}

      {/* Guardrails */}
      {(bb.do_say || []).length || (bb.dont_say || []).length ? (
        <Section title="Voice guardrails" testID="section-guardrails">
          <View style={s.guardrailsRow}>
            <View style={s.guardrailCol}>
              <Text style={s.guardrailLabel}>DO SAY</Text>
              {(bb.do_say || []).map((p: string, i: number) => (
                <View key={i} style={s.bulletRow}>
                  <Text style={s.bullet}>•</Text>
                  <Text style={s.bodyText}>{p}</Text>
                </View>
              ))}
              {!(bb.do_say || []).length ? (
                <Text style={[s.bodyText, { color: colors.muted }]}>—</Text>
              ) : null}
            </View>
            <View style={s.guardrailCol}>
              <Text style={s.guardrailLabel}>{"DON'T SAY"}</Text>
              {(bb.dont_say || []).map((p: string, i: number) => (
                <View key={i} style={s.bulletRow}>
                  <Text style={s.bullet}>•</Text>
                  <Text style={s.bodyText}>{p}</Text>
                </View>
              ))}
              {!(bb.dont_say || []).length ? (
                <Text style={[s.bodyText, { color: colors.muted }]}>—</Text>
              ) : null}
            </View>
          </View>
        </Section>
      ) : null}

      {/* Ingest details */}
      {ingest && (ingest.service_summary || (ingest.headings || []).length) ? (
        <Section title="Ingested website details" icon="location-outline" testID="section-ingest">
          {ingest.service_summary ? (
            <Text style={[s.bodyText, { marginBottom: spacing.sm }]} testID="brand-brain-service-summary">
              {ingest.service_summary}
            </Text>
          ) : null}
          {(ingest.headings || []).length ? (
            <View>
              <Text style={s.guardrailLabel}>Headings pulled</Text>
              {ingest.headings.slice(0, 8).map((h: string, i: number) => (
                <View key={i} style={s.bulletRow}>
                  <Text style={s.bullet}>•</Text>
                  <Text style={s.bodyText}>{h}</Text>
                </View>
              ))}
            </View>
          ) : null}
        </Section>
      ) : null}

      <IngestModal
        visible={ingestOpen}
        onClose={() => setIngestOpen(false)}
        onDone={load}
      />
    </View>
  );
}

const s = StyleSheet.create({
  skeletonWrap: { gap: spacing.md },
  skeleton: {
    backgroundColor: colors.surfaceTertiary,
    borderRadius: radius.lg,
  },
  sectionCard: { marginBottom: spacing.md },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  sectionTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  headerTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  headerMeta: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 3,
  },
  reingestBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  reingestText: {
    fontFamily: font.semibold,
    fontSize: 12,
    color: colors.brand,
  },
  bodyText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    lineHeight: 20,
  },
  snippet: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.muted,
    fontStyle: "italic",
    marginTop: spacing.sm,
  },
  bulletRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: 4,
  },
  bullet: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  guardrailsRow: {
    flexDirection: "row",
    gap: spacing.md,
  },
  guardrailCol: { flex: 1 },
  guardrailLabel: {
    fontFamily: font.semibold,
    fontSize: 10,
    color: colors.muted,
    textTransform: "uppercase",
    marginBottom: 4,
    letterSpacing: 0.5,
  },
  emptyCta: {
    alignItems: "center",
    marginTop: spacing.lg,
  },
  errorText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.error,
  },
  modalBody: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
  },
  label: {
    fontFamily: font.semibold,
    fontSize: 12,
    color: colors.muted,
    marginBottom: 6,
  },
  hint: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 4,
  },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  modalActions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
    marginTop: spacing.xl,
  },
  cancelBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.sm,
  },
  cancelText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
});
