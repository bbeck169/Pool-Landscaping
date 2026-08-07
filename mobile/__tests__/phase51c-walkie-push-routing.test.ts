/**
 * Phase 51c · Feb-2026 — Walkie push notification tap-through routing.
 *
 * Backend fan-out (``services/walkie/push.py``) sets the Expo push
 * ``data`` field to ``{type: "walkie", channel_id, message_id}``.
 * When a user taps the push, the mobile shell's
 * ``notificationRoutes.resolveNotificationRoute`` must deep-link to
 * ``/walkie/{channel_id}``. This test locks the wiring in place —
 * regressing either side (backend field name change or resolver
 * table drift) trips here.
 */
import { resolveNotificationRoute } from "@/src/services/notificationRoutes";

describe("Phase 51c · walkie push tap-through", () => {
  it("routes to /walkie/{channel_id} when data has type=walkie + channel_id", () => {
    const notif = { type: "walkie", channel_id: "ch_pool_1", message_id: "m_1" };
    expect(resolveNotificationRoute(notif, { role: "technician" })).toBe("/walkie/ch_pool_1");
  });

  it("routes to /walkie index when channel_id is missing (defensive)", () => {
    const notif = { type: "walkie", message_id: "m_1" };
    expect(resolveNotificationRoute(notif, { role: "technician" })).toBe("/walkie");
  });

  it("works whether backend uses 'type' or 'kind' key (payload alias)", () => {
    // Backend sets ``data.type`` explicitly. If any legacy fan-out
    // uses ``data.kind`` instead, we still route.
    expect(
      resolveNotificationRoute({ kind: "walkie", channel_id: "ch_x" }, { role: "admin" }),
    ).toBe("/walkie/ch_x");
  });

  it("ignores payloads with unrelated types (returns null / fallback)", () => {
    const notif = { type: "something_else", channel_id: "ch_x" };
    expect(resolveNotificationRoute(notif, { role: "admin" })).toBeNull();
  });

  it("customer role does NOT open walkie (server never sends walkie push to customers, but defensive layer)", () => {
    // The resolver isn't role-gated for walkie because staff-only
    // enforcement lives on the send side (server ``resolve_recipients``
    // never picks up customer users). If a stray payload ever reaches
    // a customer device, the walkie route still resolves — the walkie
    // screen itself renders the ``walkie-empty-customer`` empty state.
    // Locking that expectation here so the mobile-side resolver stays
    // dumb and predictable.
    const notif = { type: "walkie", channel_id: "ch_x" };
    expect(resolveNotificationRoute(notif, { role: "customer" })).toBe("/walkie/ch_x");
  });
});
