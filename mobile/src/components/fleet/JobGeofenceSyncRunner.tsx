/**
 * β-core 2 · hosts the P37c arrival-geofence sync inside <AuthProvider>
 * (sibling of <FleetEmitterRunner />). Renders nothing.
 */
import { useAuth } from "@/src/auth";
import { useJobGeofenceSync } from "@/src/hooks/useJobGeofenceSync";

export default function JobGeofenceSyncRunner() {
  const { user } = useAuth();
  useJobGeofenceSync(user as any);
  return null;
}
