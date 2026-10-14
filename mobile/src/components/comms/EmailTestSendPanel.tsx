/**
 * Email template test-send panel — P2 #11 mobile parity (web d34aec4e5).
 *
 * POST /comms/email-templates/{code}/test-send  body `{to?}`:
 *   200 → toast "Sent to <recipient>" (+ delivery status when not sent)
 *   400 test_recipient_not_allowed / _missing → backend `msg` verbatim
 *   403 → generic "Admin access required" (server body NOT echoed)
 *   429 → Retry-After seconds (ceil) countdown; button disabled meanwhile
 */
import React, { useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api_base, getAuthToken } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/ToastProvider";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { colors, font, fontSize, radius, spacing } from "@/src/theme";

export type TestSendRaw = { status: number; body: any; retryAfter: string | null };
export type TestSendOutcome =
  | { kind: "sent"; recipient: string; deliveryStatus: string | null }
  | { kind: "rate_limited"; retryAfterS: number; message: string }
  | { kind: "error"; message: string };

/**
 * ONE-OFF DIRECT `fetch` (approved P2 #11 mobile parity, do not "clean up"):
 * the shared `api` wrapper's `ApiError` keeps only `status` + `detail` and
 * DROPS response headers, but the 429 path needs the `Retry-After` header
 * to drive the countdown. Bearer token + base URL come from the same
 * helpers the wrapper uses. Any future refactor must either keep this raw
 * call or teach `ApiError` to carry headers — never silently lose
 * Retry-After.
 */
export async function postTemplateTestSend(code: string, to?: string): Promise<TestSendRaw> {
  const token = await getAuthToken();
  const res = await fetch(
    `${api_base()}/comms/email-templates/${encodeURIComponent(code)}/test-send`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(to ? { to } : {}),
    },
  );
  let body: any = null;
  try { body = await res.json(); } catch { body = null; }
  return { status: res.status, body, retryAfter: res.headers?.get?.("Retry-After") ?? null };
}

/** Retry-After → whole seconds, ceiling. Delta-seconds or HTTP-date; fallback 60. */
export function parseRetryAfter(v: string | null | undefined, now: number = Date.now()): number {
  if (v != null && String(v).trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return Math.max(1, Math.ceil(n));
    const at = Date.parse(String(v));
    if (Number.isFinite(at)) return Math.max(1, Math.ceil((at - now) / 1000));
  }
  return 60;
}

const detailMsg = (body: any): string | null => {
  const d = body?.detail;
  if (d && typeof d === "object" && typeof d.msg === "string") return d.msg;
  return typeof d === "string" ? d : null;
};

export function interpretTestSend(r: TestSendRaw): TestSendOutcome {
  if (r.status >= 200 && r.status < 300) {
    return { kind: "sent", recipient: r.body?.recipient || "(you)", deliveryStatus: r.body?.status ?? null };
  }
  if (r.status === 429) {
    const s = parseRetryAfter(r.retryAfter);
    return { kind: "rate_limited", retryAfterS: s, message: `Rate limit reached — try again in ${s}s` };
  }
  if (r.status === 403) return { kind: "error", message: "Admin access required" };
  if (r.status === 401) return { kind: "error", message: "Session expired — sign in again" };
  if (r.status === 400) return { kind: "error", message: detailMsg(r.body) || "Recipient not allowed" };
  if (r.status === 404) return { kind: "error", message: "Template not found" };
  return { kind: "error", message: detailMsg(r.body) || `Test send failed (${r.status})` };
}

/** Toast copy for a 2xx — always names the recipient. */
export function sentToastCopy(o: { recipient: string; deliveryStatus: string | null }) {
  const st = (o.deliveryStatus || "").toLowerCase();
  if (st === "failed") return { msg: `Send to ${o.recipient} failed at the provider`, variant: "error" as const };
  if (st && st !== "sent" && st !== "queued" && st !== "delivered") {
    return { msg: `Sent to ${o.recipient} — delivery ${st.replace(/_/g, " ")}`, variant: "info" as const };
  }
  return { msg: `Sent to ${o.recipient}`, variant: "success" as const };
}

export default function EmailTestSendPanel({ code }: { code: string }) {
  const { user } = useAuth();
  const { showToast } = useToast();
  const [to, setTo] = useState<string>(user?.email || "");
  const [sending, setSending] = useState(false);
  const [cooldown, setCooldown] = useState(false);
  const [waitS, setWaitS] = useState(0);
  const [message, setMessage] = useState<{ text: string; tone: "ok" | "err" } | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const alive = useRef(true);

  useEffect(() => () => {
    alive.current = false;
    if (timer.current) clearInterval(timer.current);
  }, []);

  const startCountdown = (s: number) => {
    if (timer.current) clearInterval(timer.current);
    setWaitS(s);
    timer.current = setInterval(() => {
      setWaitS((n) => {
        if (n <= 1) {
          if (timer.current) clearInterval(timer.current);
          timer.current = null;
          return 0;
        }
        return n - 1;
      });
    }, 1000);
  };

  const onSend = async () => {
    setSending(true);
    setMessage(null);
    let outcome: TestSendOutcome;
    try {
      outcome = interpretTestSend(await postTemplateTestSend(code, to.trim() || undefined));
    } catch {
      outcome = { kind: "error", message: "Network error — check your connection" };
    }
    if (!alive.current) return;
    setSending(false);
    if (outcome.kind === "sent") {
      const t = sentToastCopy(outcome);
      showToast(t.msg, t.variant);
      setMessage({ text: t.msg, tone: t.variant === "error" ? "err" : "ok" });
      // 2-second cooldown against double-fires (web parity).
      setCooldown(true);
      setTimeout(() => alive.current && setCooldown(false), 2000);
    } else {
      if (outcome.kind === "rate_limited") startCountdown(outcome.retryAfterS);
      showToast(outcome.message, "error");
      setMessage({ text: outcome.message, tone: "err" });
    }
  };

  const disabled = sending || cooldown || waitS > 0;
  const label = waitS > 0 ? `Retry in ${waitS}s` : sending ? "Sending…" : "Send test";

  return (
    <View style={s.card} testID="comms-email-test-send-panel">
      <Text style={s.title}>Send test</Text>
      <Text style={s.hint}>
        Subject is prefixed [TEST]. Recipient must be you or another admin in this account.
      </Text>
      <AppTextInput
        testID="comms-email-test-send-input"
        style={s.input}
        value={to}
        onChangeText={setTo}
        placeholder="(your email)"
        placeholderTextColor={colors.muted}
        keyboardType="email-address"
        autoCapitalize="none"
        autoCorrect={false}
      />
      <TouchableOpacity
        testID="comms-email-test-send-submit"
        style={[s.btn, disabled && s.btnDisabled]}
        onPress={onSend}
        disabled={disabled}
        accessibilityState={{ disabled }}
      >
        {sending ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="paper-plane-outline" size={16} color="#fff" />}
        <Text style={s.btnLabel} testID="comms-email-test-send-label">{label}</Text>
      </TouchableOpacity>
      {message ? (
        <Text style={[s.msg, message.tone === "err" && s.msgErr]} testID="comms-email-test-send-message">
          {message.text}
        </Text>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.border, gap: spacing.sm, marginBottom: spacing.lg,
  },
  title: { fontFamily: font.bold, fontSize: 11, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  hint: { fontFamily: font.regular, fontSize: 12, color: colors.muted },
  input: {
    minHeight: 44, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface, paddingHorizontal: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface,
  },
  btn: {
    minHeight: 44, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: colors.brand, borderRadius: radius.sm,
  },
  btnDisabled: { opacity: 0.5 },
  btnLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  msg: { fontFamily: font.medium, fontSize: 12, color: "#065F46" },
  msgErr: { color: colors.error },
});
