/**
 * Phase 56.9b Step 7 — Route guard for Zillow-backed mobile screens.
 * Mirrors backend `require_zillow_access`: admin, super_admin, technician allowed.
 * Customers + anonymous get redirected home. Replaces AdminOnly on
 * Virtual Bid so techs can now access it too.
 */
import React from "react";
import { Redirect } from "expo-router";
import { useAuth } from "@/src/auth";

export function ZillowAccess({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Redirect href="/login" />;
  if (!["admin", "super_admin", "technician"].includes(user.role)) {
    return <Redirect href={user.role === "customer" ? "/portal/home" : "/(app)/jobs"} />;
  }
  return <>{children}</>;
}

export default ZillowAccess;
