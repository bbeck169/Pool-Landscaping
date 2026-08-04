/**
 * Phase 34 · Review Gating — Customer-facing review submit.
 *
 * Route: /portal/review-submit?token=<review_request_token>
 *
 * Flow:
 * 1. GET /api/public/r/{token} → load request (expired? already_submitted?)
 * 2. User taps 1-5 stars
 * 3. POST /api/public/r/{token}/rating { star_rating, comment }
 *    → response.next_step = "choose_platform" (4-5 stars) | "private_feedback" (1-3)
 * 4a. choose_platform: Show Google CTA + other platform buttons
 * 4b. private_feedback: Show "Thank you" with private comment box already sent
 * 5. POST /api/public/r/{token}/google-clicked (analytics)
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, Linking, Platform,
  ScrollView, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type RequestData = {
  company_name?: string;
  tech_name?: string;
  expired?: boolean;
  already_submitted?: boolean;
  star_rating_submitted?: number;
};

type SubmitResult = {
  next_step: "choose_platform" | "private_feedback";
  choose_platform?: { platform: string; display_name: string; url: string }[];
  google_review_url?: string;
};

export default function ReviewSubmitScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const router = useRouter();
  const [reqData, setReqData] = useState<RequestData | null>(null);
  const [loading, setLoading] = useState(true);
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<SubmitResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        // Phase 34 · Feb 2026 — canonical path is `/reviews/public/r/*`.
        // The pre-Phase-34 alias `/public/r/*` still works (backend adds
        // a Deprecation: true header) but should not be used going forward.
        const data = await api.get(`/reviews/public/r/${token}`);
        setReqData(data);
      } catch (e: any) {
        setError(e?.message || "Invalid or expired review link.");
      } finally {
        setLoading(false);
      }
    })();
  }, [token]);

  const submit = useCallback(async () => {
    if (stars === 0 || !token) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await api.post(`/reviews/public/r/${token}/rating`, {
        star_rating: stars,
        comment: comment.trim() || undefined,
      });
      setResult(res);
    } catch (e: any) {
      setError(e?.message || "Failed to submit review.");
    } finally {
      setSubmitting(false);
    }
  }, [stars, comment, token]);

  const trackGoogleClick = useCallback(async () => {
    if (!token) return;
    try { await api.post(`/reviews/public/r/${token}/google-clicked`, {}); } catch { /* analytics — silent fail */ }
  }, [token]);

  if (loading) {
    return (
      <View style={s.root} testID="review-submit-loading">
        <ActivityIndicator size="large" color={colors.brand} style={{ marginTop: 100 }} />
      </View>
    );
  }

  if (error && !result) {
    return (
      <View style={s.root} testID="review-submit-error">
        <View style={s.center}>
          <Ionicons name="alert-circle-outline" size={48} color={colors.error} />
          <Text style={s.errorTitle}>{error}</Text>
        </View>
      </View>
    );
  }

  if (reqData?.expired) {
    return (
      <View style={s.root} testID="review-submit-expired">
        <View style={s.center}>
          <Ionicons name="time-outline" size={48} color={colors.muted} />
          <Text style={s.errorTitle}>This review link has expired.</Text>
        </View>
      </View>
    );
  }

  if (reqData?.already_submitted) {
    return (
      <View style={s.root} testID="review-submit-already">
        <View style={s.center}>
          <Ionicons name="checkmark-circle" size={48} color={colors.success} />
          <Text style={s.doneTitle}>Already submitted</Text>
          <Text style={s.doneSub}>You already left a {reqData.star_rating_submitted}-star review. Thank you!</Text>
        </View>
      </View>
    );
  }

  // After successful submission
  if (result) {
    if (result.next_step === "choose_platform") {
      const platforms = result.choose_platform || [];
      return (
        <View style={s.root} testID="review-submit-choose-platform">
          <ScrollView contentContainerStyle={s.content}>
            <View style={s.center}>
              <Ionicons name="star" size={48} color="#F59E0B" />
              <Text style={s.doneTitle}>Thanks for the {stars}-star rating!</Text>
              <Text style={s.doneSub}>
                Would you mind leaving a public review? It really helps us grow.
              </Text>
            </View>

            {platforms.map((p) => (
              <Pressable
                key={p.platform}
                style={[s.platformBtn, p.platform === "google" && s.platformBtnGoogle]}
                testID={`review-platform-${p.platform}`}
                onPress={async () => {
                  if (p.platform === "google") await trackGoogleClick();
                  Linking.openURL(p.url);
                }}
              >
                <Ionicons
                  name={p.platform === "google" ? "logo-google" : "star-outline"}
                  size={20}
                  color={p.platform === "google" ? "#fff" : colors.brand}
                />
                <Text style={[s.platformBtnText, p.platform === "google" && { color: "#fff" }]}>
                  Post on {p.display_name}
                </Text>
              </Pressable>
            ))}

            {result.google_review_url && !platforms.some((p) => p.platform === "google") ? (
              <Pressable
                style={[s.platformBtn, s.platformBtnGoogle]}
                testID="review-platform-google-fallback"
                onPress={async () => {
                  await trackGoogleClick();
                  Linking.openURL(result.google_review_url!);
                }}
              >
                <Ionicons name="logo-google" size={20} color="#fff" />
                <Text style={[s.platformBtnText, { color: "#fff" }]}>Post on Google</Text>
              </Pressable>
            ) : null}

            <Pressable style={s.skipLink} onPress={() => router.back()} testID="review-skip-public">
              <Text style={s.skipLinkText}>No thanks, maybe later</Text>
            </Pressable>
          </ScrollView>
        </View>
      );
    }

    // private_feedback (1-3 stars)
    return (
      <View style={s.root} testID="review-submit-private-feedback">
        <View style={s.center}>
          <Ionicons name="chatbubble-ellipses-outline" size={48} color={colors.brand} />
          <Text style={s.doneTitle}>Thank you for your feedback</Text>
          <Text style={s.doneSub}>
            We appreciate your honesty. Our team will review your comments and follow up if needed.
          </Text>
        </View>
      </View>
    );
  }

  // Star selection + comment form
  return (
    <View style={s.root} testID="review-submit-form">
      <ScrollView contentContainerStyle={s.content}>
        <Text style={s.heading}>
          How was your experience{reqData?.tech_name ? ` with ${reqData.tech_name}` : ""}?
        </Text>
        {reqData?.company_name ? (
          <Text style={s.companyName}>{reqData.company_name}</Text>
        ) : null}

        <View style={s.starsRow} testID="review-star-row">
          {[1, 2, 3, 4, 5].map((n) => (
            <Pressable
              key={n}
              onPress={() => setStars(n)}
              hitSlop={6}
              testID={`review-star-${n}`}
            >
              <Ionicons
                name={n <= stars ? "star" : "star-outline"}
                size={44}
                color={n <= stars ? "#F59E0B" : colors.border}
              />
            </Pressable>
          ))}
        </View>

        {stars > 0 ? (
          <Text style={s.starsLabel}>
            {stars === 5 ? "Excellent!" : stars === 4 ? "Great!" : stars === 3 ? "OK" : stars === 2 ? "Not great" : "Poor"}
          </Text>
        ) : null}

        <Text style={s.commentLabel}>
          {stars >= 4 ? "Anything you'd like to add? (optional)" : "Tell us what we can improve"}
        </Text>
        <TextInput
          testID="review-comment-input"
          style={s.commentInput}
          placeholder="Your feedback…"
          placeholderTextColor={colors.muted}
          value={comment}
          onChangeText={setComment}
          multiline
          numberOfLines={4}
          textAlignVertical="top"
        />

        {error ? <Text style={s.errorText} testID="review-submit-error">{error}</Text> : null}

        <Pressable
          style={[s.submitBtn, (stars === 0 || submitting) && { opacity: 0.5 }]}
          onPress={submit}
          disabled={stars === 0 || submitting}
          testID="review-submit-btn"
        >
          {submitting ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Text style={s.submitBtnText}>Submit Review</Text>
          )}
        </Pressable>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  content: { padding: spacing.xl, paddingBottom: spacing["3xl"] },
  center: { alignItems: "center", paddingTop: 60, paddingBottom: spacing.xl },
  heading: { fontFamily: font.bold, fontSize: 22, color: colors.onSurface, textAlign: "center", marginTop: 40 },
  companyName: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, textAlign: "center", marginTop: spacing.xs },
  starsRow: { flexDirection: "row", justifyContent: "center", gap: 12, marginTop: spacing.xl },
  starsLabel: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface, textAlign: "center", marginTop: spacing.md },
  commentLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginTop: spacing.xl, marginBottom: spacing.sm },
  commentInput: {
    borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, minHeight: 100,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  submitBtn: {
    backgroundColor: colors.brand, borderRadius: radius.md,
    paddingVertical: 14, alignItems: "center", marginTop: spacing.xl,
  },
  submitBtnText: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff" },
  errorText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.error, marginTop: spacing.sm, textAlign: "center" },
  errorTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: spacing.lg, textAlign: "center" },
  doneTitle: { fontFamily: font.bold, fontSize: 22, color: colors.onSurface, marginTop: spacing.lg, textAlign: "center" },
  doneSub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: spacing.sm, textAlign: "center", lineHeight: 22, paddingHorizontal: spacing.lg },
  platformBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    paddingVertical: 14, borderRadius: radius.md, borderWidth: 1.5,
    borderColor: colors.brand, marginTop: spacing.md,
  },
  platformBtnGoogle: { backgroundColor: "#4285F4", borderColor: "#4285F4" },
  platformBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  skipLink: { alignItems: "center", marginTop: spacing.xl },
  skipLinkText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted },
});
