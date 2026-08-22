/**
 * Feb-2026 · P29 — MuteControl reason picker + PATCH payload.
 *
 * Pins:
 *   1. Opening the mute modal loads the reasons list from
 *      GET /settings/muted-reasons and renders the options + a
 *      "Custom…" fallback.
 *   2. Selecting a canned reason submits ``muted_reason: <label>``.
 *   3. Selecting Custom + typing free text submits that string.
 *   4. Submitting without picking a reason sends an empty body
 *      (no ``muted_reason`` key) — backwards compatible with P27.
 *   5. On unmute the reasons list is NOT fetched (no picker on
 *      the unmute path).
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

const _flush = () => new Promise((r) => setTimeout(r, 0));


beforeEach(() => {
  mockGet.mockReset();
  mockPatch.mockReset();
  mockGet.mockResolvedValue({
    items: [
      { id: "r1", label: "Billing dispute", is_active: true },
      { id: "r2", label: "Requested no contact", is_active: true },
    ],
    total: 2,
  });
  mockPatch.mockResolvedValue({ muted: true });
});


describe("MuteControl P29 reason picker", () => {
  it("loads reasons on modal open and renders both canned + custom options", async () => {
    const { getByTestId } = render(<MuteControl customer={{ id: "c1" }} />);
    fireEvent.click(getByTestId("mute-control-btn-c1"));
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/settings/muted-reasons"));
    const select = getByTestId("mute-control-reason-select-c1");
    const opts = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(opts).toContain("Billing dispute");
    expect(opts).toContain("Requested no contact");
    expect(opts).toContain("Custom…");
  });

  it("submitting with a canned reason posts muted_reason=<label>", async () => {
    const { getByTestId } = render(<MuteControl customer={{ id: "c2" }} />);
    fireEvent.click(getByTestId("mute-control-btn-c2"));
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    fireEvent.change(getByTestId("mute-control-reason-select-c2"),
                        { target: { value: "r1" } });
    fireEvent.click(getByTestId("mute-control-confirm-c2"));
    await _flush();
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    expect(mockPatch).toHaveBeenCalledWith(
      "/customers/c2/mute", { muted_reason: "Billing dispute" });
  });

  it("submitting Custom + text posts that free-text reason", async () => {
    const { getByTestId } = render(<MuteControl customer={{ id: "c3" }} />);
    fireEvent.click(getByTestId("mute-control-btn-c3"));
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    fireEvent.change(getByTestId("mute-control-reason-select-c3"),
                        { target: { value: "__custom__" } });
    fireEvent.change(getByTestId("mute-control-reason-custom-c3"),
                        { target: { value: "  Bespoke reason  " } });
    fireEvent.click(getByTestId("mute-control-confirm-c3"));
    await _flush();
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    expect(mockPatch).toHaveBeenCalledWith(
      "/customers/c3/mute", { muted_reason: "Bespoke reason" });
  });

  it("submitting without a reason posts empty body (P27 back-compat)", async () => {
    const { getByTestId } = render(<MuteControl customer={{ id: "c4" }} />);
    fireEvent.click(getByTestId("mute-control-btn-c4"));
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    fireEvent.click(getByTestId("mute-control-confirm-c4"));
    await _flush();
    await waitFor(() => expect(mockPatch).toHaveBeenCalledTimes(1));
    expect(mockPatch).toHaveBeenCalledWith("/customers/c4/mute", {});
  });

  it("unmute does NOT fetch reasons (picker suppressed on unmute path)", async () => {
    const { getByTestId } = render(
      <MuteControl customer={{ id: "cU", is_muted: true }} />,
    );
    fireEvent.click(getByTestId("mute-control-btn-cU"));
    await _flush();
    expect(mockGet).not.toHaveBeenCalled();
    fireEvent.click(getByTestId("mute-control-confirm-cU"));
    await _flush();
    expect(mockPatch).toHaveBeenCalledWith("/customers/cU/unmute", {});
  });
});
