export const colors = {
  surface: "#FFFFFF",
  onSurface: "#09090B",
  surfaceSecondary: "#F4F4F5",
  onSurfaceSecondary: "#52525B",
  surfaceTertiary: "#E4E4E7",
  surfaceInverse: "#18181B",
  onSurfaceInverse: "#FFFFFF",
  brand: "#0284C7",
  brandPrimary: "#0284C7",
  onBrandPrimary: "#FFFFFF",
  brandSecondary: "#16A34A",
  brandTertiary: "#E0F2FE",
  onBrandTertiary: "#0369A1",
  success: "#16A34A",
  onSuccess: "#FFFFFF",
  warning: "#CA8A04",
  onWarning: "#FFFFFF",
  error: "#DC2626",
  onError: "#FFFFFF",
  info: "#0284C7",
  border: "#E4E4E7",
  borderStrong: "#D4D4D8",
  divider: "#E4E4E7",
  muted: "#71717A",
};

// Web app signature primary gradient: sky-600 -> green-600
export const brandGradient = ["#0284C7", "#16A34A"] as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48 };
export const radius = { sm: 8, md: 12, lg: 16, pill: 999 };

export const font = {
  regular: "PlusJakarta-Regular",
  medium: "PlusJakarta-Medium",
  semibold: "PlusJakarta-SemiBold",
  bold: "PlusJakarta-Bold",
};

export const fontSize = { sm: 12, base: 14, lg: 16, xl: 20, "2xl": 24, "3xl": 30 };

export type JobStatus = "pending" | "active" | "completed" | "cancelled";

export const statusMeta: Record<string, { label: string; bg: string; fg: string }> = {
  requested: { label: "Requested", bg: "#FFEDD5", fg: "#C2410C" },
  pending: { label: "Pending", bg: "#FEF9C3", fg: "#A16207" },
  active: { label: "Active", bg: colors.brandTertiary, fg: colors.onBrandTertiary },
  completed: { label: "Completed", bg: "#DCFCE7", fg: colors.success },
  cancelled: { label: "Cancelled", bg: "#FEE2E2", fg: colors.error },
  draft: { label: "Draft", bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary },
  published: { label: "Published", bg: "#DCFCE7", fg: colors.success },
  scheduled: { label: "Scheduled", bg: "#E0E7FF", fg: "#4338CA" },
  sent: { label: "Sent", bg: colors.brandTertiary, fg: colors.onBrandTertiary },
  accepted: { label: "Accepted", bg: "#DCFCE7", fg: colors.success },
  rejected: { label: "Rejected", bg: "#FEE2E2", fg: colors.error },
  paid: { label: "Paid", bg: "#DCFCE7", fg: colors.success },
  unpaid: { label: "Unpaid", bg: "#FEF9C3", fg: "#A16207" },
};

export const IMAGES = {
  loginHero:
    "https://images.unsplash.com/photo-1587870306141-4f19861e6c73?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000",
  dashboardHero:
    "https://images.pexels.com/photos/8974468/pexels-photo-8974468.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
  jobPlaceholder:
    "https://images.unsplash.com/photo-1777106322601-578dc9213ace?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NTY2NzZ8MHwxfHNlYXJjaHwxfHxzdWJ1cmJhbiUyMG1vZGVybiUyMGhvdXNlJTIwZXh0ZXJpb3J8ZW58MHx8fHwxNzgzMzc2NTA1fDA&ixlib=rb-4.1.0&q=85&w=800",
};

/** Phase T1 — sitewide input theme: white bg + navy text */
export const inputColors = {
  bg: "#FFFFFF",
  text: "#000080",
  placeholder: "rgba(0,0,128,0.55)",
} as const;

export const money = (n: number = 0) =>
  "$" + (n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
