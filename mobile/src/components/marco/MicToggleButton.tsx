/**
 * Phase 8M · <MicToggleButton> — header-slot arm/disarm control for
 * the "Hey Marco" wake-word listener (mirrors web MicToggleButton).
 *
 * Hidden entirely for non-Marco roles or when the speech primitive
 * (expo-speech-recognition) isn't available in this build.
 * Armed state = mic icon + pulsing ring.  No audio, visual only.
 */
import React, { useEffect, useRef } from "react";
import { Animated, Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useMarcoMic } from "@/src/components/marco/marcoMicContext";

const ARMED_COLOR = "#059669";
const ARMED_BG = "#ECFDF5";
const DISARMED_COLOR = "#94A3B8";

function PulseRing() {
  const anim = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.timing(anim, { toValue: 1, duration: 1200, useNativeDriver: true }),
    );
    loop.start();
    return () => loop.stop();
  }, [anim]);
  const scale = anim.interpolate({ inputRange: [0, 1], outputRange: [1, 1.6] });
  const opacity = anim.interpolate({ inputRange: [0, 1], outputRange: [0.5, 0] });
  return (
    <Animated.View
      testID="marco-mic-pulse-ring"
      pointerEvents="none"
      style={[styles.ring, { opacity, transform: [{ scale }] }]}
    />
  );
}

export function MicToggleButton() {
  const ctx = useMarcoMic();
  if (!ctx.canUseMarco || !ctx.supported) return null;
  const armed = Boolean(ctx.isArmed);
  const label = armed ? "Disarm Marco wake-word" : "Arm Marco wake-word";
  return (
    <Pressable
      onPress={ctx.toggle}
      hitSlop={8}
      testID="marco-mic-toggle-btn"
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ selected: armed }}
      style={({ pressed }) => [styles.btn, armed && styles.btnArmed, pressed && { opacity: 0.7 }]}
    >
      {armed ? <PulseRing /> : null}
      <View testID={armed ? "marco-mic-icon-armed" : "marco-mic-icon-disarmed"}>
        <Ionicons
          name={armed ? "mic" : "mic-off-outline"}
          size={20}
          color={armed ? ARMED_COLOR : DISARMED_COLOR}
        />
      </View>
    </Pressable>
  );
}

export default MicToggleButton;

const styles = StyleSheet.create({
  btn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
  },
  btnArmed: { backgroundColor: ARMED_BG },
  ring: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: 18,
    backgroundColor: "#34D399",
  },
});
