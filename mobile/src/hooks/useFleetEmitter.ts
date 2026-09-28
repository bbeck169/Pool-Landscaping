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

import { useAuth } from "@/src/auth";
import {
  startEmitter,
  stopEmitter,
  isEmitterRunning,
  isPaused,
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
}
