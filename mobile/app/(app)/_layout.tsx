import { Tabs, Redirect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { Platform, View } from "react-native";

import { useAuth } from "@/src/auth";
import { colors, font } from "@/src/theme";
import { SyncBanner } from "@/src/components/SyncBanner";
import { GlobalMenu } from "@/src/components/tools/GlobalMenu";

export default function AppLayout() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Redirect href="/login" />;

  const isAdmin = user.role === "admin";
  const isTech = user.role === "technician";
  const isCustomer = user.role === "customer";

  // Customers use a dedicated portal (single dashboard with section cards), not the staff tab bar.
  if (isCustomer) return <Redirect href="/portal/home" />;

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <SyncBanner />
      <View style={{ flex: 1 }}>
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.brand,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          height: Platform.OS === "ios" ? 88 : 64,
          paddingTop: 6,
          paddingBottom: Platform.OS === "ios" ? 28 : 8,
        },
        tabBarLabelStyle: { fontFamily: font.medium, fontSize: 11 },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Dashboard",
          href: isAdmin ? "/(app)" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="grid-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="today"
        options={{
          title: "Schedule",
          // Phase 30: tech Schedule tab now points at the unified calendar
          // instead of the old day-list `today` screen. The file still
          // exists on disk (used as a fallback route inside the calendar
          // module) but is off the tab bar.
          href: null,
          tabBarIcon: ({ color, size }) => <Ionicons name="today-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="new-lead"
        options={{
          title: "New Lead",
          href: null,
          tabBarIcon: ({ color, size }) => <Ionicons name="magnet-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="jobs"
        options={{
          title: "Workstream",
          // Phase 47 follow-up — surface the JobCard workstream list on the
          // tech + customer tab bar. Admins keep the calendar-first flow via
          // the schedule/calendar tab and are redirected server-side.
          href: (isTech || isCustomer) ? "/(app)/jobs" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="briefcase-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="schedule/index"
        options={{
          title: "Schedule",
          href: null,
          tabBarIcon: ({ color, size }) => <Ionicons name="calendar-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="schedule/calendar"
        options={{
          title: "Schedule",
          // Phase 30 · unified calendar for both admins AND techs.
          href: (isAdmin || isTech) ? "/(app)/schedule/calendar" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="calendar-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="d2d"
        options={{
          title: "D2D",
          href: isTech ? "/(app)/d2d" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="log-in-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="time-clock"
        options={{
          title: "Time Clock",
          href: isTech ? "/(app)/time-clock" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="time-outline" size={size} color={color} />,
        }}
      />
      {/* "All My Tools" hub — the new home for every tech-accessible page.
          Huddle and Equipment moved off the tab bar and now live inside the hub. */}
      <Tabs.Screen
        name="tools"
        options={{
          title: "Tools",
          href: isTech ? "/(app)/tools" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="apps-outline" size={size} color={color} />,
        }}
      />
      {/* Standalone pool-chemistry calculators — reachable from the Tools hub. */}
      <Tabs.Screen
        name="calculators"
        options={{
          title: "Calculators",
          href: null,
          tabBarIcon: ({ color, size }) => <Ionicons name="calculator-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="huddle"
        options={{
          title: "Huddle",
          href: null,
          tabBarIcon: ({ color, size }) => <Ionicons name="chatbubbles-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="assets"
        options={{
          title: "Equipment",
          href: null,
          tabBarIcon: ({ color, size }) => <Ionicons name="construct-outline" size={size} color={color} />,
        }}
      />
      {/* Phase 29A · Mobile Wave A parity — admin-only, hidden from tab bar. */}
      <Tabs.Screen
        name="dispatch/board"
        options={{
          title: "Dispatch",
          href: null,
          tabBarIcon: ({ color, size }) => <Ionicons name="git-network-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="dispatch/weather"
        options={{
          title: "Weather",
          href: null,
          tabBarIcon: ({ color, size }) => <Ionicons name="cloud-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="payroll/batch"
        options={{
          title: "Payroll",
          href: null,
          tabBarIcon: ({ color, size }) => <Ionicons name="cash-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="onboarding"
        options={{
          title: "Onboarding",
          href: null,
          tabBarIcon: ({ color, size }) => <Ionicons name="clipboard-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="quotes"
        options={{
          title: isCustomer ? "Invoices" : "Quotes",
          href: isAdmin || isCustomer ? "/(app)/quotes" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="document-text-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="customers"
        options={{
          title: "Customers",
          href: isAdmin ? "/(app)/customers" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="people-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="more"
        options={{
          title: isAdmin ? "More" : "Profile",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name={isAdmin ? "ellipsis-horizontal-circle-outline" : "person-outline"} size={size} color={color} />
          ),
        }}
      />
    </Tabs>
      </View>
      {/* Phase 43 · Global dropdown menu — trigger renders absolute-
          positioned so no per-screen header changes are needed. Sheet
          reuses the Phase 42 body via `<ToolsMenuBody variant="sheet" />`. */}
      <GlobalMenu />
    </View>
  );
}
