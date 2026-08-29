/**
 * Phase O5 · OfflineGate — wraps category-D screens that require
 * network connectivity. Shows a friendly "Requires network" state
 * instead of spinning forever or crashing.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useOnline } from "@/src/offline";

type Props = {
  children: React.ReactNode;
  /** Label shown when offline. Default: "This feature requires an internet connection." */
  message?: string;
  testID?: string;
};

export function OfflineGate({ children, message, testID }: Props) {
  const online = useOnline();

  if (!online) {
    return (
      <View style={styles.container} testID={testID ?? "offline-gate"}>
        <MaterialCommunityIcons name="wifi-off" size={48} color="#94a3b8" />
        <Text style={styles.title}>No connection</Text>
        <Text style={styles.message}>
          {message ?? "This feature requires an internet connection."}
        </Text>
        <Text style={styles.hint}>Please reconnect and try again.</Text>
      </View>
    );
  }

  return <>{children}</>;
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 32,
    backgroundColor: "#f8fafc",
  },
  title: {
    fontSize: 18,
    fontWeight: "700",
    color: "#334155",
    marginTop: 16,
  },
  message: {
    fontSize: 14,
    color: "#64748b",
    textAlign: "center",
    marginTop: 8,
    lineHeight: 20,
  },
  hint: {
    fontSize: 13,
    color: "#94a3b8",
    marginTop: 12,
  },
});
