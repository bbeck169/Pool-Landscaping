/**
 * PaymentMethodPromptModal.tsx — Phase K24
 *
 * Modal shown on portal home (first mount per app session) when:
 *   - ``prompt_kind === "missing"``  → "Add a payment method"
 *   - ``prompt_kind === "expiring"`` → "Update your card"
 *
 * Fetches ``GET /api/portal/payment-method/prompt-status``.
 * "Remind me tomorrow" POSTs snooze (24 h) and closes.
 * Impersonation JWT hides the modal entirely (K13 interlock).
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/* ── types ──────────────────────────────────────────── */

export type ExpiringCard = {
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  days_until_expiry: number;
};

export type PromptStatus = {
  prompt_kind: "none" | "missing" | "expiring";
  original_prompt_kind: "none" | "missing" | "expiring";
  snoozed_until?: string | null;
  expiring_cards?: ExpiringCard[];
};

/* ── session guard ──────────────────────────────────── */

// Module-level flag — ensures the modal only fires once per cold
// start / JS bundle mount. Survives re-renders but resets on reload.
let _modalShownThisSession = false;

/** Reset for testing purposes only. */
export function _resetModalShown() { _modalShownThisSession = false; }

/* ── component ──────────────────────────────────────── */

export default function PaymentMethodPromptModal() {
  const router = useRouter();
  const { isImpersonating } = useAuth();

  const [visible, setVisible] = useState(false);
  const [status, setStatus] = useState<PromptStatus | null>(null);
  const [snoozing, setSnoozing] = useState(false);

  useEffect(() => {
    // K13 interlock — never show during impersonation.
    if (isImpersonating) return;
    if (_modalShownThisSession) return;

    let cancelled = false;
    (async () => {
      try {
        const res: PromptStatus = await api.get(
          "/portal/payment-method/prompt-status",
        );
        if (cancelled) return;
        if (res.prompt_kind && res.prompt_kind !== "none") {
          setStatus(res);
          setVisible(true);
          _modalShownThisSession = true;
        }
      } catch {
        // Fail silently — missing endpoint or network error.
      }
    })();
    return () => { cancelled = true; };
  }, [isImpersonating]);

  const close = () => setVisible(false);

  const handlePrimary = () => {
    close();
    router.push("/portal/payment-method");
  };

  const handleSnooze = async () => {
    setSnoozing(true);
    try {
      await api.post("/portal/payment-method/prompt-snooze", {});
    } catch {
      // Snooze POST failure is non-fatal.
    }
    setSnoozing(false);
    close();
  };

  if (!visible || !status) return null;

  const isMissing = status.prompt_kind === "missing";

  return (
    <Modal
      visible
      transparent
      animationType="fade"
      onRequestClose={close}
      testID="pm-prompt-modal"
    >
      <Pressable style={s.overlay} onPress={close}>
        <Pressable style={s.card} onPress={() => {}} testID="pm-prompt-modal-card">
          {/* Icon */}
          <View style={[s.iconWrap, isMissing ? s.iconMissing : s.iconExpiring]}>
            <Ionicons
              name={isMissing ? "wallet-outline" : "warning-outline"}
              size={28}
              color={isMissing ? "#1D4ED8" : "#B45309"}
            />
          </View>

          {/* Title */}
          <Text style={s.title} testID="pm-prompt-modal-title">
            {isMissing ? "Add a payment method" : "Update your card"}
          </Text>

          {/* Body */}
          {isMissing ? (
            <Text style={s.body} testID="pm-prompt-modal-body">
              Please add a card on file so we can process payments for your
              upcoming services. You won{"'"}t be charged until an invoice is
              issued.
            </Text>
          ) : (
            <View testID="pm-prompt-modal-body">
              <Text style={s.body}>
                {(status.expiring_cards?.length || 0) > 1
                  ? "Some of your cards are expiring soon:"
                  : "Your card is expiring soon:"}
              </Text>
              {(status.expiring_cards || []).map((c, i) => (
                <View key={i} style={s.cardRow}>
                  <Ionicons name="card-outline" size={16} color="#B45309" />
                  <Text style={s.cardText}>
                    {c.brand} ending {c.last4} · expires {c.exp_month}/{c.exp_year}
                    {c.days_until_expiry <= 0
                      ? " (expired)"
                      : ` (${c.days_until_expiry}d left)`}
                  </Text>
                </View>
              ))}
            </View>
          )}

          {/* Primary CTA */}
          <Pressable
            style={s.primaryBtn}
            onPress={handlePrimary}
            testID="pm-prompt-primary-btn"
          >
            <Ionicons name={isMissing ? "add-circle-outline" : "refresh-outline"} size={18} color="#fff" />
            <Text style={s.primaryText}>
              {isMissing ? "Add card" : "Update card"}
            </Text>
          </Pressable>

          {/* Snooze */}
          <Pressable
            style={s.snoozeBtn}
            onPress={handleSnooze}
            disabled={snoozing}
            testID="pm-prompt-snooze-btn"
          >
            {snoozing ? (
              <ActivityIndicator size="small" color={colors.muted} />
            ) : (
              <Text style={s.snoozeText}>Remind me tomorrow</Text>
            )}
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/* ── styles ─────────────────────────────────────────── */

const s = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.lg,
  },
  card: {
    width: "100%",
    maxWidth: 380,
    backgroundColor: "#fff",
    borderRadius: radius.lg + 4,
    padding: spacing.xl,
    alignItems: "center",
    gap: 12,
    shadowColor: "#000",
    shadowOpacity: 0.2,
    shadowOffset: { width: 0, height: 8 },
    shadowRadius: 24,
    elevation: 10,
  },
  iconWrap: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 4,
  },
  iconMissing: { backgroundColor: "#DBEAFE" },
  iconExpiring: { backgroundColor: "#FEF3C7" },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
    textAlign: "center",
  },
  body: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 22,
  },
  cardRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 8,
    backgroundColor: "#FFFBEB",
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  cardText: {
    flex: 1,
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#92400E",
    lineHeight: 18,
  },
  primaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.brand,
    borderRadius: radius.md,
    paddingVertical: 14,
    paddingHorizontal: 24,
    width: "100%",
    marginTop: 8,
  },
  primaryText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
  snoozeBtn: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    minHeight: 40,
    justifyContent: "center",
    alignItems: "center",
  },
  snoozeText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.muted,
    textDecorationLine: "underline",
  },
});
