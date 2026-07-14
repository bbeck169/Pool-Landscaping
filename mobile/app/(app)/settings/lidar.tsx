/**
 * Phase 21 · Mobile Settings — LiDAR / 3D room scan toggle.
 * Native-build-ready path (iOS ARKit RoomPlan). Safe no-op in Expo Go.
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Switch, Platform, ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import Constants, { ExecutionEnvironment } from "expo-constants";

import { storage } from "@/src/utils/storage";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

const LIDAR_ENABLED_KEY = "estimator_lidar_enabled";

export default function LidarSettings() {
  const [enabled, setEnabled] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    (async () => {
      const v = await storage.getItem<boolean>(LIDAR_ENABLED_KEY, false);
      setEnabled(!!v);
      setLoaded(true);
    })();
  }, []);

  const toggle = async (v: boolean) => {
    setEnabled(v);
    await storage.setItem(LIDAR_ENABLED_KEY, v);
  };

  const isExpoGo =
    Constants.executionEnvironment === ExecutionEnvironment.StoreClient;
  const nativeReady = Platform.OS === "ios" && !isExpoGo;

  return (
    <View style={styles.root}>
      <Header title="LiDAR / 3D scan" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
        <View style={styles.card}>
          <View style={styles.row}>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={styles.title}>
                Attach 3D room scan to estimates
              </Text>
              <Text style={styles.body}>
                Uses Apple ARKit RoomPlan to capture wall dimensions and
                floor area, which sharpens the AI estimate. iOS native
                build required.
              </Text>
            </View>
            {loaded && (
              <Switch value={enabled} onValueChange={toggle}
                       trackColor={{ true: colors.brand, false: "#CBD5E1" }}
                       testID="lidar-toggle" />
            )}
          </View>
        </View>

        <View style={[styles.card,
                        { marginTop: spacing.md,
                          backgroundColor: nativeReady
                            ? colors.brandTertiary : "#FEF3C7" }]}>
          <View style={styles.row}>
            <Ionicons
              name={nativeReady ? "checkmark-circle" : "information-circle"}
              size={20}
              color={nativeReady ? colors.brand : "#92400E"}
            />
            <View style={{ flex: 1, marginLeft: spacing.sm }}>
              <Text style={[styles.title,
                              { color: nativeReady
                                  ? colors.brand : "#92400E" }]}>
                {nativeReady
                  ? "Native iOS build detected — ready for LiDAR."
                  : "Running in Expo Go (safe no-op)"}
              </Text>
              <Text style={[styles.body,
                              { color: nativeReady
                                  ? colors.brand : "#92400E" }]}>
                {nativeReady
                  ? "Scans will be captured with ARKit RoomPlan when the estimate flow opens."
                  : "3D scan requires an iOS native build. Toggling this on is remembered — it'll auto-activate once you install the built app."}
              </Text>
            </View>
          </View>
        </View>

        <View style={[styles.card, { marginTop: spacing.md }]}>
          <Text style={styles.title}>Privacy</Text>
          <Text style={styles.body}>
            Scans are stored on your tenant only and used exclusively as
            AI-estimate context. They are never shared across tenants.
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
  },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  title: { fontFamily: font.bold, fontSize: fontSize.base,
            color: colors.onSurface },
  body: { fontFamily: font.regular, fontSize: fontSize.sm,
           color: colors.muted, marginTop: 4, lineHeight: 18 },
});
