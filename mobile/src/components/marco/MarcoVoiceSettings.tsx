/**
 * TB-1 · MARCO Voice Settings — toggles for TTS and wake-word.
 *
 * Displayed in the Profile/More screen for techs and admins.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Switch } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import {
  getVoiceResponseEnabled,
  setVoiceResponseEnabled,
  getWakeWordEnabled,
  setWakeWordEnabled,
} from "@/src/services/marco/voicePreferences";
import { font, fontSize, spacing, radius, colors } from "@/src/theme";

/* Check if expo-speech-recognition is available (dev-client only) */
let _speechRecognitionAvailable = false;
try {
  require("expo-speech-recognition");
  _speechRecognitionAvailable = true;
} catch {
  _speechRecognitionAvailable = false;
}

export default function MarcoVoiceSettings() {
  const [ttsOn, setTtsOn] = useState(true);
  const [wakeOn, setWakeOn] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getVoiceResponseEnabled(), getWakeWordEnabled()]).then(
      ([tts, wake]) => {
        setTtsOn(tts);
        setWakeOn(wake);
        setLoading(false);
      },
    );
  }, []);

  const toggleTTS = async (val: boolean) => {
    setTtsOn(val);
    await setVoiceResponseEnabled(val);
    // If TTS off, also disable wake-word (wake needs TTS to be useful)
    if (!val && wakeOn) {
      setWakeOn(false);
      await setWakeWordEnabled(false);
    }
  };

  const toggleWake = async (val: boolean) => {
    setWakeOn(val);
    await setWakeWordEnabled(val);
  };

  if (loading) return null;

  const wakeDisabled = !ttsOn || !_speechRecognitionAvailable;

  return (
    <View style={s.container} testID="marco-voice-settings">
      {/* TTS toggle */}
      <View style={s.row} testID="marco-voice-tts-row">
        <View style={s.iconWrap}>
          <Ionicons name="volume-high-outline" size={18} color={colors.brand} />
        </View>
        <View style={s.textWrap}>
          <Text style={s.title}>Voice Responses</Text>
          <Text style={s.subtitle}>
            {ttsOn ? "MARCO speaks results aloud" : "Text-only responses"}
          </Text>
        </View>
        <Switch
          testID="marco-voice-tts-toggle"
          value={ttsOn}
          onValueChange={toggleTTS}
          trackColor={{ false: colors.surfaceTertiary, true: "#86EFAC" }}
          thumbColor={ttsOn ? "#16A34A" : "#A1A1AA"}
        />
      </View>

      {/* Wake-word toggle */}
      <View
        style={[s.row, { marginTop: spacing.sm, opacity: wakeDisabled ? 0.5 : 1 }]}
        testID="marco-voice-wake-row"
      >
        <View style={s.iconWrap}>
          <Ionicons name="ear-outline" size={18} color={colors.brand} />
        </View>
        <View style={s.textWrap}>
          <Text style={s.title}>
            {'"Hey MARCO" Wake Word'}
          </Text>
          <Text style={s.subtitle}>
            {!_speechRecognitionAvailable
              ? "Unavailable — requires dev-client build"
              : !ttsOn
              ? "Enable voice responses first"
              : wakeOn
              ? 'Listening for "Hey MARCO" (foreground only)'
              : "Off — tap to enable hands-free activation"}
          </Text>
        </View>
        <Switch
          testID="marco-voice-wake-toggle"
          value={wakeOn}
          onValueChange={toggleWake}
          disabled={wakeDisabled}
          trackColor={{ false: colors.surfaceTertiary, true: "#93C5FD" }}
          thumbColor={wakeOn ? "#2563EB" : "#A1A1AA"}
        />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  container: {
    gap: 0,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
  },
  iconWrap: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  textWrap: {
    flex: 1,
  },
  title: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  subtitle: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 1,
  },
});
