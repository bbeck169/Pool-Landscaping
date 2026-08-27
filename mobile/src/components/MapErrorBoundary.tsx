/**
 * MapErrorBoundary — Phase P16 · catch-all for map render errors.
 *
 * Wraps map components (DailyRouteMap, ScheduleMap, etc.) so a
 * native module crash, missing token, or shape error surfaces as a
 * compact card instead of crashing the entire schedule screen.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

interface Props {
  children: React.ReactNode;
  testID?: string;
}

interface State {
  error: Error | null;
}

export class MapErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.warn("[MapErrorBoundary]", error.message, info?.componentStack);
  }

  private _retry = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <View style={s.card} testID={this.props.testID || "map-error-boundary"}>
          <View style={s.row}>
            <Ionicons name="warning-outline" size={20} color="#92400E" />
            <Text style={s.msg} testID="map-error-boundary-message">
              Route map unavailable — {this.state.error.message}
            </Text>
          </View>
          <Pressable
            onPress={this._retry}
            style={s.retryBtn}
            testID="map-error-boundary-retry"
          >
            <Ionicons name="refresh" size={14} color="#fff" />
            <Text style={s.retryLabel}>Retry</Text>
          </Pressable>
        </View>
      );
    }
    return this.props.children;
  }
}

const s = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: "#FBBF24",
    borderRadius: radius.md,
    backgroundColor: "#FEF3C7",
    padding: spacing.md,
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  row: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
  },
  msg: {
    flex: 1,
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#92400E",
    lineHeight: 18,
  },
  retryBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    height: 36,
    borderRadius: radius.md,
    backgroundColor: colors.brand,
    alignSelf: "flex-start",
    paddingHorizontal: spacing.md,
  },
  retryLabel: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
});

export default MapErrorBoundary;
