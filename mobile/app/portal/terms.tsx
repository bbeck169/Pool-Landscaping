import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
} from "react-native";
import Markdown from "react-native-markdown-display";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Header } from "@/src/components/widgets";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/**
 * Phase 39 · Feb-2026 — mobile customer Terms of Service.
 *
 * Mirrors the web `/portal/terms` (`PortalTerms.jsx`) surface — same
 * public endpoint (``GET /api/legal/{slug}``), same slug
 * (``terms-of-service-pool-maintenance``), same acknowledge / status
 * flow when the customer is signed in.
 *
 * Reachable from two entry points on mobile:
 *   1. Signed-in customer portal → drawer / profile → "Terms of Service".
 *   2. Login screen → "Terms of Service" link at the bottom of the
 *      sign-in form (pre-auth). The document endpoint is public so
 *      hydration works without a token; the acknowledge widget is
 *      simply hidden when ``user`` is null.
 */
const SLUG = "terms-of-service-pool-maintenance";

type LegalDoc = {
  slug: string;
  title: string;
  body_markdown: string;
  version: number | string;
  effective_date?: string;
  updated_at?: string;
};

type AckState = {
  acknowledged: boolean;
  current_version: number | string | null;
  acked_at?: string | null;
};

export default function PortalTerms() {
  const { user } = useAuth();
  const router = useRouter();
  const [doc, setDoc] = useState<LegalDoc | null>(null);
  const [ack, setAck] = useState<AckState>({
    acknowledged: false,
    current_version: null,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const d = await api.get(`/legal/${SLUG}`);
        if (alive) setDoc(d);
      } catch {
        if (alive) setDoc(null);
      }
      // Ack status is only meaningful when the user is signed in —
      // the endpoint requires auth and would 401 otherwise.
      if (user) {
        try {
          const s = await api.get(`/portal/terms/status?slug=${SLUG}`);
          if (alive) setAck(s);
        } catch {
          // No-op — the "I have read and agree" widget just stays visible.
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [user]);

  const agree = useCallback(async () => {
    if (!doc) return;
    setSaving(true);
    setError("");
    try {
      await api.post("/portal/terms/acknowledge", {
        slug: SLUG,
        version: doc.version,
      });
      const s = await api.get(`/portal/terms/status?slug=${SLUG}`);
      setAck(s);
    } catch (e: any) {
      setError(
        e?.message ||
          "Could not record your acknowledgement. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  }, [doc]);

  return (
    <View style={s.root} testID="portal-terms-page">
      <Header title="Terms of Service" back />
      {!doc ? (
        <View style={s.loadingBox} testID="portal-terms-loading">
          <ActivityIndicator size="large" color={colors.brand} />
        </View>
      ) : (
        <ScrollView
          testID="portal-terms-content"
          contentContainerStyle={s.scrollContent}
        >
          <View style={s.card}>
            <View style={s.metaRow}>
              <Ionicons
                name="document-text-outline"
                size={20}
                color={colors.brand}
              />
              <View style={{ flex: 1 }}>
                <Text style={s.eyebrow}>LEGAL</Text>
                <Text style={s.title}>{doc.title}</Text>
              </View>
              <View style={s.versionPill}>
                <Text style={s.versionPillText}>v{doc.version}</Text>
              </View>
            </View>

            <View style={s.datesRow}>
              {doc.effective_date ? (
                <Text style={s.dateLabel}>
                  Effective:{" "}
                  <Text style={s.dateValue}>{doc.effective_date}</Text>
                </Text>
              ) : null}
              {doc.updated_at ? (
                <Text style={s.dateLabel}>
                  Updated:{" "}
                  <Text style={s.dateValue}>
                    {(doc.updated_at || "").slice(0, 10)}
                  </Text>
                </Text>
              ) : null}
            </View>

            <View testID="portal-terms-markdown">
              <Markdown style={markdownStyles}>
                {doc.body_markdown || ""}
              </Markdown>
            </View>
          </View>

          {/* Acknowledge widget · signed-in customers only. Hidden
              pre-auth (login-link entry point) — the ToS text
              itself is still fully readable. */}
          {user ? (
            <View style={s.ackCard}>
              {ack.acknowledged ? (
                <View style={s.ackedRow} testID="portal-terms-acknowledged">
                  <View style={s.ackedIcon}>
                    <Ionicons name="checkmark" size={18} color="#16A34A" />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.ackedTitle}>
                      You have acknowledged this version.
                    </Text>
                    <Text style={s.ackedSub}>
                      Acked {(ack.acked_at || "").slice(0, 10)} · v
                      {ack.current_version}
                    </Text>
                  </View>
                </View>
              ) : (
                <>
                  <Text style={s.ackBody}>
                    By tapping the button you acknowledge you have read and
                    agree to the terms above.
                  </Text>
                  <Pressable
                    testID="portal-terms-agree-btn"
                    onPress={agree}
                    disabled={saving}
                    style={({ pressed }) => [
                      s.agreeBtn,
                      pressed && { opacity: 0.8 },
                      saving && { opacity: 0.6 },
                    ]}
                    accessibilityRole="button"
                    accessibilityLabel="I have read and agree"
                  >
                    <Text style={s.agreeBtnText}>
                      {saving ? "Recording…" : "I have read and agree"}
                    </Text>
                  </Pressable>
                  {error ? (
                    <View style={s.errorBox} testID="portal-terms-agree-error">
                      <Text style={s.errorText}>{error}</Text>
                    </View>
                  ) : null}
                </>
              )}
            </View>
          ) : (
            // Not signed in — offer a shortcut back to login.
            <Pressable
              testID="portal-terms-back-to-login"
              onPress={() => router.replace("/login")}
              style={({ pressed }) => [
                s.backToLoginBtn,
                pressed && { opacity: 0.8 },
              ]}
            >
              <Ionicons name="arrow-back" size={16} color={colors.brand} />
              <Text style={s.backToLoginText}>Back to sign in</Text>
            </Pressable>
          )}
        </ScrollView>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  loadingBox: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing["3xl"],
  },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: spacing["3xl"],
    gap: spacing.md,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.md,
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  eyebrow: {
    fontFamily: font.semibold,
    fontSize: 10,
    letterSpacing: 1.4,
    color: colors.muted,
    marginBottom: 2,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize["xl"],
    color: colors.onSurface,
  },
  versionPill: {
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
  },
  versionPillText: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.onBrandTertiary,
  },
  datesRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.md,
  },
  dateLabel: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.muted,
  },
  dateValue: {
    fontFamily: font.semibold,
    color: colors.onSurface,
  },
  ackCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.md,
  },
  ackBody: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    lineHeight: 21,
  },
  agreeBtn: {
    backgroundColor: colors.brand,
    paddingVertical: 14,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.md,
    alignItems: "center",
  },
  agreeBtnText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
  ackedRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  ackedIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: "#DCFCE7",
    alignItems: "center",
    justifyContent: "center",
  },
  ackedTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  ackedSub: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.muted,
    marginTop: 2,
  },
  errorBox: {
    marginTop: spacing.sm,
    padding: spacing.sm,
    backgroundColor: "#FEF3C7",
    borderColor: "#FDE68A",
    borderWidth: 1,
    borderRadius: radius.md,
  },
  errorText: {
    fontFamily: font.regular,
    fontSize: 13,
    color: "#92400E",
  },
  backToLoginBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: spacing.md,
  },
  backToLoginText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.brand,
  },
});

// Markdown styling — mirrors the web MarkdownBody component's
// element treatment (h2/h3 hierarchy, bullet indent, code chip)
// so the same source document reads the same on both surfaces.
const markdownStyles = StyleSheet.create({
  body: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    lineHeight: 22,
  },
  heading1: {
    fontFamily: font.bold,
    fontSize: fontSize["2xl"],
    color: colors.onSurface,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  heading2: {
    fontFamily: font.bold,
    fontSize: fontSize["xl"],
    color: colors.onSurface,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  heading3: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
  paragraph: { marginBottom: spacing.sm },
  strong: { fontFamily: font.bold, color: colors.onSurface },
  em: { fontStyle: "italic" },
  bullet_list: { marginBottom: spacing.sm },
  ordered_list: { marginBottom: spacing.sm },
  list_item: { marginBottom: 4 },
  hr: {
    backgroundColor: colors.border,
    height: 1,
    marginVertical: spacing.md,
  },
  code_inline: {
    fontFamily: font.regular,
    backgroundColor: colors.surfaceTertiary,
    color: colors.brand,
    paddingHorizontal: 4,
    borderRadius: 4,
  },
});
