// Feb-2026 · P37c — Mobile GPS consent modal (soft-block).
//
// Shown on entry to any job screen when GET /tech-gps-consent/me
// returns ``active=false``. Tech may grant → POST /tech-gps-consent
// {granted:true, method:"mobile_onboarding_modal"} → dismiss. Or
// tap "Not right now" → dismiss WITHOUT POSTing; modal reappears
// next session until granted.
//
// Never hard-blocks the underlying screen — a declined tech keeps
// using the app, dispatcher can start timers manually.
import React, { useCallback, useEffect, useState } from "react";
import {
  Modal, View, Text, Pressable, StyleSheet,
} from "react-native";

import { api } from "@/src/api";
import { offlineWrite } from "@/src/services/offlineWrite";
import { invalidateConsentCache } from "@/src/background/jobGeofence";


export type GpsConsentModalProps = {
  onDismiss?: (granted: boolean) => void;
  autoOpen?: boolean;  // for tests / manual show
};


export default function GpsConsentModal({ onDismiss, autoOpen }: GpsConsentModalProps) {
  const [visible, setVisible] = useState<boolean>(!!autoOpen);
  const [busy, setBusy] = useState(false);

  const checkAndOpen = useCallback(async () => {
    try {
      const res: any = await api.get("/tech-gps-consent/me");
      if (!res?.active) setVisible(true);
    } catch { /* silent — network hiccup, don't spam modal */ }
  }, []);

  useEffect(() => {
    if (!autoOpen) checkAndOpen();
  }, [autoOpen, checkAndOpen]);

  const grant = useCallback(async () => {
    setBusy(true);
    try {
      const payload = { granted: true, method: "mobile_onboarding_modal" };
      await offlineWrite({
        op_type: "gps_consent",
        entity_id: "self",
        endpoint: "/tech-gps-consent",
        method: "POST",
        payload,
        onlineFn: () => api.post("/tech-gps-consent", payload),
      });
      invalidateConsentCache();
      setVisible(false);
      onDismiss?.(true);
    } catch { /* silent — keep modal open so tech can retry */ }
    finally { setBusy(false); }
  }, [onDismiss]);

  const decline = useCallback(() => {
    setVisible(false);
    onDismiss?.(false);
  }, [onDismiss]);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={decline}
    >
      <View style={styles.backdrop}>
        <View style={styles.card} testID="gps-consent-modal">
          <Text style={styles.title}>Location tracking for auto-start</Text>
          <Text style={styles.body}>
            To auto-start your job timer when you arrive at a customer's
            site, we track your location while you're clocked in and
            assigned to jobs. Location data is used only to trigger
            timer starts and is stored in your job's audit log.
          </Text>
          <Text style={styles.body}>
            You can revoke this any time from{" "}
            <Text style={styles.bold}>Settings → Location tracking</Text>.
            Declining is safe — your dispatcher can still start timers
            manually.
          </Text>
          <View style={styles.actions}>
            <Pressable
              onPress={decline}
              disabled={busy}
              testID="gps-consent-decline"
              style={[styles.btn, styles.btnGhost]}
            >
              <Text style={styles.btnGhostText}>Not right now</Text>
            </Pressable>
            <Pressable
              onPress={grant}
              disabled={busy}
              testID="gps-consent-grant"
              style={[styles.btn, styles.btnPrimary,
                        { opacity: busy ? 0.6 : 1 }]}
            >
              <Text style={styles.btnPrimaryText}>
                {busy ? "Saving…" : "Grant location tracking"}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}


const styles = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center", justifyContent: "center", padding: 24,
  },
  card: {
    backgroundColor: "#fff", borderRadius: 12, padding: 20,
    maxWidth: 460, width: "100%",
  },
  title: {
    fontSize: 18, fontWeight: "700", color: "#0F172A", marginBottom: 10,
  },
  body: {
    fontSize: 14, color: "#334155", marginBottom: 12, lineHeight: 20,
  },
  bold: { fontWeight: "600", color: "#0F172A" },
  actions: {
    flexDirection: "row", justifyContent: "flex-end",
    gap: 8, marginTop: 8,
  },
  btn: {
    paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8,
  },
  btnGhost: { borderWidth: 1, borderColor: "#E5E7EB" },
  btnGhostText: { color: "#334155", fontWeight: "600", fontSize: 14 },
  btnPrimary: { backgroundColor: "#0EA5E9" },
  btnPrimaryText: { color: "#fff", fontWeight: "700", fontSize: 14 },
});
