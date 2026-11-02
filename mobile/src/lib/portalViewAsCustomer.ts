/**
 * TD-91 · "View as customer" — open the customer portal in the in-app
 * browser AS this customer (web `cd-impersonate` parity). Only the URL
 * carries the 30-min customer token; the admin's own mobile session is
 * never touched (contrast: profile header "Switch to customer view" =
 * in-app session swap via useAuth().startImpersonation).
 *
 * BE `POST /admin/impersonate/{customer_id}` (routers/auth.py) is
 * require_admin + tenant-scoped, logs `impersonation_started` with the
 * admin's id/name/role, and stamps `impersonator_id` on the token.
 * Web origin = EXPO_PUBLIC_WEB_URL, else the API host (same inline idiom
 * as WebOnlyPage / ComingSoonPage).
 *
 * Moved verbatim from PortalAccessPanel (behaviour-equivalence factor) so
 * the profile header can reuse it. Callers own the role / login / active
 * gating and their busy-state shape.
 */
import { Linking } from "react-native";
import * as WebBrowser from "expo-web-browser";

import { api } from "@/src/api";
import { mapApiError } from "@/src/utils/mapApiError";
import type { ToastVariant } from "@/src/components/ToastProvider";

export type ViewAsCustomerDeps = {
  /** true when the request starts, false when it settles (always, via finally). */
  setBusy: (busy: boolean) => void;
  showToast: (message: string, variant?: ToastVariant) => void;
};

export async function viewAsCustomer(customerId: string, { setBusy, showToast }: ViewAsCustomerDeps): Promise<void> {
  setBusy(true);
  try {
    let token = "";
    try {
      const r: any = await api.post(`/admin/impersonate/${customerId}`, {});
      token = r?.access_token || "";
    } catch (e) {
      const m = mapApiError(e);
      if (m.kind === "forbidden") {
        console.warn("[portal] view-as-customer forbidden", m.status);
        showToast("Access denied — only admins can view the portal as a customer.", "error");
      } else if (m.kind === "offline") {
        showToast("Couldn't reach the server — check your connection and try again.", "error");
      } else {
        showToast(m.message, "error");
      }
      return;
    }
    if (!token) { showToast("Couldn't start the customer session — please try again.", "error"); return; }
    const webBase = (process.env.EXPO_PUBLIC_WEB_URL || process.env.EXPO_PUBLIC_BACKEND_URL || "")
      .replace(/\/+$/, "").replace(/\/api$/, "");
    const url = `${webBase}/portal/home?impersonation_token=${encodeURIComponent(token)}`;
    try {
      await WebBrowser.openBrowserAsync(url);
    } catch {
      try { await Linking.openURL(url); } catch { showToast("Couldn't open the browser — please try again.", "error"); }
    }
  } finally {
    setBusy(false);
  }
}
