/**
 * TB-1 · MARCO voice preferences — persisted toggles for TTS and wake-word.
 *
 * Keys in AsyncStorage:
 *   marco.voiceResponseEnabled  — default ON  (TTS speaks back responses)
 *   marco.wakeWordEnabled       — default OFF (explicit opt-in to "Hey MARCO")
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

const VOICE_RESPONSE_KEY = "marco.voiceResponseEnabled";
const WAKE_WORD_KEY = "marco.wakeWordEnabled";

export async function getVoiceResponseEnabled(): Promise<boolean> {
  const val = await AsyncStorage.getItem(VOICE_RESPONSE_KEY);
  // Default ON
  return val !== "0";
}

export async function setVoiceResponseEnabled(enabled: boolean): Promise<void> {
  await AsyncStorage.setItem(VOICE_RESPONSE_KEY, enabled ? "1" : "0");
}

export async function getWakeWordEnabled(): Promise<boolean> {
  const val = await AsyncStorage.getItem(WAKE_WORD_KEY);
  // Default OFF — explicit opt-in
  return val === "1";
}

export async function setWakeWordEnabled(enabled: boolean): Promise<void> {
  await AsyncStorage.setItem(WAKE_WORD_KEY, enabled ? "1" : "0");
}
