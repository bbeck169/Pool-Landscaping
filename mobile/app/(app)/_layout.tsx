import React, { useState, useEffect, useMemo } from "react";
import { Tabs, Redirect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { View, TouchableOpacity, StyleSheet, Platform } from "react-native";
import { SafeAreaInsetsContext, useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth";
import { colors, font } from "@/src/theme";
import { SyncBanner } from "@/src/components/SyncBanner";
import { GlobalMenu } from "@/src/components/tools/GlobalMenu";
import AIDockDrawer from "@/src/components/ai/AIDockDrawer";
import { aiDockEvents } from "@/src/events/aiDockEvents";
import { registerForPushNotifications } from "@/src/services/pushNotifications";
import { useUnreadCount } from "@/src/hooks/useUnreadCount";
// FLEET-B · Fleet status chip in the tab bar area.
import FleetStatusChip from "@/src/components/fleet/FleetStatusChip";
import FleetPermissionBanner from "@/src/components/fleet/FleetPermissionBanner";
// Landscape-tech clock-in gate — parity with web f5dd1eb0a.
import LandscapeTechClockInGate from "@/src/components/LandscapeTechClockInGate";

export default function AppLayout() {
  const { user, loading } = useAuth();
  const [dockOpen, setDockOpen] = useState(false);
  // MARCO-AI-CHAT Phase B — wake-word → dock-open bridge
  useEffect(() => {
    return aiDockEvents.onOpen(() => setDockOpen(true));
  }, []);

  // G2 · Unread messages badge on the Messages tab.
  // Enabled for admin + tech (same roles that see the tab).
  const unreadBadge = useUnreadCount(!!user && user.role !== "customer");

  // Register push notifications after successful auth
  useEffect(() => {
    if (user) {
      registerForPushNotifications().catch(() => {});
    }
  }, [user]);

  // Fleet chip tap-target fix (Option A) — when the fleet chip row renders
  // it sits at the very top of the shell, so the shell owns the top
  // safe-area inset ONCE (wrapper below) and hands top:0 to SyncBanner and
  // every tab screen (Header / useSafeAreaInsets consumers) so the gap is
  // not double-applied. GlobalMenu + AI dock stay outside → real insets.
  const insets = useSafeAreaInsets();
  const childInsets = useMemo(() => ({ ...insets, top: 0 }), [insets]);

  if (loading) return null;
  if (!user) return <Redirect href="/login" />;

  const isAdmin = user.role === "admin" || (user.role as string) === "super_admin";
  // MARCO-AI-CHAT Phase B — manager/owner also access AI dock (matches web role widening)
  const canAccessAIDock = ["admin", "super_admin", "manager", "owner"].includes(user.role || "");
  const isTech = user.role === "technician";
  const isCustomer = user.role === "customer";

  // Customers use a dedicated portal (single dashboard with section cards), not the staff tab bar.
  if (isCustomer) return <Redirect href="/portal/home" />;

  const showFleetRow = isTech || isAdmin;

  return (
    <LandscapeTechClockInGate>
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <SafeAreaInsetsContext.Provider value={showFleetRow ? childInsets : insets}>
      <View style={showFleetRow ? { paddingTop: insets.top } : null} testID="app-shell-top-inset">
        <SyncBanner />
        {/* FLEET-B · Fleet status chip — shows fleet tracking state for techs.
            Chip gap = insets.top (wrapper) + 4 → below the Android
            edge-to-edge status bar instead of under it. */}
        {showFleetRow && (
          <View style={{ flexDirection: "row", justifyContent: "flex-end", paddingHorizontal: 12, paddingTop: 4 }} testID="fleet-chip-row">
            <FleetStatusChip />
          </View>
        )}
        {showFleetRow && <FleetPermissionBanner />}
      </View>
      <View style={{ flex: 1 }}>
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.brand,
        tabBarInactiveTintColor: colors.muted,
        tabBarHideOnKeyboard: true,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopWidth: 1,
          borderTopColor: colors.border,
          elevation: 8,
          shadowColor: "#000",
          shadowOffset: { width: 0, height: -2 },
          shadowOpacity: 0.06,
          shadowRadius: 4,
        },
        tabBarLabelStyle: { fontFamily: font.medium, fontSize: 11 },
      }}
    >
      {/* ═══════════════════════════════════════════════════════════
          E3 · 5 VISIBLE TABS — order here determines tab bar order
          ═══════════════════════════════════════════════════════════ */}

      {/* Tab 1 · Schedule */}
      <Tabs.Screen
        name="schedule/calendar"
        options={{
          title: "Schedule",
          href: (isAdmin || isTech) ? "/(app)/schedule/calendar" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="calendar-outline" size={size} color={color} />,
          tabBarTestID: "tab-schedule",
        }}
      />

      {/* Tab 2 · Customers */}
      <Tabs.Screen
        name="customers"
        options={{
          title: "Customers",
          href: (isAdmin || isTech) ? "/(app)/customers" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="people-outline" size={size} color={color} />,
          tabBarTestID: "tab-customers",
        }}
      />

      {/* Tab 3 · Messages (center position) */}
      <Tabs.Screen
        name="huddle"
        options={{
          title: "Messages",
          href: (isAdmin || isTech) ? "/(app)/huddle" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="chatbubbles-outline" size={size} color={color} />,
          tabBarTestID: "tab-messages",
          tabBarBadge: unreadBadge,
          tabBarBadgeStyle: unreadBadge != null ? { backgroundColor: colors.error, fontFamily: font.semibold, fontSize: 10 } : undefined,
        }}
      />

      {/* Tab 4a · Jobs (tech-only) — role-gated slot 4 */}
      <Tabs.Screen
        name="jobs"
        options={{
          title: "Jobs",
          href: isTech ? "/(app)/jobs" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="briefcase-outline" size={size} color={color} />,
          tabBarTestID: "tab-jobs",
        }}
      />

      {/* Tab 4b · Pipeline (admin-only) — role-gated slot 4 */}
      <Tabs.Screen
        name="quotes"
        options={{
          title: "Pipeline",
          href: isAdmin ? "/(app)/quotes" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="git-branch-outline" size={size} color={color} />,
          tabBarTestID: "tab-pipeline",
        }}
      />

      {/* Tab 5 · More / Profile */}
      <Tabs.Screen
        name="more"
        options={{
          title: isAdmin ? "More" : "Profile",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name={isAdmin ? "ellipsis-horizontal-circle-outline" : "person-outline"} size={size} color={color} />
          ),
          tabBarTestID: "tab-more",
        }}
      />

      {/* ═══════════════════════════════════════════════════════════
          HIDDEN TABS — accessible via GlobalMenu / router.push
          ═══════════════════════════════════════════════════════════ */}

      <Tabs.Screen name="index" options={{ title: "Dashboard", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="grid-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="today" options={{ title: "Today", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="today-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="new-lead" options={{ title: "New Lead", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="magnet-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="schedule/index" options={{ title: "Schedule Index", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="calendar-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="schedule/JobTrackerTiles" options={{ title: "Job Tracker", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="stats-chart-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="d2d" options={{ title: "D2D", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="log-in-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="time-clock" options={{ title: "Time Clock", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="time-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="landscape-time-clock" options={{ title: "Landscape Clock", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="time-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="tools" options={{ title: "Tools", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="apps-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="calculators" options={{ title: "Calculators", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="calculator-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="assets/index" options={{ title: "Equipment", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="construct-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="assets/[id]" options={{ title: "Equipment Detail", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="construct-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="before-after" options={{ title: "Before/After", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="images-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="profile" options={{ title: "Profile", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="person-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="property-lookup" options={{ title: "Property Lookup", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="home-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="chat" options={{ title: "Chat", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="chatbubble-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="instaquote" options={{ title: "InstaQuote", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="flash-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="instaschedule" options={{ title: "InstaSchedule", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="flash-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="directories" options={{ title: "Directories", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="book-outline" size={size} color={color} /> }} />

      {/* Dispatch */}
      <Tabs.Screen name="dispatch/board" options={{ title: "Dispatch", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="git-network-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="dispatch/weather" options={{ title: "Weather", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="cloud-outline" size={size} color={color} /> }} />

      {/* Payroll */}
      <Tabs.Screen name="payroll/batch" options={{ title: "Payroll", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="cash-outline" size={size} color={color} /> }} />

      {/* CFO */}
      <Tabs.Screen name="cfo/index" options={{ title: "CFO", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="bar-chart-outline" size={size} color={color} /> }} />

      {/* Checks */}
      <Tabs.Screen name="checks/register" options={{ title: "Check Register", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="document-text-outline" size={size} color={color} /> }} />

      {/* Dunning */}
      <Tabs.Screen name="dunning/queue" options={{ title: "Dunning Queue", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="mail-open-outline" size={size} color={color} /> }} />

      {/* Onboarding */}
      <Tabs.Screen name="onboarding/mine" options={{ title: "My Onboarding", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="clipboard-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="onboarding-checklist/index" options={{ title: "Onboarding Checklist", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="checkbox-outline" size={size} color={color} /> }} />

      {/* Inventory */}
      <Tabs.Screen name="inventory/index" options={{ title: "Inventory", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="layers-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="inventory/my-inventory" options={{ title: "My Inventory", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="layers-outline" size={size} color={color} /> }} />

      {/* Handbook */}
      <Tabs.Screen name="handbook/index" options={{ title: "Handbook", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="book-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="handbook/[code]" options={{ title: "Handbook Entry", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="book-outline" size={size} color={color} /> }} />

      {/* Service Reports */}
      <Tabs.Screen name="service-report/[id]" options={{ title: "Service Report", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="document-text-outline" size={size} color={color} /> }} />

      {/* Tests */}
      <Tabs.Screen name="tests/index" options={{ title: "Tests", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="school-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="tests/[code]" options={{ title: "Test", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="school-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="tests/[code]/quiz" options={{ title: "Quiz", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="school-outline" size={size} color={color} /> }} />

      {/* Comms */}
      <Tabs.Screen name="comms/index" options={{ title: "Comms", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="mail-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="comms/templates/index" options={{ title: "Comms Templates", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="mail-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="comms/templates/[code]" options={{ title: "Template Detail", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="mail-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="comms/automations/index" options={{ title: "Automations", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="flash-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="comms/automations/[code]" options={{ title: "Automation Detail", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="flash-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="comms/sends/index" options={{ title: "Sends", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="paper-plane-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="comms/sends/[id]" options={{ title: "Send Detail", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="paper-plane-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="comms/test-send" options={{ title: "Test Send", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="rocket-outline" size={size} color={color} /> }} />

      {/* Reviews */}
      <Tabs.Screen name="reviews/index" options={{ title: "Reviews", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="star-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="reviews/requests/index" options={{ title: "Requests", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="send-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="reviews/requests/[id]" options={{ title: "Request Detail", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="send-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="reviews/recent" options={{ title: "Recent Reviews", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="chatbubbles-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="reviews/leaderboard" options={{ title: "Leaderboard", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="trophy-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="reviews/platforms" options={{ title: "Platforms", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="globe-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="reviews/widget" options={{ title: "Widget", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="code-slash-outline" size={size} color={color} /> }} />

      {/* AI & Estimator */}
      <Tabs.Screen name="credits/index" options={{ title: "AI Credits", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="sparkles-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="ai-estimator" options={{ title: "AI Estimator", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="bulb-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="estimator/index" options={{ title: "Estimator", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="document-text-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="estimator/[id]" options={{ title: "Estimate", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="document-text-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="estimator/new" options={{ title: "New Estimate", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="add-outline" size={size} color={color} /> }} />

      {/* Deals */}
      <Tabs.Screen name="deals/index" options={{ title: "Deals", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="git-branch-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="deals/new" options={{ title: "New Deal", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="add-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="deals/[id]" options={{ title: "Deal", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="git-branch-outline" size={size} color={color} /> }} />

      {/* Soshie Moderation */}
      <Tabs.Screen name="soshie-moderation" options={{ title: "Soshie Moderation", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="shield-outline" size={size} color={color} /> }} />

      {/* Templates Library */}
      <Tabs.Screen name="templates/index" options={{ title: "Templates", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="library-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="templates/[id]" options={{ title: "Template Fill", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="document-text-outline" size={size} color={color} /> }} />

      {/* Settings */}
      <Tabs.Screen name="settings/auto-clockin" options={{ title: "Auto Clock-In", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="location-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="settings/lidar" options={{ title: "LiDAR", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="cube-outline" size={size} color={color} /> }} />
      <Tabs.Screen name="settings/offline-diagnostics" options={{ title: "Offline Diagnostics", href: null, tabBarIcon: ({ color, size }) => <Ionicons name="analytics-outline" size={size} color={color} /> }} />
    </Tabs>
      </View>
      </SafeAreaInsetsContext.Provider>
      {/* Phase 43 · Global dropdown menu — trigger renders absolute-
          positioned so no per-screen header changes are needed. Sheet
          reuses the Phase 42 body via `<ToolsMenuBody variant="sheet" />`. */}
      <GlobalMenu />
      {/* B1 · AI Dock FAB — admin/super_admin/manager/owner.
          MARCO-AI-CHAT Phase B — role widened to manager/owner. */}
      {canAccessAIDock && (
        <TouchableOpacity
          testID="ai-dock-fab"
          style={fabStyles.fab}
          onPress={() => setDockOpen(true)}
          activeOpacity={0.8}
        >
          <Ionicons name="sparkles" size={20} color="#fff" />
        </TouchableOpacity>
      )}
      {canAccessAIDock && <AIDockDrawer visible={dockOpen} onClose={() => setDockOpen(false)} />}
    </View>
    </LandscapeTechClockInGate>
  );
}

const TAB_BAR_HEIGHT = Platform.OS === "ios" ? 88 : 64;

const fabStyles = StyleSheet.create({
  fab: {
    position: "absolute",
    bottom: TAB_BAR_HEIGHT + 16,
    right: 20,
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.brand,
    alignItems: "center",
    justifyContent: "center",
    elevation: 6,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
    zIndex: 40,
  },
});
