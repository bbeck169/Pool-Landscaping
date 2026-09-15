// Phase 37 · Feb-2026 — Business OS Lana AI chat (P1.3).
// Phase 49 · Feb-2026 — Voice input, schedule-intent confirmation card,
// admin todos panel. Voice uses `expo-speech-recognition` (requires a
// dev-client build — see EXPO_GO_RUNBOOK.md).
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, KeyboardAvoidingView,
  Platform, Pressable, Alert } from "react-native";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { PrimaryButton, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Turn = { role: "user" | "assistant"; text: string; card?: any };
type Todo = { id: string; text: string; completed: boolean; created_at: string; due_at?: string | null };

// Dynamic import so Expo Go doesn't crash on the native module — see
// Phase 38b Mapbox convention.
let _speech: any = null;
try {
   
  _speech = require("expo-speech-recognition");
} catch (_) {
  _speech = null;
}

export default function OsLana() {
  const [history, setHistory] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [pendingSchedule, setPendingSchedule] = useState<any>(null);
  const [todos, setTodos] = useState<Todo[]>([]);

  const loadTodos = useCallback(async () => {
    try {
      const r: any = await api.get("/lana/todos");
      setTodos(Array.isArray(r?.items) ? r.items : []);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { loadTodos(); }, [loadTodos]);

  const send = useCallback(async (override?: string) => {
    const q = (override ?? input).trim();
    if (!q || busy) return;
    setHistory((h) => [...h, { role: "user", text: q }]);
    setInput("");
    setBusy(true);
    try {
      const r: any = await api.post("/business-os/lana/chat", { message: q });
      const reply = r?.reply || r?.response || r?.message || "(no reply)";
      const card = r?.intent && r.intent.kind !== "chat" ? r.intent : null;
      setHistory((h) => [...h, { role: "assistant", text: String(reply), card }]);
      if (card?.kind === "schedule_job" && card?.preview?.ok) {
        setPendingSchedule(card.preview);
      } else if (card?.kind === "add_todo") {
        loadTodos();
      } else if (card?.kind === "set_reminder") {
        // Reminder created server-side; nothing to load here.
      }
    } catch (e: any) {
      setHistory((h) => [...h, { role: "assistant", text: `Error: ${e?.message || "failed"}` }]);
    } finally {
      setBusy(false);
    }
  }, [busy, input, loadTodos]);

  const confirmSchedule = useCallback(async () => {
    if (!pendingSchedule) return;
    setBusy(true);
    try {
      const r: any = await api.post("/business-os/lana/schedule/commit", {
        customer_id: pendingSchedule.customer_id,
        service_type: pendingSchedule.service_type,
        scheduled_date: pendingSchedule.scheduled_date,
        title: pendingSchedule.title,
      });
      if (r?.ok) {
        setHistory((h) => [...h, { role: "assistant", text: `Booked job ${r.job?.id || ""} ✓` }]);
      } else {
        setHistory((h) => [...h, { role: "assistant", text: `Could not book: ${r?.reason || "unknown"}` }]);
      }
    } catch (e: any) {
      setHistory((h) => [...h, { role: "assistant", text: `Error: ${e?.message || "failed"}` }]);
    } finally {
      setPendingSchedule(null);
      setBusy(false);
    }
  }, [pendingSchedule]);

  const toggleTodo = useCallback(async (t: Todo) => {
    try {
      await api.patch(`/lana/todos/${t.id}`, { completed: !t.completed });
      loadTodos();
    } catch { /* ignore */ }
  }, [loadTodos]);

  // ── Voice input ────────────────────────────────────────────────────
  const startVoice = useCallback(async () => {
    if (!_speech) {
      Alert.alert(
        "Voice unavailable",
        "Voice input requires the dev-client build. Type your message instead.",
      );
      return;
    }
    try {
      const { granted } = await _speech.requestPermissionsAsync?.() || { granted: true };
      if (!granted) {
        Alert.alert("Permission denied", "Please enable microphone access in Settings.");
        return;
      }
      setListening(true);
      _speech.start?.({ lang: "en-US", interimResults: true });
      _speech.addListener?.("result", (ev: any) => {
        const t = ev?.results?.[0]?.transcript || "";
        if (t) setInput(t);
        if (ev?.isFinal) {
          _speech.stop?.();
          setListening(false);
          if (t.trim()) send(t.trim());
        }
      });
    } catch (e: any) {
      setListening(false);
      Alert.alert("Voice error", e?.message || "Could not start voice input.");
    }
  }, [send]);

  const stopVoice = useCallback(() => {
    if (_speech?.stop) _speech.stop();
    setListening(false);
  }, []);

  return (
    <RoleGate level="admin_plus">
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.container}
        testID="os-lana-page"
      >
        <Header title="Lana AI" />
        <ScrollView contentContainerStyle={styles.body}>
          {history.length === 0 ? (
            <EmptyState
              icon="chatbubbles-outline"
              title="Ask Lana anything"
              subtitle='Try "schedule a pool clean for Alan Wednesday at 10am" or tap the mic.'
              testID="os-lana-empty"
            />
          ) : history.map((turn, i) => (
            <View
              key={i}
              style={[styles.turn, turn.role === "user" ? styles.turnUser : styles.turnBot]}
              testID={`os-lana-turn-${i}`}
            >
              <Text style={styles.turnText}>{turn.text}</Text>
            </View>
          ))}

          {pendingSchedule ? (
            <View style={styles.confirmCard} testID="os-lana-schedule-confirm">
              <Text style={styles.confirmTitle}>Confirm job</Text>
              <Text style={styles.confirmLine}>Customer: {pendingSchedule.customer_name}</Text>
              <Text style={styles.confirmLine}>Service:  {pendingSchedule.service_type}</Text>
              <Text style={styles.confirmLine}>When:     {pendingSchedule.scheduled_date}</Text>
              <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
                <PrimaryButton label="Confirm" onPress={confirmSchedule}
                                testID="os-lana-schedule-confirm-yes" />
                <PrimaryButton label="Cancel" onPress={() => setPendingSchedule(null)}
                                variant="ghost" testID="os-lana-schedule-confirm-no" />
              </View>
            </View>
          ) : null}

          {todos.length > 0 ? (
            <View style={styles.todos} testID="os-lana-todos">
              <Text style={styles.todosTitle}>Your todos</Text>
              {todos.map((t) => (
                <Pressable
                  key={t.id}
                  onPress={() => toggleTodo(t)}
                  style={styles.todoRow}
                  testID={`os-lana-todo-${t.id}`}
                >
                  <Text style={[styles.todoText, t.completed && styles.todoDone]}>
                    {t.completed ? "☑ " : "☐ "}{t.text}
                  </Text>
                </Pressable>
              ))}
            </View>
          ) : null}
        </ScrollView>

        <View style={styles.inputRow}>
          <IconButton
            icon={listening ? "stop-circle-outline" : "mic-outline"}
            onPress={listening ? stopVoice : startVoice}
            testID="os-lana-mic"
          />
          <AppTextInput
            style={styles.input}
            value={input}
            onChangeText={setInput}
            placeholder="Message Lana…"
            editable={!busy}
            onSubmitEditing={() => send()}
            testID="os-lana-input"
          />
          <PrimaryButton label="Send" onPress={() => send()}
                          disabled={busy || !input.trim()} testID="os-lana-send" />
        </View>
      </KeyboardAvoidingView>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  turn: { padding: spacing.md, borderRadius: radius.md, maxWidth: "90%" },
  turnUser: { alignSelf: "flex-end", backgroundColor: colors.brandTertiary },
  turnBot: { alignSelf: "flex-start", backgroundColor: colors.surfaceSecondary },
  turnText: { fontFamily: font.regular, fontSize: fontSize.md, color: colors.onSurface },
  confirmCard: { padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
                  borderColor: colors.brand, backgroundColor: colors.surface, gap: 2 },
  confirmTitle: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface,
                   marginBottom: spacing.xs },
  confirmLine: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  todos: { padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
            borderColor: colors.border, backgroundColor: colors.surface, gap: 4 },
  todosTitle: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.muted,
                 textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 },
  todoRow: { paddingVertical: 4 },
  todoText: { fontFamily: font.regular, fontSize: fontSize.md, color: colors.onSurface },
  todoDone: { textDecorationLine: "line-through", color: colors.muted },
  inputRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm,
               padding: spacing.md, borderTopWidth: 1, borderTopColor: colors.border,
               backgroundColor: colors.surface },
  input: { flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
            padding: spacing.sm, fontFamily: font.regular, fontSize: fontSize.md,
            backgroundColor: colors.surface, color: colors.onSurface },
});
