/**
 * FLEET-B · useFleetEmitter hook
 *
 * Initializes the fleet location emitter when:
 * 1. User is a technician (or admin for testing)
 * 2. App is in foreground
 * 3. Not paused
 *
 * Mount this in the root layout or app shell.
 */
import { useEffect, useRef } from "react";
import { AppState } from "react-native";
import * as Location from "expo-location";

import { useAuth } from "@/src/auth";
import {
  startEmitter,
  stopEmitter,
  isEmitterRunning,
  isPaused,
  getEmitterStatus,
} from "@/src/services/fleet/locationEmitter";

export function useFleetEmitter() {
  const { user } = useAuth();
  const startedRef = useRef(false);

  useEffect(() => {
    if (!user) {
      // Not logged in — stop emitter if running
      if (startedRef.current) {
        stopEmitter();
        startedRef.current = false;
      }
      return;
    }

    const role = (user.role || "") as string;
    const isTech = role === "technician" || role === "tech";

    if (!isTech) {
      // Only techs emit
      if (startedRef.current) {
        stopEmitter();
        startedRef.current = false;
      }
      return;
    }

    // Start the emitter (it handles permission checks, pause state, etc.)
    const init = async () => {
      const paused = await isPaused();
      if (paused) return;
      if (!isEmitterRunning()) {
        await startEmitter();
        startedRef.current = true;
      }
    };

    init().catch(() => {});

    // Cleanup on unmount
    return () => {
      // Don't stop on unmount since this is root-level.
      // The emitter self-manages via AppState.
    };
  }, [user]);

  // TD-fleet-tracking-always-on (Option A) · resume after an OS permission
  // re-grant (Settings → allow → back to app) without a relaunch. Only acts
  // from `no_permission`, never re-prompts (read-only permission check), and
  // never overrides an explicit pause.
  const role = (user?.role || "") as string;
  const isTechUser = role === "technician" || role === "tech";
  useEffect(() => {
    if (!isTechUser) return;
    const sub = AppState.addEventListener("change", async (state) => {
      if (state !== "active" || isEmitterRunning() || getEmitterStatus() !== "no_permission") return;
      if (await isPaused()) return;
      const { status } = await Location.getForegroundPermissionsAsync();
      if (status === "granted") await startEmitter();
    });
    return () => sub.remove();
  }, [isTechUser]);
}
