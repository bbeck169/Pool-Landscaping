/**
 * RootErrorBoundary — Feb-2026 · P2→P0 hotfix companion.
 *
 * Wraps the entire mobile provider tree so that any uncaught JS
 * exception during render (missing null-guard, shape drift, native
 * module deref) surfaces as a visible diagnostic screen instead of
 * a silent blank white — which is what happened during the P0 tech
 * cluster on production Aug 25 2026.
 *
 * The boundary itself is intentionally minimal: no theme imports (in
 * case ``@/src/theme`` is the thing that threw), no icon library
 * (in case fonts didn't load), no navigation (in case the router is
 * the source of the crash). Pure RN primitives + inline styles.
 */
import React from "react";
import { View, Text, ScrollView, Pressable, StyleSheet, Platform } from "react-native";

type Props = { children: React.ReactNode };
type State = { error: Error | null; stack: string | null };

export class RootErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null, stack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Persist for the render layer + push into the JS console so
    // that adb logcat / Metro / Sentry (if added later) picks it up.
    // eslint-disable-next-line no-console
    console.error("[RootErrorBoundary]", error, info?.componentStack);
    this.setState({ stack: info?.componentStack ?? null });
  }

  private _retry = () => this.setState({ error: null, stack: null });

  render() {
    if (this.state.error) {
      const msg = String(this.state.error?.message || this.state.error || "unknown");
      return (
        <View style={styles.root} testID="root-error-boundary">
          <ScrollView contentContainerStyle={styles.scroll}>
            <Text style={styles.title}>App failed to render</Text>
            <Text style={styles.subtitle}>
              An error prevented the screen from loading. This message is
              here so we can diagnose faster than a blank screen would let
              us.
            </Text>
            <View style={styles.msgBox}>
              <Text style={styles.msgLabel}>ERROR</Text>
              <Text style={styles.msg} testID="root-error-boundary-message">
                {msg}
              </Text>
            </View>
            {this.state.stack ? (
              <View style={styles.stackBox}>
                <Text style={styles.msgLabel}>COMPONENT STACK</Text>
                <Text style={styles.stack} numberOfLines={12}>
                  {this.state.stack}
                </Text>
              </View>
            ) : null}
            <Pressable
              onPress={this._retry}
              style={styles.btn}
              testID="root-error-boundary-retry"
            >
              <Text style={styles.btnText}>Try Again</Text>
            </Pressable>
            <Text style={styles.footer}>
              If this keeps happening, sign out and back in, or reinstall
              the app. Share this message with support.
            </Text>
          </ScrollView>
        </View>
      );
    }
    return this.props.children as React.ReactElement;
  }
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: "#0B1220",
    paddingTop: Platform.OS === "ios" ? 60 : 40,
  },
  scroll: { padding: 24, gap: 16 },
  title: {
    fontSize: 24, fontWeight: "700", color: "#F8FAFC",
  },
  subtitle: {
    fontSize: 14, color: "#94A3B8", lineHeight: 20,
  },
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
  msgLabel: {
    fontSize: 10, fontWeight: "700", color: "#94A3B8", letterSpacing: 1,
  },
  msg: {
    fontSize: 14, color: "#FCA5A5", fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace",
  },
  stack: {
    fontSize: 11, color: "#CBD5E1", fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", lineHeight: 16,
  },
  btn: {
    backgroundColor: "#3B82F6",
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 10,
    alignItems: "center",
    marginTop: 12,
  },
  btnText: {
    color: "#FFFFFF", fontSize: 16, fontWeight: "700",
  },
  footer: {
    fontSize: 12, color: "#64748B", marginTop: 16, textAlign: "center",
  },
});

export default RootErrorBoundary;
