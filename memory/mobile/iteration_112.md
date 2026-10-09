# Iteration 112 — Phase 8M Hey Marco arm-on-click (mobile)
- Web→mobile: useWebWakeWord → useMarcoWakeWord (expo-speech-recognition via wakeWordService); beforeunload → AppState background/inactive disarm; sonner → useToast.
- Role gate changed from technician-only auto-start (pre-8M mobile) to web's MARCO_WAKE_ROLES (admin/super_admin/manager/owner). Techs no longer get wake-word.
- Arming bypasses stored wakeWordEnabled/voiceResponseEnabled prefs (click = opt-in). TTS of Marco's answer on job screens is still gated by voiceResponseEnabled.
- MicToggleButton lives in its own file (imports only context) so widgets.tsx/Header don't pull expo-audio into ~219 screens' tests; re-exported from MarcoMicController.tsx.
- Tests: marco-wake-word-arm (15) + marco-mobile-chat + marco-wake-word all green. Full suite 43 failed/51 tests = unchanged baseline.
- Verified on Expo web preview: admin header shows mic-off icon → tap → armed icon + pulse ring + "Marco wake-word armed" toast.
