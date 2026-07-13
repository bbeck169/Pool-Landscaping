import React from "react";
import { View, StyleSheet } from "react-native";
import { useRouter } from "expo-router";

import { colors } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import NewLeadForm from "@/src/components/NewLeadForm";

// Technician bottom-tab: quick "New Lead" capture (replaces the Jobs tab).
export default function NewLeadTab() {
  const router = useRouter();
  return (
    <View style={styles.root}>
      <Header title="New Lead" subtitle="Capture a prospect on the spot" />
      <NewLeadForm onDone={() => router.push("/leads")} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
});
