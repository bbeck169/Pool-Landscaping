/**
 * Feb-2026 · BUG G — MassMessagingComposeDialog send payload MUST
 * carry the same filters the preview issued the confirm-token
 * against. Pre-fix, ``handleSend`` dropped ``category_ids``,
 * ``service_days``, and ``assigned_tech_user_ids`` — any admin who
 * applied ANY filter got back 400 ``CONFIRM_TOKEN_FILTERS_MISMATCH``
 * and mass messaging failed silently.
 *
 * This test drives the compose dialog through the "user typed a
 * body → preview fired → user hit Send" flow and inspects the send
 * payload. It intentionally exercises the code path — not just the
 * JSON shape — so a future re-regression here fails loudly.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


const apiPost = vi.fn();
const apiGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    post: (...a) => apiPost(...a),
    get: (...a) => apiGet(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/auth", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));

// Neutralise the sub-components that read from network on mount and
// aren't material to the send-payload assertion.
vi.mock("@/components/mass-messaging/filters/AudienceFiltersPopover", () => ({
  default: () => null,
}));

import MassMessagingComposeDialog from "@/components/mass-messaging/MassMessagingComposeDialog";


beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  // Templates fetch returns empty list.
  apiGet.mockResolvedValue([]);
});


function findSendPayload() {
  const call = apiPost.mock.calls.find((c) => c[0] === "/mass-messaging/send");
  if (!call) throw new Error("send POST not fired");
  return call[1];
}


describe("MassMessagingComposeDialog · BUG G send payload", () => {
  it("send payload includes category_ids / service_days / assigned_tech_user_ids (fields preview issued the token against)", async () => {
    // Preview returns a token so canSend becomes true.
    apiPost.mockImplementation((path) => {
      if (path === "/mass-messaging/preview") {
        return Promise.resolve({
          estimated_recipients: { email: 3, sms: 0 },
          stats: { audience_size: 3 },
          confirm_token: "tok-123",
          sample_render: {},
          filters_applied: {},
        });
      }
      if (path === "/mass-messaging/send") {
        return Promise.resolve({
          batch_id: "b-1", queued_email: 3, queued_sms: 0, status: "running",
        });
      }
      return Promise.reject(new Error("unexpected POST " + path));
    });

    const onOpenChange = vi.fn();
    render(
      <MassMessagingComposeDialog
        open={true}
        onOpenChange={onOpenChange}
      />,
    );

    // Wait for the debounced preview to fire.
    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        "/mass-messaging/preview",
        expect.objectContaining({
          category_ids: expect.any(Array),
          service_days: expect.any(Array),
          assigned_tech_user_ids: expect.any(Array),
        }),
      );
    }, { timeout: 2000 });

    // Click the Send button (triggers the confirm dialog).
    const sendBtn = await screen.findByTestId("mass-messaging-send-btn");
    fireEvent.click(sendBtn);

    // Confirm the send in the confirmation dialog.
    const confirmBtn = await screen.findByTestId("mass-messaging-confirm-send");
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        "/mass-messaging/send",
        expect.any(Object),
      );
    });

    const payload = findSendPayload();
    // The three filter arrays MUST be present so the confirm-token
    // filter-signature guard sees a match.
    expect(payload).toHaveProperty("category_ids");
    expect(payload).toHaveProperty("service_days");
    expect(payload).toHaveProperty("assigned_tech_user_ids");
    expect(Array.isArray(payload.category_ids)).toBe(true);
    expect(Array.isArray(payload.service_days)).toBe(true);
    expect(Array.isArray(payload.assigned_tech_user_ids)).toBe(true);
    // Also carries the confirm_token from preview.
    expect(payload.confirm_token).toBe("tok-123");
    // And audience_status default.
    expect(payload.audience_status).toBe("active");
  });
});
