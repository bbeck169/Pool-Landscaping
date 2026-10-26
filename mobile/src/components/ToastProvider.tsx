/**
 * ToastProvider — lightweight cross-platform toast overlay.
 *
 * Usage:
 *   1. Wrap your app root in <ToastProvider>
 *   2. In any screen: const { showToast } = useToast();
 *      showToast("Quote duplicated as draft #abc");
 *      showToast("Error occurred", "error");
 *
 * Variants: "success" (default), "error", "info"
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
} from "react";
import {
  Animated,
  StyleSheet,
  Text,
  View,
  Platform,
  Pressable,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { font, fontSize, radius, spacing } from "@/src/theme";

export type ToastVariant = "success" | "error" | "info";
/** M3b · optional inline action (e.g. "Undo"). Additive — existing callers unchanged. */
export type ToastAction = { label: string; onPress: () => void };

type ToastContextValue = {
  showToast: (message: string, variant?: ToastVariant, durationMs?: number, action?: ToastAction) => void;
};

const ToastContext = createContext<ToastContextValue>({
  showToast: () => {},
});

export const useToast = () => useContext(ToastContext);

const VARIANT_CONFIG: Record<ToastVariant, { bg: string; icon: string; iconColor: string }> = {
  success: { bg: "#065F46", icon: "checkmark-circle", iconColor: "#6EE7B7" },
  error:   { bg: "#991B1B", icon: "alert-circle", iconColor: "#FCA5A5" },
  info:    { bg: "#1E3A5F", icon: "information-circle", iconColor: "#93C5FD" },
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const insets = useSafeAreaInsets();
  const [message, setMessage] = useState("");
  const [variant, setVariant] = useState<ToastVariant>("success");
  const [action, setAction] = useState<ToastAction | null>(null);
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(-20)).current;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback(
    (msg: string, v: ToastVariant = "success", durationMs = 3000, act?: ToastAction) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      setMessage(msg);
      setVariant(v);
      setAction(act || null);

      // Reset + animate in
      opacity.setValue(0);
      translateY.setValue(-20);
      Animated.parallel([
        Animated.timing(opacity, { toValue: 1, duration: 250, useNativeDriver: true }),
        Animated.timing(translateY, { toValue: 0, duration: 250, useNativeDriver: true }),
      ]).start();

      timerRef.current = setTimeout(() => {
        Animated.parallel([
          Animated.timing(opacity, { toValue: 0, duration: 300, useNativeDriver: true }),
          Animated.timing(translateY, { toValue: -20, duration: 300, useNativeDriver: true }),
        ]).start(() => { setMessage(""); setAction(null); });
      }, durationMs);
    },
    [opacity, translateY],
  );

  const cfg = VARIANT_CONFIG[variant];

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {message ? (
        <Animated.View
          pointerEvents={action ? "box-none" : "none"}
          style={[
            s.container,
            { top: insets.top + (Platform.OS === "ios" ? 8 : 16), opacity, transform: [{ translateY }] },
          ]}
          testID="toast-container"
        >
          <View style={[s.toast, { backgroundColor: cfg.bg }]} testID="toast-message">
            <Ionicons name={cfg.icon as any} size={20} color={cfg.iconColor} />
            <Text style={s.text} testID="toast-text">{message}</Text>
            {action ? (
              <Pressable
                onPress={() => {
                  if (timerRef.current) clearTimeout(timerRef.current);
                  const run = action.onPress;
                  setMessage(""); setAction(null);
                  run();
                }}
                hitSlop={8}
                style={s.action}
                accessibilityRole="button"
                testID="toast-action"
              >
                <Text style={s.actionText}>{action.label}</Text>
              </Pressable>
            ) : null}
          </View>
        </Animated.View>
      ) : null}
    </ToastContext.Provider>
  );
}

const s = StyleSheet.create({
  container: {
    position: "absolute",
    left: spacing.lg,
    right: spacing.lg,
    zIndex: 9999,
    alignItems: "center",
  },
  toast: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: radius.md,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.25,
    shadowRadius: 8,
    elevation: 6,
    maxWidth: 420,
    width: "100%",
  },
  text: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#fff",
    flex: 1,
  },
  action: { minHeight: 32, paddingHorizontal: 10, justifyContent: "center", borderRadius: radius.sm, backgroundColor: "rgba(255,255,255,0.18)" },
  actionText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});
