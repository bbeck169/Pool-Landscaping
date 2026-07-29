import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: {
    post: vi.fn(async (path, body) => ({
      submitted: body?.publish_to_website && body?.photo_license_ack,
      public_checkin_id: "pub-1",
      reason: "opt_out_or_no_license",
    })),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import SubmitToPublicButton from "@/components/checkins/SubmitToPublicButton";
import { api } from "@/api";

describe("SubmitToPublicButton", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("does not open the modal by default", () => {
    render(<SubmitToPublicButton checkinId="c-1" />);
    expect(screen.queryByTestId("submit-public-modal")).toBeNull();
    expect(screen.getByTestId("submit-public-open")).toBeTruthy();
  });

  it("opens modal on click and shows the publish checkbox", () => {
    render(<SubmitToPublicButton checkinId="c-1" />);
    fireEvent.click(screen.getByTestId("submit-public-open"));
    expect(screen.getByTestId("submit-public-modal")).toBeTruthy();
    expect(screen.getByTestId("submit-public-publish")).toBeTruthy();
    // Ack checkbox only appears once publish is checked.
    expect(screen.queryByTestId("submit-public-ack")).toBeNull();
  });

  it("shows the license-ack checkbox once publish is checked", () => {
    render(<SubmitToPublicButton checkinId="c-1" />);
    fireEvent.click(screen.getByTestId("submit-public-open"));
    fireEvent.click(screen.getByTestId("submit-public-publish"));
    expect(screen.getByTestId("submit-public-ack")).toBeTruthy();
  });

  it("submit button is disabled until both boxes are ticked", () => {
    render(<SubmitToPublicButton checkinId="c-1" />);
    fireEvent.click(screen.getByTestId("submit-public-open"));

    // Neither → disabled
    fireEvent.click(screen.getByTestId("submit-public-submit"));
    expect(api.post).not.toHaveBeenCalled();

    // Only publish → still disabled
    fireEvent.click(screen.getByTestId("submit-public-publish"));
    fireEvent.click(screen.getByTestId("submit-public-submit"));
    expect(api.post).not.toHaveBeenCalled();

    // Both ticked → click submits
    fireEvent.click(screen.getByTestId("submit-public-ack"));
    fireEvent.click(screen.getByTestId("submit-public-submit"));
    expect(api.post).toHaveBeenCalledTimes(1);
    const [path, body] = api.post.mock.calls[0];
    expect(path).toBe("/checkins/c-1/submit-public");
    expect(body).toEqual({
      publish_to_website: true,
      photo_license_ack: true,
      description: undefined,
    });
  });

  it("closes on successful submit and calls onSubmitted", async () => {
    const onSubmitted = vi.fn();
    render(<SubmitToPublicButton checkinId="c-1" onSubmitted={onSubmitted} />);
    fireEvent.click(screen.getByTestId("submit-public-open"));
    fireEvent.click(screen.getByTestId("submit-public-publish"));
    fireEvent.click(screen.getByTestId("submit-public-ack"));
    fireEvent.click(screen.getByTestId("submit-public-submit"));
    await waitFor(() => { expect(onSubmitted).toHaveBeenCalledWith("pub-1"); });
    // Modal closes.
    await waitFor(() => {
      expect(screen.queryByTestId("submit-public-modal")).toBeNull();
    });
  });
});
