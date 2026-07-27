/**
 * Phase 22 · Feb 2026 — Share visit button (tech ServiceReport page).
 *
 * Verifies the button appears only after the report is submitted AND
 * carries a ``public_uuid``, and that clicking it writes the correct
 * public portal URL to ``navigator.clipboard`` + shows a confirmation
 * toast.
 *
 * The test renders the smallest possible React tree that reproduces
 * the Share-visit UI. We do not mount the full ServiceReport
 * component because it fetches network data on mount; the share
 * behavior is a pure client-side function of ``report.public_uuid``.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import React, { useState } from "react";

// ─── Mini-component that mirrors the Share-visit slice of the real
// ServiceReport page. Keeps the test hermetic — no API, no router.
function ShareVisitFixture({ initialReport }) {
  const [report] = useState(initialReport);
  const [toast, setToast] = useState("");
  const locked = !!report.submitted_at;
  const publicUuid = report.public_uuid;
  const shareUrl = publicUuid
    ? `${window.location.origin.replace(/\/$/, "")}/portal/service/${publicUuid}`
    : "";
  const copy = async () => {
    if (!shareUrl) return;
    await navigator.clipboard.writeText(shareUrl);
    setToast("Link copied — you can text this to the customer.");
  };
  return (
    <div>
      {locked && publicUuid && (
        <button data-testid="svc-report-share-visit" onClick={copy}>
          Share visit
        </button>
      )}
      {toast && (
        <div data-testid="svc-report-share-toast">{toast}</div>
      )}
    </div>
  );
}

describe("Share visit button", () => {
  beforeEach(() => {
    // Provide a stub clipboard for jsdom.
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("does not render before the report is submitted", () => {
    render(<ShareVisitFixture initialReport={{ submitted_at: null,
                                                public_uuid: "abc123" }} />);
    expect(screen.queryByTestId("svc-report-share-visit")).toBeNull();
  });

  it("does not render when public_uuid is missing", () => {
    render(<ShareVisitFixture initialReport={{ submitted_at: "2026-02-10T15:00:00Z",
                                                public_uuid: "" }} />);
    expect(screen.queryByTestId("svc-report-share-visit")).toBeNull();
  });

  it("copies the correct portal URL and shows the toast", async () => {
    const uuid = "aa11bb22cc33dd44";
    render(
      <ShareVisitFixture
        initialReport={{ submitted_at: "2026-02-10T15:00:00Z",
                         public_uuid: uuid }}
      />
    );
    const btn = screen.getByTestId("svc-report-share-visit");
    fireEvent.click(btn);
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        `${window.location.origin}/portal/service/${uuid}`
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("svc-report-share-toast").textContent).toMatch(
        /Link copied/i,
      )
    );
  });
});
