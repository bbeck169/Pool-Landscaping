/**
 * PORTAL-INVITE-EMAIL-COLLISION-FIX · Feb-2026 (P0 #1 + P0 #2).
 *
 * Vitest coverage for the admin ``PortalInviteQuickAction`` 409
 * handler.  Backend ``_upsert_customer_user`` fails loudly with
 * ``{status: 409, detail: {code: "portal_user_email_collision",
 * existing_customer_id_prefix}}`` when a different customer in the
 * same tenant already owns this email.  The handler must render a
 * human-readable toast instead of a generic error.
 *
 * Single case:
 *   • 409 collision → onToast called with
 *     ``tone: "error"`` and a message that names the collision +
 *     echoes the existing-customer-id prefix.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { postSpy } = vi.hoisted(() => ({ postSpy: vi.fn() }));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: { post: (...a) => postSpy(...a), get: vi.fn() },
}));

beforeEach(() => {
  postSpy.mockReset();
});

import { PortalInviteQuickAction } from "@/pages/customers/CustomerDetail";


describe("PortalInviteQuickAction · PORTAL-INVITE-EMAIL-COLLISION-FIX", () => {
  it("renders a human-readable toast + prefix when 409 portal_user_email_collision is returned", async () => {
    const err = new Error("Conflict");
    err.status = 409;
    err.data = {
      detail: {
        code: "portal_user_email_collision",
        message:
          "This email is already linked to another customer in "
          + "this tenant. Resolve the duplicate before re-inviting.",
        existing_user_id_prefix: "abcd1234",
        existing_customer_id_prefix: "efgh5678",
      },
    };
    postSpy.mockRejectedValue(err);

    const toastSpy = vi.fn();
    render(
      <PortalInviteQuickAction
        customer={{
          id: "cust-xyz",
          emails: [],
          email: "shared@synthetic.test",
        }}
        onToast={toastSpy}
      />,
    );

    fireEvent.click(screen.getByTestId("cd-portal-invite"));

    await waitFor(() => expect(toastSpy).toHaveBeenCalledTimes(1));
    const call = toastSpy.mock.calls[0][0];
    expect(call.tone).toBe("error");
    expect(call.message).toContain(
      "already linked to another customer in this tenant",
    );
    expect(call.message).toContain("efgh5678");
    expect(call.testid).toBe("portal-invite-email-collision-toast");
  });
});
