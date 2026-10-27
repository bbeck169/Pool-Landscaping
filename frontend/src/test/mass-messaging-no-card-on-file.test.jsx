/**
 * YY · Feb-2026 — MassMessagingComposeDialog "No card on file"
 * audience filter + mutex invariant.
 *
 * Opens the inverse-cohort branch of the P2 #7 Card-on-file filter
 * via a second checkbox that shares the ``hasCardOnFile`` state
 * slice with the existing positive checkbox — implicit mutex.
 *
 * Pins:
 *   1. Initial state — both Card-on-file checkboxes unchecked,
 *      payload carries ``has_card_on_file: null`` (regression lock
 *      on P2 #7 default).
 *   2. Tick "Has card on file" → state ``true``; "No card on file"
 *      stays unchecked; payload ``has_card_on_file: true``
 *      (positive-branch regression lock).
 *   3. Tick "No card on file" from clean → state ``false``;
 *      "Has card on file" stays unchecked; payload
 *      ``has_card_on_file: false`` (YY fix).
 *   4. Mutex invariant · ticking "Has card" while "No card" is
 *      checked flips state to ``true`` and auto-unticks "No card".
 *   5. Mutex invariant · ticking "No card" while "Has card" is
 *      checked flips state to ``false`` and auto-unticks "Has card".
 *   6. Untick the active one → state ``null`` (both unchecked).
 *   7. Send payload — regardless of filter state — always carries
 *      the key with the active tri-state value (BUG G non-regression
 *      extended to YY ``false``).
 *   8. Reset-on-open — tick "No card", close, reopen → both
 *      Card-on-file checkboxes unchecked, payload ``null``.
 *   9. Portal-login regression lock — still binary null↔true only
 *      (no mutex pair added; YY opt-in is per-field).
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
        confirm_token: "tok-yy",
        sample_render: {},
        filters_applied: {},
      });
    }
    if (path === "/mass-messaging/send") {
      return Promise.resolve({
        batch_id: "b-yy", queued_email: 3, queued_sms: 0, status: "running",
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


async function _waitPreviewHasCardEquals(expected) {
  await waitFor(() => {
    const p = _lastPreviewPayload();
    if (p.has_card_on_file !== expected) {
      throw new Error(
        `expected has_card_on_file=${JSON.stringify(expected)}, ` +
        `got ${JSON.stringify(p.has_card_on_file)}`,
      );
    }
  }, { timeout: 2000 });
}


describe("YY · Mass Messaging · 'No card on file' filter + mutex", () => {
  it("Case 1 — initial state: both Card-on-file checkboxes unchecked, payload null", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());

    const hasCard = screen.getByTestId("mass-messaging-filter-card-on-file");
    const noCard = screen.getByTestId("mass-messaging-filter-no-card-on-file");
    expect(hasCard.getAttribute("data-state")).toBe("unchecked");
    expect(noCard.getAttribute("data-state")).toBe("unchecked");

    const payload = _lastPreviewPayload();
    expect(payload).toHaveProperty("has_card_on_file", null);
  });

  it("Case 2 — tick 'Has card on file' → true; 'No card' stays unchecked", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("mass-messaging-filter-card-on-file"));
    await _waitPreviewHasCardEquals(true);

    const hasCard = screen.getByTestId("mass-messaging-filter-card-on-file");
    const noCard = screen.getByTestId("mass-messaging-filter-no-card-on-file");
    expect(hasCard.getAttribute("data-state")).toBe("checked");
    expect(noCard.getAttribute("data-state")).toBe("unchecked");
    expect(_lastPreviewPayload().has_card_on_file).toBe(true);
  });

  it("Case 3 — tick 'No card on file' from clean → false; 'Has card' stays unchecked", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("mass-messaging-filter-no-card-on-file"));
    await _waitPreviewHasCardEquals(false);

    const hasCard = screen.getByTestId("mass-messaging-filter-card-on-file");
    const noCard = screen.getByTestId("mass-messaging-filter-no-card-on-file");
    expect(hasCard.getAttribute("data-state")).toBe("unchecked");
    expect(noCard.getAttribute("data-state")).toBe("checked");
    expect(_lastPreviewPayload().has_card_on_file).toBe(false);
  });

  it("Case 4 — mutex: ticking 'Has card' while 'No card' checked → true, 'No card' auto-unticks", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());

    // Start by ticking "No card on file".
    fireEvent.click(screen.getByTestId("mass-messaging-filter-no-card-on-file"));
    await _waitPreviewHasCardEquals(false);

    // Now tick "Has card on file" — mutex should flip state to true.
    fireEvent.click(screen.getByTestId("mass-messaging-filter-card-on-file"));
    await _waitPreviewHasCardEquals(true);

    const hasCard = screen.getByTestId("mass-messaging-filter-card-on-file");
    const noCard = screen.getByTestId("mass-messaging-filter-no-card-on-file");
    expect(hasCard.getAttribute("data-state")).toBe("checked");
    expect(noCard.getAttribute("data-state")).toBe("unchecked");
  });

  it("Case 5 — mutex: ticking 'No card' while 'Has card' checked → false, 'Has card' auto-unticks", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());

    // Start by ticking "Has card on file".
    fireEvent.click(screen.getByTestId("mass-messaging-filter-card-on-file"));
    await _waitPreviewHasCardEquals(true);

    // Now tick "No card on file" — mutex should flip state to false.
    fireEvent.click(screen.getByTestId("mass-messaging-filter-no-card-on-file"));
    await _waitPreviewHasCardEquals(false);

    const hasCard = screen.getByTestId("mass-messaging-filter-card-on-file");
    const noCard = screen.getByTestId("mass-messaging-filter-no-card-on-file");
    expect(hasCard.getAttribute("data-state")).toBe("unchecked");
    expect(noCard.getAttribute("data-state")).toBe("checked");
  });

  it("Case 6 — untick the active one returns state to null (both unchecked)", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());

    // Tick "No card" → state false.
    fireEvent.click(screen.getByTestId("mass-messaging-filter-no-card-on-file"));
    await _waitPreviewHasCardEquals(false);

    // Untick "No card" (click it again) → state null.
    fireEvent.click(screen.getByTestId("mass-messaging-filter-no-card-on-file"));
    await _waitPreviewHasCardEquals(null);

    const hasCard = screen.getByTestId("mass-messaging-filter-card-on-file");
    const noCard = screen.getByTestId("mass-messaging-filter-no-card-on-file");
    expect(hasCard.getAttribute("data-state")).toBe("unchecked");
    expect(noCard.getAttribute("data-state")).toBe("unchecked");
  });

  it("Case 7 — send payload carries has_card_on_file:false when 'No card' is selected (BUG G non-regression · YY)", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("mass-messaging-filter-no-card-on-file"));
    await _waitPreviewHasCardEquals(false);

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
    expect(payload).toHaveProperty("has_card_on_file");
    expect(payload.has_card_on_file).toBe(false);
    // Portal-login must still ship as null-sentinel (strict-sibling lock).
    expect(payload).toHaveProperty("has_portal_login", null);
  });

  it("Case 8 — reset-on-open: 'No card' tick + close + reopen → both unchecked, payload null", async () => {
    _wirePreviewOk();
    const { rerender } = render(
      <MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />,
    );
    await waitFor(() => expect(apiPost).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("mass-messaging-filter-no-card-on-file"));
    await _waitPreviewHasCardEquals(false);

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

    const hasCard = screen.getByTestId("mass-messaging-filter-card-on-file");
    const noCard = screen.getByTestId("mass-messaging-filter-no-card-on-file");
    expect(hasCard.getAttribute("data-state")).toBe("unchecked");
    expect(noCard.getAttribute("data-state")).toBe("unchecked");
  });

  it("Case 9 — portal-login regression lock: still binary null↔true, no mutex pair added", async () => {
    _wirePreviewOk();
    render(<MassMessagingComposeDialog open={true} onOpenChange={vi.fn()} />);
    await waitFor(() => expect(apiPost).toHaveBeenCalled());

    // Portal-login still has only ONE checkbox (no sibling "No portal").
    expect(
      screen.queryByTestId("mass-messaging-filter-no-portal-login"),
    ).toBeNull();

    // Tick portal-login → true.
    fireEvent.click(screen.getByTestId("mass-messaging-filter-portal-login"));
    await waitFor(() => {
      const p = _lastPreviewPayload();
      if (p.has_portal_login !== true) {
        throw new Error("portal-login did not flip to true");
      }
    }, { timeout: 2000 });

    // Untick → null (no false intermediate).
    fireEvent.click(screen.getByTestId("mass-messaging-filter-portal-login"));
    await waitFor(() => {
      const p = _lastPreviewPayload();
      if (p.has_portal_login !== null) {
        throw new Error("portal-login did not flip back to null");
      }
    }, { timeout: 2000 });
  });
});
