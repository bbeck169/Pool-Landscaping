/**
 * ARPermissionGate — AR-1 setup.
 *
 * Checks camera + motion-sensor permissions before allowing AR content
 * to mount. Shows a navy-themed onboarding card when permissions are
 * not yet granted.
 *
 * Props:
 *   onGranted()  — called once BOTH camera + motion are authorised.
 *   placeholder   — ReactNode to render after permissions granted
 *                   (AR-2 will replace this with the actual AR scene).
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Alert,
  Linking,
  Platform,
  ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  getCameraPermissionsAsync,
  requestCameraPermissionsAsync,
} from "expo-image-picker";
import { DeviceMotion } from "expo-sensors";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/* ── types ─────────────────────────────────────────────────────── */
interface Props {
  onGranted: () => void;
  placeholder?: React.ReactNode;
}

type PermState = "checking" | "needs-onboarding" | "granted";

/* ── helpers ───────────────────────────────────────────────────── */
async function checkCamera(): Promise<{ granted: boolean; canAsk: boolean }> {
  const { status, canAskAgain } = await getCameraPermissionsAsync();
  return { granted: status === "granted", canAsk: canAskAgain };
}

async function checkMotion(): Promise<{ granted: boolean; canAsk: boolean }> {
  // Android doesn't gate motion sensors behind a runtime permission
  if (Platform.OS === "android") return { granted: true, canAsk: true };
  try {
    const { status, canAskAgain } = await DeviceMotion.getPermissionsAsync();
    return { granted: status === "granted", canAsk: canAskAgain };
  } catch {
    // If expo-sensors doesn't support permission checks on this platform,
    // treat as granted (web preview, older devices).
    return { granted: true, canAsk: true };
  }
}

/* ── component ─────────────────────────────────────────────────── */
export default function ARPermissionGate({ onGranted, placeholder }: Props) {
  const insets = useSafeAreaInsets();
  const [state, setState] = useState<PermState>("checking");
  const [camOk, setCamOk] = useState(false);
  const [motionOk, setMotionOk] = useState(false);
  const [requesting, setRequesting] = useState(false);

  const runChecks = useCallback(async () => {
    setState("checking");
    const cam = await checkCamera();
    const mot = await checkMotion();
    setCamOk(cam.granted);
    setMotionOk(mot.granted);
    if (cam.granted && mot.granted) {
      setState("granted");
      onGranted();
    } else {
      setState("needs-onboarding");
    }
  }, [onGranted]);

  useEffect(() => {
    runChecks();
  }, [runChecks]);

  /* ── request flow ────────────────────────────────────────────── */
  const requestPermissions = useCallback(async () => {
    setRequesting(true);
    try {
      // Camera
      if (!camOk) {
        const camResult = await requestCameraPermissionsAsync();
        if (camResult.status === "granted") {
          setCamOk(true);
        } else if (!camResult.canAskAgain) {
          Alert.alert(
            "Camera access required",
            "AR Ruler needs camera access to measure distances. Please enable it in Settings.",
            [
              { text: "Cancel", style: "cancel" },
              { text: "Open Settings", onPress: () => Linking.openSettings() },
            ],
          );
          setRequesting(false);
          return;
        }
      }

      // Motion (iOS only — Android is auto-granted above)
      if (!motionOk && Platform.OS !== "android") {
        try {
          const motResult = await DeviceMotion.requestPermissionsAsync();
          if (motResult.status === "granted") {
            setMotionOk(true);
          } else if (!motResult.canAskAgain) {
            Alert.alert(
              "Motion access required",
              "AR Ruler needs motion sensors for spatial tracking. Please enable it in Settings.",
              [
                { text: "Cancel", style: "cancel" },
                { text: "Open Settings", onPress: () => Linking.openSettings() },
              ],
            );
            setRequesting(false);
            return;
          }
        } catch {
          // Sensor permission not supported — treat as granted
          setMotionOk(true);
        }
      }

      // Re-check final state
      const cam = await checkCamera();
      const mot = await checkMotion();
      if (cam.granted && mot.granted) {
        setCamOk(true);
        setMotionOk(true);
        setState("granted");
        onGranted();
      }
    } finally {
      setRequesting(false);
    }
  }, [camOk, motionOk, onGranted]);

  /* ── loading ─────────────────────────────────────────────────── */
  if (state === "checking") {
    return (
      <View style={[styles.root, { paddingTop: insets.top, paddingBottom: insets.bottom }]} testID="ar-gate-checking">
        <ActivityIndicator size="large" color={colors.arBlue} />
        <Text style={styles.checkingText}>Checking permissions…</Text>
      </View>
    );
  }

  /* ── granted → render placeholder (AR-2 replaces this) ───────── */
  if (state === "granted") {
    return <>{placeholder ?? null}</>;
  }

  /* ── onboarding card ─────────────────────────────────────────── */
  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={[styles.content, { paddingTop: insets.top + 24, paddingBottom: insets.bottom + 24 }]}
      testID="ar-gate-onboarding"
    >
      {/* Hero icon */}
      <View style={styles.heroCircle}>
        <Ionicons name="cube-outline" size={48} color="#fff" />
      </View>

      <Text style={styles.title}>AR Ruler</Text>
      <Text style={styles.subtitle}>
        Place virtual pins on real surfaces to measure{"\n"}distances and areas — hands-free.
      </Text>

      {/* Permission cards */}
      <View style={styles.cardsWrap}>
        <PermCard
          icon="camera-outline"
          title="Camera"
          desc="View the real world through your camera to place measurement pins."
          granted={camOk}
          testID="ar-gate-cam"
        />
        <PermCard
          icon="move-outline"
          title="Motion Sensors"
          desc="Track device orientation for accurate spatial positioning."
          granted={motionOk}
          testID="ar-gate-motion"
        />
      </View>

      {/* CTA */}
      <Pressable
        style={[styles.ctaBtn, requesting && { opacity: 0.7 }]}
        onPress={requestPermissions}
        disabled={requesting}
        testID="ar-gate-grant-btn"
      >
        {requesting ? (
          <ActivityIndicator size="small" color="#fff" />
        ) : (
          <Ionicons name="shield-checkmark-outline" size={20} color="#fff" />
        )}
        <Text style={styles.ctaText}>
          {requesting ? "Requesting…" : "Grant Permissions"}
        </Text>
      </Pressable>

      <Text style={styles.footnote}>
        You can change these later in your device Settings.
      </Text>
    </ScrollView>
  );
}

/* ── small sub-component ───────────────────────────────────────── */
function PermCard({
  icon,
  title,
  desc,
  granted,
  testID,
}: {
  icon: string;
  title: string;
  desc: string;
  granted: boolean;
  testID: string;
}) {
  return (
    <View style={[styles.permCard, granted && styles.permCardGranted]} testID={testID}>
      <View style={styles.permIconWrap}>
        <Ionicons
          name={granted ? "checkmark-circle" : (icon as any)}
          size={28}
          color={granted ? "#34D399" : colors.arBlue}
        />
      </View>
      <View style={styles.permTextWrap}>
        <Text style={styles.permTitle}>
          {title}
          {granted ? (
            <Text style={styles.permGranted}> ✓ Granted</Text>
          ) : null}
        </Text>
        <Text style={styles.permDesc}>{desc}</Text>
      </View>
    </View>
  );
}

/* ── styles ────────────────────────────────────────────────────── */
const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.arNavy,
  },
  content: {
    alignItems: "center",
    paddingHorizontal: spacing.xl,
    gap: spacing.lg,
  },
  checkingText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: "rgba(255,255,255,0.7)",
    marginTop: spacing.md,
  },
  heroCircle: {
    width: 96,
    height: 96,
    borderRadius: 48,
    backgroundColor: colors.arBlue,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.sm,
  },
  title: {
    fontFamily: font.bold,
    fontSize: 28,
    color: "#fff",
  },
  subtitle: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: "rgba(255,255,255,0.75)",
    textAlign: "center",
    lineHeight: 22,
  },
  cardsWrap: {
    width: "100%",
    gap: spacing.md,
    marginTop: spacing.sm,
  },
  permCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: "rgba(255,255,255,0.08)",
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1.5,
    borderColor: "rgba(255,255,255,0.12)",
  },
  permCardGranted: {
    borderColor: "#34D399",
    backgroundColor: "rgba(52,211,153,0.08)",
  },
  permIconWrap: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "rgba(255,255,255,0.1)",
    alignItems: "center",
    justifyContent: "center",
  },
  permTextWrap: {
    flex: 1,
  },
  permTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.lg,
    color: "#fff",
  },
  permGranted: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#34D399",
  },
  permDesc: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "rgba(255,255,255,0.6)",
    marginTop: 2,
    lineHeight: 18,
  },
  ctaBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    width: "100%",
    height: 56,
    borderRadius: radius.lg,
    backgroundColor: colors.arBlue,
    marginTop: spacing.sm,
  },
  ctaText: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: "#fff",
  },
  footnote: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "rgba(255,255,255,0.4)",
    textAlign: "center",
  },
});
