import { Tabs, Redirect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { Platform, View } from "react-native";

import { useAuth } from "@/src/auth";
import { colors, font } from "@/src/theme";
import { SyncBanner } from "@/src/components/SyncBanner";

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
          title: "Today",
          href: isTech ? "/(app)/today" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="today-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="new-lead"
        options={{
          title: "New Lead",
          href: isTech ? "/(app)/new-lead" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="magnet-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="jobs"
        options={{
          title: "Jobs",
          href: isTech ? "/(app)/jobs" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="briefcase-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="schedule"
        options={{
          title: "Schedule",
          href: isAdmin ? "/(app)/schedule" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="calendar-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="tools"
        options={{
          title: "Tools",
          href: isTech ? "/(app)/tools" : null,
          tabBarIcon: ({ color, size }) => <Ionicons name="calculator-outline" size={size} color={color} />,
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
    </View>
  );
}
