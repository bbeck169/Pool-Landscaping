/**
 * Task 6b · Feb 2026 — Revoke a service-records link (UI regression).
 *
 * Covers:
 *  1. "Recent sends" list renders every send returned by
 *     `GET /customers/{cid}/service-records-links`.
 *  2. Revoke button shows a Yes/No inline confirm.
 *  3. Cancelling the confirm restores the row.
 *  4. Confirming the revoke POSTs the correct endpoint and refreshes
 *     the list (revoked row shows the "Revoked" badge, no Revoke
 *     button).
 *  5. Already-revoked rows do NOT render a Revoke button.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

const { postSpy, getSpy } = vi.hoisted(() => ({
  postSpy: vi.fn(),
  getSpy: vi.fn(),
}));
vi.mock("@/api", () => ({
  api: {
    post: (...a) => postSpy(...a),
    get: (...a) => getSpy(...a),
  },
}));

import SendServiceRecordsLinkModal from "@/components/customers/SendServiceRecordsLinkModal";

function baseCustomer(overrides = {}) {
  return {
    id: "cust-1",
    name: "Jane Doe",
    email: "jane@example.com",
    emails: [{ address: "jane@example.com", is_primary: true }],
    mobiles: [{ number_e164: "+15555550100", is_primary: true }],
    channel_opt_in: { email_marketing: true, sms_marketing: true },
    is_muted: false,
    ...overrides,
  };
}

// Track which URL was hit so we can mock the list + status endpoints
// with different payloads.
function installGetHandler(handler) {
  getSpy.mockImplementation((url) => handler(url));
}

describe("SendServiceRecordsLinkModal · revoke (Task 6b)", () => {
  beforeEach(() => {
    postSpy.mockReset();
    getSpy.mockReset();
  });
  afterEach(() => cleanup());

  it("renders the Recent sends list from the list endpoint", async () => {
    const sends = [
      { id: "s1", channel: "email", recipient: "jane@example.com",
        created_at: "2026-02-07T18:00:00+00:00", revoked_at: null },
      { id: "s2", channel: "sms", recipient: "+15555550100",
        created_at: "2026-02-07T17:00:00+00:00", revoked_at: null },
    ];
    installGetHandler((url) => {
      if (url.includes("/service-records-link-status")) {
        return Promise.resolve({
          sends_last_hour: 2, rate_limit: 5, rate_limited: false,
          last_send_at: sends[0].created_at,
        });
      }
      return Promise.resolve({ sends, limit: 5 });
    });
    render(
      <SendServiceRecordsLinkModal
        open
        customer={baseCustomer()}
        onClose={() => {}}
        onSent={() => {}}
        onError={() => {}}
      />,
    );
    expect(await screen.findByTestId("sr-link-recent-sends")).toBeTruthy();
    expect(screen.getByTestId("sr-link-send-row-s1")).toBeTruthy();
    expect(screen.getByTestId("sr-link-send-row-s2")).toBeTruthy();
    expect(screen.getByTestId("sr-link-send-recipient-s1").textContent)
      .toBe("jane@example.com");
    expect(screen.getByTestId("sr-link-revoke-s1")).toBeTruthy();
    expect(screen.getByTestId("sr-link-revoke-s2")).toBeTruthy();
  });

  it("shows an inline Yes/No confirm on Revoke click", async () => {
    installGetHandler((url) => {
      if (url.includes("/service-records-link-status")) {
        return Promise.resolve({ sends_last_hour: 1, rate_limit: 5, rate_limited: false });
      }
      return Promise.resolve({
        sends: [{ id: "s1", channel: "email", recipient: "jane@example.com",
                    created_at: new Date().toISOString(), revoked_at: null }],
        limit: 5,
      });
    });
    render(
      <SendServiceRecordsLinkModal
        open customer={baseCustomer()}
        onClose={() => {}} onSent={() => {}} onError={() => {}}
      />,
    );
    fireEvent.click(await screen.findByTestId("sr-link-revoke-s1"));
    expect(await screen.findByTestId("sr-link-confirm-s1")).toBeTruthy();
    expect(screen.getByTestId("sr-link-confirm-yes-s1")).toBeTruthy();
    expect(screen.getByTestId("sr-link-confirm-no-s1")).toBeTruthy();
  });

  it("Cancel restores the Revoke button", async () => {
    installGetHandler(() => Promise.resolve({
      sends: [{ id: "s1", channel: "email", recipient: "jane@example.com",
                  created_at: new Date().toISOString(), revoked_at: null }],
      limit: 5,
    }));
    render(
      <SendServiceRecordsLinkModal
        open customer={baseCustomer()}
        onClose={() => {}} onSent={() => {}} onError={() => {}}
      />,
    );
    fireEvent.click(await screen.findByTestId("sr-link-revoke-s1"));
    fireEvent.click(screen.getByTestId("sr-link-confirm-no-s1"));
    // Revoke button restored, confirm gone.
    expect(await screen.findByTestId("sr-link-revoke-s1")).toBeTruthy();
    expect(screen.queryByTestId("sr-link-confirm-s1")).toBeNull();
  });

  it("Confirm posts to the revoke endpoint and refreshes the list", async () => {
    let sendsCall = 0;
    installGetHandler((url) => {
      if (url.includes("/service-records-link-status")) {
        return Promise.resolve({ sends_last_hour: 1, rate_limit: 5, rate_limited: false });
      }
      sendsCall += 1;
      const revoked = sendsCall >= 2;
      return Promise.resolve({
        sends: [
          { id: "s1", channel: "email", recipient: "jane@example.com",
            created_at: new Date().toISOString(),
            revoked_at: revoked ? "2026-02-07T18:05:00+00:00" : null,
            revoked_by_email: revoked ? "admin@aquaterra.com" : null },
        ],
        limit: 5,
      });
    });
    postSpy.mockResolvedValueOnce({
      ok: true, already_revoked: false, id: "s1",
      revoked_at: "2026-02-07T18:05:00+00:00",
      revoked_by_email: "admin@aquaterra.com",
    });
    render(
      <SendServiceRecordsLinkModal
        open customer={baseCustomer()}
        onClose={() => {}} onSent={() => {}} onError={() => {}}
      />,
    );
    fireEvent.click(await screen.findByTestId("sr-link-revoke-s1"));
    fireEvent.click(screen.getByTestId("sr-link-confirm-yes-s1"));
    await waitFor(() =>
      expect(postSpy).toHaveBeenCalledWith(
        "/customers/cust-1/service-records-links/s1/revoke",
        {},
      ),
    );
    // After the revoke, the row should render as revoked (no revoke button).
    await waitFor(() => {
      const row = screen.getByTestId("sr-link-send-row-s1");
      expect(row.getAttribute("data-revoked")).toBe("true");
    });
    expect(screen.queryByTestId("sr-link-revoke-s1")).toBeNull();
    // Meta text mentions "Revoked".
    expect(screen.getByTestId("sr-link-send-meta-s1").textContent)
      .toMatch(/Revoked/);
  });

  it("does NOT render a Revoke button on an already-revoked row", async () => {
    installGetHandler((url) => {
      if (url.includes("/service-records-link-status")) {
        return Promise.resolve({ sends_last_hour: 1, rate_limit: 5, rate_limited: false });
      }
      return Promise.resolve({
        sends: [{ id: "s1", channel: "email", recipient: "jane@example.com",
                    created_at: new Date().toISOString(),
                    revoked_at: "2026-02-07T18:05:00+00:00",
                    revoked_by_email: "admin@aquaterra.com" }],
        limit: 5,
      });
    });
    render(
      <SendServiceRecordsLinkModal
        open customer={baseCustomer()}
        onClose={() => {}} onSent={() => {}} onError={() => {}}
      />,
    );
    expect(await screen.findByTestId("sr-link-send-row-s1")).toBeTruthy();
    expect(screen.queryByTestId("sr-link-revoke-s1")).toBeNull();
    expect(screen.queryByTestId("sr-link-confirm-s1")).toBeNull();
  });
});
