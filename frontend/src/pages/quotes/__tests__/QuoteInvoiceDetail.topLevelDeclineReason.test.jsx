/**
 * PORTAL-QUOTE-DECLINE-REQUIRE-REASON · Feb-2026 — Vitest coverage
 * for the admin ``DeclineReasonBlock`` rendered on
 * ``QuoteInvoiceDetail``.
 *
 * 2 cases:
 *   (i)  Block renders when ``doc.status === "declined"`` and
 *        surfaces category label + text + relative-time timestamp.
 *   (ii) Block renders NOTHING when the doc is not declined
 *        (``"sent"`` / ``"accepted"`` / ``"draft"``).
 */
import React from "react";
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

// The component references ``declineReasonLabel`` from the FE enum
// module and ``formatDeclinedTimestamp`` which is also exported from
// the same QuoteInvoiceDetail file.  Neither needs mocking.
import { DeclineReasonBlock } from "@/pages/quotes/QuoteInvoiceDetail";


beforeEach(() => {
  cleanup();
});


describe("DeclineReasonBlock · PORTAL-QUOTE-DECLINE-REQUIRE-REASON", () => {
  it("case (i) · renders category label + text + timestamp when doc is declined", () => {
    render(
      <DeclineReasonBlock
        doc={{
          status: "declined",
          decision: "declined",
          declined_at: new Date(
            Date.now() - 2 * 60 * 60 * 1000, // 2 hours ago
          ).toISOString(),
          decline_reason_category: "going_with_another_provider",
          decline_reason_text:
            "We received a lower bid from a competitor that "
            + "included the same scope.",
          decline_reason:
            "We received a lower bid from a competitor that "
            + "included the same scope.",
        }}
      />,
    );

    const block = screen.getByTestId(
      "admin-top-level-decline-reason-block",
    );
    expect(block).toBeTruthy();

    // Category label uses the display-label map, NOT the raw
    // snake_case value.
    const cat = screen.getByTestId(
      "admin-top-level-decline-reason-category",
    );
    expect(cat.textContent).toBe("Going with another provider");

    // Full free-text visible.
    const text = screen.getByTestId(
      "admin-top-level-decline-reason-text",
    );
    expect(text.textContent).toContain("lower bid from a competitor");

    // Relative-time timestamp present ("Declined 2h ago").
    const at = screen.getByTestId(
      "admin-top-level-decline-reason-at",
    );
    expect(at.textContent.length).toBeGreaterThan(0);
    expect(at.textContent).toMatch(/Declined/i);
  });

  it("case (ii) · renders nothing when doc.status is not declined", () => {
    // 'sent' — not declined.
    const { container: sentContainer } = render(
      <DeclineReasonBlock
        doc={{
          status: "sent",
          decision: null,
          decline_reason_category: "too_expensive",
          decline_reason_text: "This block must NOT render.",
          declined_at: null,
        }}
      />,
    );
    expect(sentContainer.firstChild).toBeNull();
    expect(
      screen.queryByTestId("admin-top-level-decline-reason-block"),
    ).toBeNull();
    cleanup();

    // 'accepted' — not declined.
    const { container: acceptedContainer } = render(
      <DeclineReasonBlock
        doc={{
          status: "accepted",
          decision: "accepted",
          decline_reason_text: "Still must NOT render.",
        }}
      />,
    );
    expect(acceptedContainer.firstChild).toBeNull();
    cleanup();

    // 'draft' — not declined.
    const { container: draftContainer } = render(
      <DeclineReasonBlock doc={{ status: "draft" }} />,
    );
    expect(draftContainer.firstChild).toBeNull();
  });
});
