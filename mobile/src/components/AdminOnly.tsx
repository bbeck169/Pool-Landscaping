import React from "react";
import { Redirect } from "expo-router";
import { useAuth } from "@/src/auth";

/**
 * Belt-and-suspenders route guard: renders children only if the current user is admin.
 * Non-admins are redirected to their role-appropriate landing screen.
 * Used to guard admin-only screens (Landscape AI, CAD, Measure, Virtual Bid) so a
 * technician typing the URL directly can't reach them even if the nav omits the link.
 */
export function AdminOnly({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Redirect href="/login" />;
  if (user.role !== "admin") {
    return <Redirect href={user.role === "customer" ? "/portal/home" : "/(app)/jobs"} />;
  }
  return <>{children}</>;
}
