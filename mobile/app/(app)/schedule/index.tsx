/**
 * Phase 30 fix pass — bare-URL landing.
 *
 * A tap on the `/schedule` deep-link used to render "Unmatched Route" because
 * the folder only contained `calendar.tsx`. Expo Router treats `index.tsx` as
 * the folder's default page; redirecting here keeps every existing shortcut
 * working.
 */
import { Redirect } from "expo-router";

export default function ScheduleIndex() {
  return <Redirect href="/(app)/schedule/calendar" />;
}
