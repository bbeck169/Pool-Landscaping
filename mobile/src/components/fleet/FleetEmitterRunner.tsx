/**
 * TD-fleet-emitter-auth-wiring · provider-scoped host for the fleet emitter.
 *
 * `useFleetEmitter()` reads `useAuth()`. It used to be called directly in
 * `RootLayout` (app/_layout.tsx), the component that RENDERS <AuthProvider>,
 * so it only ever saw the context default `{}` → `user` undefined → the
 * emitter never started (since FLEET-B cedc6d5f8). Mounting this runner
 * INSIDE <AuthProvider> (same pattern as <PushTapRouter />) fixes that.
 * Renders nothing.
 */
import { useFleetEmitter } from "@/src/hooks/useFleetEmitter";

export default function FleetEmitterRunner() {
  useFleetEmitter();
  return null;
}
