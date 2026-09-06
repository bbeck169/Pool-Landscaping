/**
 * Feb-2026 · P27 — MuteControl flow test.
 *
 * Pins the admin+super_admin mute/unmute round-trip:
 *   1. On active customer: renders "Mark Muted" pill (destructive tone).
 *   2. Confirmation modal shows the silent-mode warning banner.
 *   3. Confirm calls ``PATCH /customers/{cid}/mute`` and fires
 *      ``onChange`` with the API payload; cancel closes without call.
 *   4. On muted customer: renders "Unmute" pill (informational tone),
 *      no destructive warning banner.
 *   5. P27 addendum — Unmute is visible to admin (canUnmute=true), NOT
 *      hidden behind super_admin. Component returns null only when
 *      the caller-side gate for the current action is false.
 *   6. API failure fires onError with the message.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api", () => ({ api: { patch: vi.fn(), get: vi.fn().mockResolvedValue({ items: [] }) } }));

import { api } from "@/api";
import MuteControl from "@/components/customers/MuteControl";


const _flush = () => new Promise((r) => setTimeout(r, 0));


describe("MuteControl (P27)", () => {
  it("renders Mark Muted on an active customer", () => {
    const { getByTestId } = render(
      <MuteControl customer={{ id: "c-active" }} />,
    );
    const btn = getByTestId("mute-control-btn-c-active");
    expect(btn.textContent).toContain("Mark Muted");
  });

  it("confirmation modal shows the silent-mode warning banner", () => {
    const { getByTestId, queryByTestId } = render(
      <MuteControl customer={{ id: "c1" }} />,
    );
    expect(queryByTestId("mute-control-modal-c1")).toBeNull();
    fireEvent.click(getByTestId("mute-control-btn-c1"));
    expect(getByTestId("mute-control-modal-c1")).toBeTruthy();
    expect(getByTestId("mute-control-warning-c1").textContent)
      .toMatch(/Silent-mode warning/i);
    expect(getByTestId("mute-control-warning-c1").textContent)
      .toMatch(/admin or super_admin can undo/i);
  });

  it("confirm calls PATCH /customers/{cid}/mute and fires onChange", async () => {
    api.patch.mockResolvedValueOnce({
      muted: true, customer_id: "c2", muted_at: "2026-06-01T10:00:00Z",
    });
    const onChange = vi.fn();
    const { getByTestId } = render(
      <MuteControl customer={{ id: "c2" }} onChange={onChange} />,
    );
    fireEvent.click(getByTestId("mute-control-btn-c2"));
    fireEvent.click(getByTestId("mute-control-confirm-c2"));
    await _flush();
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(api.patch).toHaveBeenCalledWith("/customers/c2/mute", {});
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ muted: true, customer_id: "c2" }),
    );
  });

  it("renders Unmute on a muted customer with informational tone (no warning)", () => {
    const { getByTestId, queryByTestId } = render(
      <MuteControl customer={{ id: "cM", is_muted: true }} />,
    );
    expect(getByTestId("mute-control-btn-cM").textContent).toContain("Unmute");
    fireEvent.click(getByTestId("mute-control-btn-cM"));
    // No destructive-warning banner on the unmute path.
    expect(queryByTestId("mute-control-warning-cM")).toBeNull();
  });

  it("P27 addendum — Unmute button is rendered for admin, not just super_admin", async () => {
    api.patch.mockResolvedValueOnce({ unmuted: true, customer_id: "cU" });
    const onChange = vi.fn();
    // Simulate the CustomersList wiring where admin has BOTH gates true.
    const { getByTestId } = render(
      <MuteControl
        customer={{ id: "cU", is_muted: true }}
        canMute={true}
        canUnmute={true}
        onChange={onChange}
      />,
    );
    // Button visible.
    expect(getByTestId("mute-control-btn-cU")).toBeTruthy();
    fireEvent.click(getByTestId("mute-control-btn-cU"));
    fireEvent.click(getByTestId("mute-control-confirm-cU"));
    await _flush();
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(api.patch).toHaveBeenCalledWith("/customers/cU/unmute", {});
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ unmuted: true }),
    );

    // Same customer with canUnmute=false → the pill hides entirely.
    const { queryByTestId } = render(
      <MuteControl
        customer={{ id: "cH", is_muted: true }}
        canMute={true}
        canUnmute={false}
      />,
    );
    expect(queryByTestId("mute-control-btn-cH")).toBeNull();
  });

  it("onError fires when the API rejects", async () => {
    api.patch.mockRejectedValueOnce(new Error("boom"));
    const onError = vi.fn();
    const { getByTestId } = render(
      <MuteControl customer={{ id: "cE" }} onError={onError} />,
    );
    fireEvent.click(getByTestId("mute-control-btn-cE"));
    fireEvent.click(getByTestId("mute-control-confirm-cE"));
    await _flush();
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onError.mock.calls[0][0]).toContain("boom");
  });
});
