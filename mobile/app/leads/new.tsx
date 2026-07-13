import React from "react";
import { View, StyleSheet } from "react-native";
import { useRouter } from "expo-router";

import { colors } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import NewLeadForm from "@/src/components/NewLeadForm";

export default function NewLead() {
  const router = useRouter();
  return (
    <View style={styles.root}>
      <Header title="New Lead" back subtitle="Capture a prospect on the spot" />
      <NewLeadForm onDone={() => router.back()} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
});
