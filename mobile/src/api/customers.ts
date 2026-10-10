/**
 * Phase 36 · Customers API helpers (mobile).
 *
 * ``toggleVip`` mirrors web ``CustomerDetail.jsx::toggleVip`` exactly:
 *   PATCH /api/customers/{cid}/vip  body { is_vip, vip_note }
 * Admin-only on the backend (403 otherwise). The backend stamps
 * ``vip_since`` on OFF→ON, clears it on ON→OFF, and returns the fresh
 * customer doc. ``vip_note`` is forwarded unchanged so a toggle never
 * wipes an existing note (web passes ``customer.vip_note ?? null``).
 */
import { api } from "@/src/api";

export const toggleVip = (customerId: string, isVip: boolean, vipNote?: string | null) =>
  api.patch(`/customers/${customerId}/vip`, {
    is_vip: isVip,
    vip_note: vipNote ?? null,
  }) as Promise<{ is_vip?: boolean; vip_since?: string | null; vip_note?: string | null } & Record<string, any>>;
