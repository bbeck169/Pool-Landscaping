/**
 * P2 #7 · Feb-2026 — MassMessagingComposeDialog Card-on-file +
 * Portal-login filter UI contract.
 *
 * Covers:
 *   1. Both checkbox rows render with their declared testids and
 *      are UNchecked on open (null-sentinel default).
 *   2. Toggling the Card-on-file checkbox triggers a preview
 *      re-fetch; the payload carries ``has_card_on_file: true``.
 *   3. Toggling the Portal-login checkbox triggers a preview
 *      re-fetch; the payload carries ``has_portal_login: true``.
 *   4. Send payload — regardless of filter state — ALWAYS carries
 *      BOTH keys (as ``true | null``, never omitted). BUG G
 *      non-regression extended to the P2 #7 filters so the
 *      confirm-token-binding signature stays deterministic.
 *   5. Reset-on-open — toggling a filter, closing the dialog, and
 *      reopening it clears both filter slices back to null.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


const apiPost = vi.fn();
const apiGet = vi.fn();
vi.mock("@/api", () => ({
  api: { post: (...a) => apiPost(...a), get: (...a) => apiGet(...a) },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/auth", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));


import MassMessagingComposeDialog from "@/components/mass-messaging/MassMessagingComposeDialog";


beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiGet.mockResolvedValue([]);
});


function _wirePreviewOk() {
  apiPost.mockImplementation((path) => {
    if (path === "/mass-messaging/preview") {
      return Promise.resolve({
        estimated_recipients: { email: 3, sms: 0 },
        stats: { audience_size: 3 },
        confirm_token: "tok-p27",
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
}


function _lastPreviewPayload() {
  const calls = apiPost.mock.calls.filter((c) => c[0] === "/mass-messaging/preview");
  if (calls.length === 0) throw new Error("no preview POST fired");
  return calls[calls.length - 1][1];
}


function _findSendPayload() {
  const call = apiPost.mock.calls.find((c) => c[0] === "/mass-messaging/send");
  if (!call) throw new Error("send POST not fired");
  return call[1];
}


describe("P2 #7 · Mass Messaging · Card-on-file + Portal-login filters", () => {
  it("Case 1 — both checkboxes render with correct testids, unchecked on open", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());

    const cof = screen.getByTestId("mass-messaging-filter-card-on-file");
    const pl = screen.getByTestId("mass-messaging-filter-portal-login");
    // Radix Checkbox exposes `data-state="checked"` / `"unchecked"`.
    expect(cof.getAttribute("data-state")).toBe("unchecked");
    expect(pl.getAttribute("data-state")).toBe("unchecked");

    // The initial preview payload carries BOTH keys as null.
    const payload = _lastPreviewPayload();
    expect(payload).toHaveProperty("has_card_on_file", null);
    expect(payload).toHaveProperty("has_portal_login", null);
  });

  it("Case 2 — toggling Card-on-file sets has_card_on_file:true on preview refetch", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    const callsBefore = apiPost.mock.calls.length;

    fireEvent.click(screen.getByTestId("mass-messaging-filter-card-on-file"));
    await waitFor(() => {
      expect(apiPost.mock.calls.length).toBeGreaterThan(callsBefore);
    }, { timeout: 2000 });

    const payload = _lastPreviewPayload();
    expect(payload.has_card_on_file).toBe(true);
    expect(payload.has_portal_login).toBeNull();
  });

  it("Case 3 — toggling Portal-login sets has_portal_login:true on preview refetch", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    const callsBefore = apiPost.mock.calls.length;

    fireEvent.click(screen.getByTestId("mass-messaging-filter-portal-login"));
    await waitFor(() => {
      expect(apiPost.mock.calls.length).toBeGreaterThan(callsBefore);
    }, { timeout: 2000 });

    const payload = _lastPreviewPayload();
    expect(payload.has_portal_login).toBe(true);
    expect(payload.has_card_on_file).toBeNull();
  });

  it("Case 4 — send payload ALWAYS carries both keys (even when unset) — BUG G extension", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    // Wait for preview to populate the confirm_token.
    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        "/mass-messaging/preview",
        expect.any(Object),
      );
    });

    // Click Send button → confirm dialog.
    const sendBtn = await screen.findByTestId("mass-messaging-send-btn");
    fireEvent.click(sendBtn);
    const confirmBtn = await screen.findByTestId("mass-messaging-confirm-send");
    fireEvent.click(confirmBtn);
    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        "/mass-messaging/send",
        expect.any(Object),
      );
    });

    const payload = _findSendPayload();
    // Both keys MUST be present (never omitted) with null-sentinel.
    expect(payload).toHaveProperty("has_card_on_file");
    expect(payload).toHaveProperty("has_portal_login");
    expect(payload.has_card_on_file).toBeNull();
    expect(payload.has_portal_login).toBeNull();
  });

  it("Case 5 — reset-on-open clears both filter slices back to null", async () => {
    _wirePreviewOk();
    const { rerender } = render(
      <MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />,
    );
    await waitFor(() => expect(apiPost).toHaveBeenCalled());

    // Turn both filters on.
    fireEvent.click(screen.getByTestId("mass-messaging-filter-card-on-file"));
    fireEvent.click(screen.getByTestId("mass-messaging-filter-portal-login"));
    await waitFor(() => {
      const p = _lastPreviewPayload();
      return p.has_card_on_file === true && p.has_portal_login === true;
    });

    // Close + reopen the dialog — reset-on-open should clear state.
    rerender(<MassMessagingComposeDialog open={false} onOpenChange={vi.fn()} />);
    apiPost.mockClear();
    rerender(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        "/mass-messaging/preview",
        expect.any(Object),
      );
    });

    const payload = _lastPreviewPayload();
    expect(payload.has_card_on_file).toBeNull();
    expect(payload.has_portal_login).toBeNull();

    // UI reflects the reset.
    const cof = screen.getByTestId("mass-messaging-filter-card-on-file");
    const pl = screen.getByTestId("mass-messaging-filter-portal-login");
    expect(cof.getAttribute("data-state")).toBe("unchecked");
    expect(pl.getAttribute("data-state")).toBe("unchecked");
  });
});
