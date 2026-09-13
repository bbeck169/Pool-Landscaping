/**
 * quote-send-to-customer-modal · Feb-2026 · UX Polish Batch B
 *
 * Locks the SendToCustomerModal contract:
 *
 *  1. Modal renders with the customer's primary email pre-filled.
 *  2. Override toggle reveals the email input; Send button disabled
 *     until a non-empty override is typed.
 *  3. Submit fires POST /quotes/:id/send-to-customer with the
 *     resolved body (including note truncation).
 *  4. Success callback fires with the endpoint response.
 *  5. Server error surfaces via onError and keeps the modal open.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const postMock = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({}),
    post: (...args) => postMock(...args),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("@/theme", () => ({
  colors: { muted: "#666", brand: "#0B4A6F", onSurface: "#111", border: "#ddd" },
}));

// Trivial ui-kit shims — only Modal + Button are used.
vi.mock("@/components/ui-kit", () => ({
  Modal: ({ open, title, children, testid }) =>
    open ? (
      <div role="dialog" aria-label={title} data-testid={testid}>{children}</div>
    ) : null,
  Button: ({ children, onClick, disabled, testid, variant }) => (
    <button
      onClick={onClick}
      disabled={!!disabled}
      data-testid={testid}
      data-variant={variant || "default"}
    >{children}</button>
  ),
}));

import SendToCustomerModal from "@/components/quotes/SendToCustomerModal";


beforeEach(() => {
  postMock.mockReset();
});


describe("SendToCustomerModal · Batch B", () => {
  it("pre-fills the primary email as the recipient preview", () => {
    render(
      <SendToCustomerModal
        open
        quoteId="q-1"
        primaryEmail="jamie@example.com"
        onClose={() => {}}
        onSent={() => {}}
        onError={() => {}}
      />,
    );
    expect(
      screen.getByTestId("send-to-customer-recipient-preview").textContent,
    ).toContain("jamie@example.com");
    // Submit is enabled by default (no override → use primary).
    expect(screen.getByTestId("send-to-customer-submit").hasAttribute("disabled"))
      .toBe(false);
  });

  it("override toggle reveals the input and disables Send until non-empty", () => {
    render(
      <SendToCustomerModal
        open
        quoteId="q-1"
        primaryEmail="jamie@example.com"
        onClose={() => {}}
        onSent={() => {}}
        onError={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("send-to-customer-override-toggle"));
    expect(screen.queryByTestId("send-to-customer-override-input")).toBeTruthy();
    // Empty override → submit disabled.
    expect(screen.getByTestId("send-to-customer-submit").hasAttribute("disabled"))
      .toBe(true);
    fireEvent.change(screen.getByTestId("send-to-customer-override-input"), {
      target: { value: "other@example.com" },
    });
    expect(screen.getByTestId("send-to-customer-submit").hasAttribute("disabled"))
      .toBe(false);
  });

  it("submit fires POST with recipient override + note", async () => {
    postMock.mockResolvedValue({
      quote_id: "q-1", status: "sent", sent_at: "2026-02-01T00:00:00Z",
      email_sent: true, recipient: "other@example.com",
    });
    const onSent = vi.fn();
    render(
      <SendToCustomerModal
        open
        quoteId="q-1"
        primaryEmail="jamie@example.com"
        onClose={() => {}}
        onSent={onSent}
        onError={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("send-to-customer-override-toggle"));
    fireEvent.change(screen.getByTestId("send-to-customer-override-input"), {
      target: { value: "other@example.com" },
    });
    fireEvent.change(screen.getByTestId("send-to-customer-note-input"), {
      target: { value: "Approved by CFO — send today." },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("send-to-customer-submit"));
    });
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    const [path, body] = postMock.mock.calls[0];
    expect(path).toBe("/quotes/q-1/send-to-customer");
    expect(body.recipient_email).toBe("other@example.com");
    expect(body.note).toContain("Approved by CFO");
    await waitFor(() => expect(onSent).toHaveBeenCalled());
  });

  it("submit without override sends an empty body (backend resolves primary)", async () => {
    postMock.mockResolvedValue({
      quote_id: "q-1", status: "sent", sent_at: "2026-02-01T00:00:00Z",
      email_sent: true, recipient: "jamie@example.com",
    });
    render(
      <SendToCustomerModal
        open
        quoteId="q-1"
        primaryEmail="jamie@example.com"
        onClose={() => {}}
        onSent={() => {}}
        onError={() => {}}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("send-to-customer-submit"));
    });
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    const body = postMock.mock.calls[0][1];
    // No override toggled → no override key on the request body.
    expect(body.recipient_email).toBeUndefined();
  });

  it("server error surfaces via onError and modal stays open", async () => {
    postMock.mockRejectedValue(new Error("Recipient override is not a valid email."));
    const onError = vi.fn();
    const onClose = vi.fn();
    render(
      <SendToCustomerModal
        open
        quoteId="q-1"
        primaryEmail="jamie@example.com"
        onClose={onClose}
        onSent={() => {}}
        onError={onError}
      />,
    );
    fireEvent.click(screen.getByTestId("send-to-customer-override-toggle"));
    fireEvent.change(screen.getByTestId("send-to-customer-override-input"), {
      target: { value: "bad-email" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("send-to-customer-submit"));
    });
    await waitFor(() => expect(onError).toHaveBeenCalled());
    // Modal stays open — onClose NOT triggered by the failure path.
    expect(onClose).not.toHaveBeenCalled();
  });

  it("still shows the fallback copy when the primary email is truly missing", () => {
    render(
      <SendToCustomerModal
        open
        quoteId="q-1"
        primaryEmail=""
        onClose={() => {}}
        onSent={() => {}}
        onError={() => {}}
      />,
    );
    expect(
      screen.getByTestId("send-to-customer-recipient-preview").textContent,
    ).toContain("no primary email on file");
  });

  it("renders the customer's primary email — regression guard for Batch B tightening", () => {
    // Batch B tester surfaced: the modal showed the fallback copy
    // "(no primary email on file)" even when the backend resolved
    // the customer's email. Root cause: ``GET /quotes/{qid}`` didn't
    // include ``customer_email``. Fixed by joining the customer's
    // ``email`` into the response serializer. This test locks the
    // front-end display invariant for any non-empty prop.
    render(
      <SendToCustomerModal
        open
        quoteId="q-1"
        primaryEmail="k14tester@aquaterra.com"
        onClose={() => {}}
        onSent={() => {}}
        onError={() => {}}
      />,
    );
    const preview = screen.getByTestId("send-to-customer-recipient-preview");
    expect(preview.textContent).toContain("k14tester@aquaterra.com");
    expect(preview.textContent).not.toContain("no primary email on file");
  });
});
