/**
 * Ticket LL · Feb-2026 — AiRewriteButton component unit tests.
 *
 * Covers:
 *   §1 idle render + min-length gate (disabled below 10 chars,
 *      enabled at ≥10).
 *   §2 clicking fires POST /ai/rewrite with the trimmed draft.
 *   §3 success → ``onReplace(rewritten)`` + Undo button renders.
 *   §4 Undo click restores the original text + hides the Undo
 *      button.
 *   §5 operator edits the output within the 10-sec window → Undo
 *      clears early (watch via useEffect on value prop).
 *   §6 429 ``REWRITE_COOLDOWN`` surfaces a friendly toast.
 *   §7 429 ``REWRITE_HOURLY_CAP`` surfaces the hourly-cap toast.
 *   §8 503 ``REWRITE_UPSTREAM_UNAVAILABLE`` surfaces the AI-
 *      unavailable toast.
 *   §9 generic error → "Rewrite failed." toast.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, cleanup, waitFor,
} from "@testing-library/react";


// ── API mock ──────────────────────────────────────────────────
const { apiPostMock } = vi.hoisted(() => ({ apiPostMock: vi.fn() }));
vi.mock("@/api", () => ({
  api: { post: apiPostMock, get: vi.fn() },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

const { toastError, toastSuccess } = vi.hoisted(() => ({
  toastError: vi.fn(), toastSuccess: vi.fn(),
}));
vi.mock("sonner", () => ({
  toast: Object.assign(
    (...args) => toastSuccess(...args),
    { success: toastSuccess, error: toastError },
  ),
}));

import AiRewriteButton from "@/components/ai/AiRewriteButton";


// ── Harness: a controlled parent that owns the text state so
//    we can simulate the real compose-field integration.
function Harness({ initial = "", onReplaceSpy = () => {} }) {
  const [v, setV] = React.useState(initial);
  return (
    <>
      <textarea
        data-testid="harness-textarea"
        value={v}
        onChange={(e) => setV(e.target.value)}
      />
      <AiRewriteButton
        value={v}
        onReplace={(next) => { setV(next); onReplaceSpy(next); }}
      />
    </>
  );
}


beforeEach(() => {
  apiPostMock.mockReset();
  toastError.mockReset();
  toastSuccess.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});


// ─── §1 · Min-length gate ────────────────────────────────────────
describe("Ticket LL · AiRewriteButton · min-length gate", () => {
  it("renders disabled below 10 chars with a tooltip", () => {
    render(<Harness initial="hi" />);
    const btn = screen.getByTestId("ai-rewrite-btn");
    expect(btn.disabled).toBe(true);
    expect(btn.title).toMatch(/at least 10 characters/i);
  });

  it("renders enabled at ≥10 chars", () => {
    render(<Harness initial="Hello there friend" />);
    const btn = screen.getByTestId("ai-rewrite-btn");
    expect(btn.disabled).toBe(false);
    expect(btn.title).toMatch(/professional tone/i);
  });

  it("treats whitespace-only text as below threshold", () => {
    render(<Harness initial="                    " />);
    const btn = screen.getByTestId("ai-rewrite-btn");
    expect(btn.disabled).toBe(true);
  });
});


// ─── §2–§4 · Happy path · rewrite + Undo ─────────────────────────
describe("Ticket LL · AiRewriteButton · happy path", () => {
  it("posts the trimmed draft and replaces field on success", async () => {
    apiPostMock.mockResolvedValue({ rewritten: "Hello, polished tone." });
    const spy = vi.fn();
    render(<Harness initial="  Hey can you confirm the appointment time  " onReplaceSpy={spy} />);
    fireEvent.click(screen.getByTestId("ai-rewrite-btn"));
    await waitFor(() => expect(apiPostMock).toHaveBeenCalled());
    expect(apiPostMock).toHaveBeenCalledWith("/ai/rewrite", {
      text: "Hey can you confirm the appointment time",
    });
    await waitFor(() => expect(spy).toHaveBeenCalledWith("Hello, polished tone."));
    // Field now shows the rewritten text, and the Undo button has
    // swapped in.
    expect(screen.getByTestId("harness-textarea").value)
      .toBe("Hello, polished tone.");
    expect(screen.getByTestId("ai-rewrite-btn-undo")).toBeTruthy();
  });

  it("Undo click restores the original text and hides Undo", async () => {
    apiPostMock.mockResolvedValue({ rewritten: "Rewritten version." });
    render(<Harness initial="Hey please confirm the time" />);
    fireEvent.click(screen.getByTestId("ai-rewrite-btn"));
    await waitFor(() => expect(screen.getByTestId("ai-rewrite-btn-undo")).toBeTruthy());
    fireEvent.click(screen.getByTestId("ai-rewrite-btn-undo"));
    expect(screen.getByTestId("harness-textarea").value)
      .toBe("Hey please confirm the time");
    expect(screen.queryByTestId("ai-rewrite-btn-undo")).toBeNull();
    expect(screen.getByTestId("ai-rewrite-btn")).toBeTruthy();
  });
});


// ─── §5 · Edit-during-Undo-window clears Undo early ──────────────
describe("Ticket LL · AiRewriteButton · edit clears Undo early", () => {
  it("clears Undo as soon as the operator types anything new", async () => {
    apiPostMock.mockResolvedValue({ rewritten: "Rewritten body." });
    render(<Harness initial="Hey please confirm the time" />);
    fireEvent.click(screen.getByTestId("ai-rewrite-btn"));
    await waitFor(() => expect(screen.getByTestId("ai-rewrite-btn-undo")).toBeTruthy());
    // Operator edits the rewritten output.
    fireEvent.change(screen.getByTestId("harness-textarea"),
                      { target: { value: "Rewritten body. Thanks!" } });
    // Undo gone, rewrite button back.
    await waitFor(() => expect(screen.queryByTestId("ai-rewrite-btn-undo")).toBeNull());
    expect(screen.getByTestId("ai-rewrite-btn")).toBeTruthy();
  });

  it("auto-expires Undo after 10 seconds if the operator didn't act", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    apiPostMock.mockResolvedValue({ rewritten: "Rewritten body." });
    render(<Harness initial="Hey please confirm the time" />);
    fireEvent.click(screen.getByTestId("ai-rewrite-btn"));
    await waitFor(() => expect(screen.getByTestId("ai-rewrite-btn-undo")).toBeTruthy());
    vi.advanceTimersByTime(10_000);
    await waitFor(() => expect(screen.queryByTestId("ai-rewrite-btn-undo")).toBeNull());
    expect(screen.getByTestId("ai-rewrite-btn")).toBeTruthy();
  });
});


// ─── §6-§9 · Error surfaces (via sonner toast) ───────────────────
describe("Ticket LL · AiRewriteButton · error surfaces", () => {
  it("surfaces REWRITE_COOLDOWN as a friendly toast", async () => {
    apiPostMock.mockRejectedValue({
      status: 429, data: { detail: { code: "REWRITE_COOLDOWN", retry_after_seconds: 1.2 } },
    });
    render(<Harness initial="Hey please confirm the time" />);
    fireEvent.click(screen.getByTestId("ai-rewrite-btn"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][0]).toMatch(/Slow down between rewrites/i);
    // Rewrite button is BACK (not stuck in rewriting state).
    expect(screen.getByTestId("ai-rewrite-btn")).toBeTruthy();
  });

  it("surfaces REWRITE_HOURLY_CAP as a hourly-limit toast", async () => {
    apiPostMock.mockRejectedValue({
      status: 429, data: { detail: { code: "REWRITE_HOURLY_CAP", retry_after_seconds: 1900 } },
    });
    render(<Harness initial="Hey please confirm the time" />);
    fireEvent.click(screen.getByTestId("ai-rewrite-btn"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][0]).toMatch(/hour's rewrite limit/i);
  });

  it("surfaces REWRITE_UPSTREAM_UNAVAILABLE as service-unavailable toast", async () => {
    apiPostMock.mockRejectedValue({
      status: 503, data: { detail: { code: "REWRITE_UPSTREAM_UNAVAILABLE" } },
    });
    render(<Harness initial="Hey please confirm the time" />);
    fireEvent.click(screen.getByTestId("ai-rewrite-btn"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][0]).toMatch(/service unavailable/i);
  });

  it("surfaces a generic 'Rewrite failed' toast on unknown error", async () => {
    apiPostMock.mockRejectedValue({ status: 500, data: {} });
    render(<Harness initial="Hey please confirm the time" />);
    fireEvent.click(screen.getByTestId("ai-rewrite-btn"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toastError.mock.calls[0][0]).toMatch(/Rewrite failed/i);
  });
});
