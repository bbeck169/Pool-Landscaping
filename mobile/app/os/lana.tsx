// Phase 37 · Feb-2026 — Business OS Lana AI chat (P1.3).
// Web: LanaAndPlans.jsx. Backend: POST /business-os/lana/chat.
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, KeyboardAvoidingView, Platform } from "react-native";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { PrimaryButton, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

type Turn = { role: "user" | "assistant"; text: string };

export default function OsLana() {
  const [history, setHistory] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const send = useCallback(async () => {
    const q = input.trim();
    if (!q || busy) return;
    setHistory((h) => [...h, { role: "user", text: q }]);
    setInput("");
    setBusy(true);
    try {
      const r: any = await api.post("/business-os/lana/chat", { message: q });
      const reply = r?.reply || r?.response || r?.message || "(no reply)";
      setHistory((h) => [...h, { role: "assistant", text: String(reply) }]);
    } catch (e: any) {
      setHistory((h) => [...h, { role: "assistant", text: `Error: ${e?.message || "failed"}` }]);
    } finally {
      setBusy(false);
    }
  }, [input, busy]);

  return (
    <RoleGate level="strict_admin">
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.container}
        testID="os-lana-page"
      >
        <Header title="Lana AI" />
        <ScrollView contentContainerStyle={styles.body}>
          {history.length === 0 ? (
            <EmptyState
              icon="sparkles-outline"
              title="Ask Lana anything"
              subtitle="Business advisor + planning assistant. Try: 'What's slowing us down this month?'"
              testID="os-lana-empty"
            />
          ) : (
            history.map((t, i) => (
              <View
                key={i}
                style={[styles.bubble, t.role === "user" ? styles.userBubble : styles.aiBubble]}
                testID={`os-lana-turn-${i}`}
              >
                <Text style={t.role === "user" ? styles.userText : styles.aiText}>{t.text}</Text>
              </View>
            ))
          )}
          {busy && <Text style={styles.thinking}>Lana is thinking…</Text>}
        </ScrollView>
        <View style={styles.inputRow}>
          <TextInput
            value={input}
            onChangeText={setInput}
            placeholder="Ask Lana…"
            style={styles.input}
            editable={!busy}
            testID="os-lana-input"
          />
          <PrimaryButton
            label={busy ? "…" : "Send"}
            onPress={send}
            disabled={busy || !input.trim()}
            testID="os-lana-send"
          />
        </View>
      </KeyboardAvoidingView>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.sm, paddingBottom: spacing["3xl"] },
  bubble: { padding: spacing.md, borderRadius: radius.md, maxWidth: "88%" },
  userBubble: { alignSelf: "flex-end", backgroundColor: colors.brand },
  aiBubble: { alignSelf: "flex-start", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  userText: { fontFamily: font.regular, fontSize: fontSize.md, color: colors.onBrand || "#fff" },
  aiText: { fontFamily: font.regular, fontSize: fontSize.md, color: colors.onSurface },
  thinking: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, fontStyle: "italic", alignSelf: "flex-start" },
  inputRow: { flexDirection: "row", gap: spacing.sm, padding: spacing.md, borderTopWidth: 1, borderTopColor: colors.border, alignItems: "center" },
  input: { flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, padding: spacing.sm, fontFamily: font.regular, fontSize: fontSize.md, backgroundColor: colors.surface },
});
