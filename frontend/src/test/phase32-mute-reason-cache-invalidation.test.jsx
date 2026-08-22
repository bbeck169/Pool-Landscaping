/**
 * Feb-2026 · P32 — MuteControl re-fetches the reasons list on the
 * next open AFTER a successful mute, so any server-side auto-persist
 * of a novel custom reason (see backend ``_p32_auto_persist_reason``)
 * shows up in the picker immediately.
 *
 * The lazy fetch in ``MuteControl`` only fires when ``reasons.length
 * === 0``. Before P32 the state was kept across modal closes, so the
 * auto-created row was invisible until the page was reloaded. This
 * test proves the cache is now cleared on a successful mute.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";

const mockGet = vi.fn();
const mockPatch = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => mockGet(...a), patch: (...a) => mockPatch(...a) },
}));

import MuteControl from "@/components/customers/MuteControl";


beforeEach(() => {
  mockGet.mockReset();
  mockPatch.mockReset();
  mockPatch.mockResolvedValue({ muted: true });
});


describe("MuteControl · P32 reason-cache invalidation", () => {
  it("re-fetches the reasons list on next open after a mute succeeds", async () => {
    // First open — seed list has two options.
    mockGet.mockResolvedValueOnce({
      items: [
        { id: "r1", label: "Billing dispute", is_active: true },
      ],
      total: 1,
    });
    // Second open — a novel reason has been auto-persisted server-side.
    mockGet.mockResolvedValueOnce({
      items: [
        { id: "r1", label: "Billing dispute", is_active: true },
        { id: "r2", label: "Novel P32 reason", is_active: true, auto_created: true },
      ],
      total: 2,
    });

    let mutable = { id: "c1", is_muted: false };
    const { getByTestId, rerender } = render(
      <MuteControl customer={mutable} />,
    );

    // 1) Open, submit with "Custom…" + type a novel reason, then confirm.
    fireEvent.click(getByTestId("mute-control-btn-c1"));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));
    fireEvent.change(getByTestId("mute-control-reason-select-c1"),
      { target: { value: "__custom__" } });
    fireEvent.change(
      await waitFor(() => getByTestId("mute-control-reason-custom-c1")),
      { target: { value: "Novel P32 reason" } },
    );
    fireEvent.click(getByTestId("mute-control-confirm-c1"));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      "/customers/c1/mute", { muted_reason: "Novel P32 reason" },
    ));

    // 2) Re-open the modal. Because the customer is still non-muted
    //    from the component's POV (parent hasn't refreshed yet in this
    //    test), and because the local reasons cache was cleared on
    //    success, the picker MUST re-fetch — proving the P32 fix.
    fireEvent.click(getByTestId("mute-control-btn-c1"));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));

    // 3) The freshly-fetched list contains the auto-persisted label.
    const select = getByTestId("mute-control-reason-select-c1");
    const opts = Array.from(select.querySelectorAll("option"))
      .map((o) => o.textContent);
    expect(opts).toContain("Novel P32 reason");
  });

  it("does NOT clear the reasons cache on unmute (unmute has no picker)", async () => {
    // Cached list won't be consulted; unmute path skips the fetch.
    const { getByTestId } = render(
      <MuteControl customer={{ id: "c9", is_muted: true }} />,
    );
    fireEvent.click(getByTestId("mute-control-btn-c9"));
    // Confirm unmute.
    await waitFor(() => expect(getByTestId("mute-control-confirm-c9"))
      .toBeTruthy());
    fireEvent.click(getByTestId("mute-control-confirm-c9"));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith(
      "/customers/c9/unmute", {},
    ));
    // Reasons fetch NEVER happened — unmute stays lean.
    expect(mockGet).not.toHaveBeenCalled();
  });
});
