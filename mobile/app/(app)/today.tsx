/**
 * Phase 30 fix pass — legacy `/today` alias.
 *
 * Old tech landing route. Redirects to the unified Schedule so bookmarks,
 * push-notification links, and Tools Hub tiles that still point at `/today`
 * don't 404.
 */
import { Redirect } from "expo-router";

export default function TodayLegacy() {
  return <Redirect href="/(app)/schedule/calendar" />;
}
