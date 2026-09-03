/**
 * ScheduleErrorBoundary — K36 · Schedule crash hardening.
 *
 * Screen-scoped React error boundary. Sits between the tab
 * navigator and the Schedule calendar screen so a render throw
 * (null-deref on `me`, `tenant`, `assignments`; native module
 * missing key; shape drift) surfaces as an actionable card instead
 * of crashing the tab and dumping the iOS process (0x8badf00d watchdog).
 *
 * Also persists the error into the diagnostic ring-buffer so the
 * next launch can attempt to upload it and the "Send diagnostics"
 * button captures it.
 *
 * Kept intentionally light: no theme imports, no icon library, pure
 * RN primitives + inline styles so it can render even when the
 * theme module is the thing that threw.
 */
import React from "react";
import { View, Text, ScrollView, Pressable, StyleSheet, Platform } from "react-native";
import { persistCrash, logNav } from "@/src/utils/diagnostics";

type Props = {
  children: React.ReactNode;
  onReset?: () => void;
};

type State = { error: Error | null; componentStack: string | null };

export class ScheduleErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null, componentStack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.warn("[ScheduleErrorBoundary]", error?.message || error, info?.componentStack);
    persistCrash(error, info?.componentStack ?? null);
    logNav("schedule.error-boundary.caught", {
      message: String(error?.message || error || "unknown").slice(0, 120),
    });
    this.setState({ componentStack: info?.componentStack ?? null });
  }

  private _retry = () => {
    logNav("schedule.error-boundary.retry");
    this.setState({ error: null, componentStack: null });
    this.props.onReset?.();
  };

  render() {
    const err = this.state.error;
    if (!err) return this.props.children as React.ReactElement;

    const msg = String(err?.message || err || "unknown");
    return (
      <View style={s.root} testID="schedule-error-boundary">
        <ScrollView contentContainerStyle={s.scroll}>
          <Text style={s.title}>Schedule failed to load</Text>
          <Text style={s.subtitle}>
            Something on the Schedule tab crashed. Your session is still active —
            tap Try Again, or head to More → Send Diagnostics so we can fix it.
          </Text>
          <View style={s.msgBox}>
            <Text style={s.msgLabel}>ERROR</Text>
            <Text style={s.msg} testID="schedule-error-boundary-message">
              {msg}
            </Text>
          </View>
          {this.state.componentStack ? (
            <View style={s.stackBox}>
              <Text style={s.msgLabel}>COMPONENT STACK</Text>
              <Text style={s.stack} numberOfLines={12}>
                {this.state.componentStack}
              </Text>
            </View>
          ) : null}
          <Pressable
            onPress={this._retry}
            style={s.btn}
            testID="schedule-error-boundary-retry"
          >
            <Text style={s.btnText}>Try Again</Text>
          </Pressable>
        </ScrollView>
      </View>
    );
  }
}

const s = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: "#0B1220",
    paddingTop: Platform.OS === "ios" ? 60 : 40,
  },
  scroll: { padding: 24, gap: 16 },
  title: { fontSize: 22, fontWeight: "700", color: "#F8FAFC" },
  subtitle: { fontSize: 14, color: "#94A3B8", lineHeight: 20 },
  msgBox: {
    backgroundColor: "#1E293B",
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#B91C1C",
    gap: 4,
  },
  stackBox: {
    backgroundColor: "#1E293B",
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#334155",
    gap: 4,
  },
  msgLabel: { fontSize: 10, fontWeight: "700", color: "#94A3B8", letterSpacing: 1 },
  msg: {
    fontSize: 14,
    color: "#FCA5A5",
    fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
  },
  stack: {
    fontSize: 11,
    color: "#CBD5E1",
    fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
    lineHeight: 16,
  },
  btn: {
    backgroundColor: "#3B82F6",
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 10,
    alignItems: "center",
    marginTop: 12,
  },
  btnText: { color: "#FFFFFF", fontSize: 16, fontWeight: "700" },
});

export default ScheduleErrorBoundary;
