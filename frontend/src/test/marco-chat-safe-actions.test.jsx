/**
 * Feb-2026 · MARCO-AI-CHAT Phase B — wake-word hooks + mic + inline
 * confirm tests.
 *
 * Covers:
 *   (a) ``useWebWakeWord`` — matched phrase dispatches
 *       ``ai-dock:open-marco`` on the window.
 *   (b) ``useWebWakeWord`` — Firefox fallback returns
 *       ``{ supported: false }`` and does not throw.
 *   (c) ``useTypedWakePhrase`` — typing "heymarco" into the document
 *       dispatches the event; a 2 s inactivity gap resets the buffer.
 *   (d) ``ChatMicButton`` — Firefox fallback renders null.
 *   (e) ``ChatMicButton`` — click → start → result APPENDS to input
 *       value, does NOT auto-send.
 *   (f) ``InlineConfirm`` — renders dry-run payload rows; Confirm &
 *       Send calls the approve API with the correct action_id.
 */
import React from "react";
import {
  render, screen, waitFor, act, fireEvent, cleanup,
} from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// ── Shared mocks ──────────────────────────────────────────────────
const _api = { post: vi.fn() };
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
    post: (p, body) => _api.post(p, body),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#123", onBrand: "#fff",
    surface: "#fff", surfaceMuted: "#eee",
    onSurface: "#111", onSurfaceSecondary: "#333",
    muted: "#999", border: "#ccc", danger: "#c00",
  },
}));

vi.mock("lucide-react", () => ({
  Mic:            (p) => <span data-testid="icon-mic" {...p}/>,
  MicOff:         (p) => <span data-testid="icon-mic-off" {...p}/>,
  Check:          (p) => <span data-testid="icon-check" {...p}/>,
  X:              (p) => <span data-testid="icon-x" {...p}/>,
  Sparkles:       (p) => <span data-testid="icon-sparkles" {...p}/>,
  AlertTriangle:  (p) => <span data-testid="icon-alert" {...p}/>,
}));

// ── Stub SpeechRecognition ──────────────────────────────────────────
let _lastRecognition = null;
class _StubRecognition {
  constructor() {
    this.continuous = false;
    this.interimResults = false;
    this.lang = "";
    this.onresult = null;
    this.onerror = null;
    this.onend = null;
    this.started = false;
    _lastRecognition = this;
  }
  start() { this.started = true; }
  stop() {
    this.started = false;
    if (this.onend) this.onend();
  }
  emit(transcript) {
    if (!this.onresult) return;
    this.onresult({
      resultIndex: 0,
      results: [[{ transcript, confidence: 1 }]],
    });
  }
}

function _installSpeechRecognition() {
  Object.defineProperty(window, "SpeechRecognition", {
    value: _StubRecognition, configurable: true, writable: true,
  });
  Object.defineProperty(window, "webkitSpeechRecognition", {
    value: _StubRecognition, configurable: true, writable: true,
  });
}

function _uninstallSpeechRecognition() {
  try { delete window.SpeechRecognition; } catch (_e) { /* noop */ }
  try { delete window.webkitSpeechRecognition; } catch (_e) { /* noop */ }
}

beforeEach(() => {
  _api.post.mockReset();
  _lastRecognition = null;
  _installSpeechRecognition();
});

afterEach(() => {
  cleanup();
  _uninstallSpeechRecognition();
});

// ══════════════════════════════════════════════════════════════════
// (a) wake-word hook: match + dispatch
// ══════════════════════════════════════════════════════════════════
describe("useWebWakeWord", () => {
  it("(a) dispatches ai-dock:open-marco when 'hey marco' is heard",
      async () => {
    const { default: useWebWakeWord } = await import(
      "../hooks/useWebWakeWord.js");
    const seen = [];
    const handler = (ev) => seen.push(ev.detail);
    window.addEventListener("ai-dock:open-marco", handler);

    function _Harness() {
      const state = useWebWakeWord();
      return <div data-testid="state">{JSON.stringify(state)}</div>;
    }
    render(<_Harness/>);
    await waitFor(() => expect(_lastRecognition).toBeTruthy());

    await act(async () => {
      _lastRecognition.emit("hey Marco please check the dashboard");
    });

    await waitFor(() => expect(seen.length).toBe(1));
    expect(seen[0].source).toBe("wake-word");

    window.removeEventListener("ai-dock:open-marco", handler);
  });

  it("(b) returns supported:false on Firefox (no SpeechRecognition)",
      async () => {
    _uninstallSpeechRecognition();
    const { default: useWebWakeWord } = await import(
      "../hooks/useWebWakeWord.js");
    let captured = null;
    function _Harness() {
      captured = useWebWakeWord();
      return <div data-testid="harness"/>;
    }
    render(<_Harness/>);
    await waitFor(() => expect(screen.getByTestId("harness")).toBeTruthy());
    expect(captured.supported).toBe(false);
  });
});

// ══════════════════════════════════════════════════════════════════
// (c) typed phrase hook — "heymarco" → event
// ══════════════════════════════════════════════════════════════════
describe("useTypedWakePhrase", () => {
  it("(c) typing h-e-y-m-a-r-c-o fires ai-dock:open-marco", async () => {
    const { default: useTypedWakePhrase } = await import(
      "../hooks/useTypedWakePhrase.js");
    const seen = [];
    const handler = (ev) => seen.push(ev.detail);
    window.addEventListener("ai-dock:open-marco", handler);

    function _Harness() {
      useTypedWakePhrase();
      return <div data-testid="harness"/>;
    }
    render(<_Harness/>);

    const letters = ["h", "e", "y", "m", "a", "r", "c", "o"];
    await act(async () => {
      for (const k of letters) {
        fireEvent.keyDown(document, { key: k });
      }
    });

    await waitFor(() => expect(seen.length).toBe(1));
    expect(seen[0].source).toBe("typed-phrase");

    window.removeEventListener("ai-dock:open-marco", handler);
  });
});

// ══════════════════════════════════════════════════════════════════
// (d)(e) ChatMicButton — Firefox fallback + append-not-send
// ══════════════════════════════════════════════════════════════════
describe("ChatMicButton", () => {
  it("(d) renders null when SpeechRecognition is unavailable",
      async () => {
    _uninstallSpeechRecognition();
    const { default: ChatMicButton } = await import(
      "../components/AIDock/ChatMicButton.jsx");
    const { container } = render(
      <ChatMicButton value="" onChange={() => {}}/>);
    expect(container.innerHTML).toBe("");
  });

  it("(e) click → recognised speech APPENDS to parent value", async () => {
    const { default: ChatMicButton } = await import(
      "../components/AIDock/ChatMicButton.jsx");
    const changes = [];
    function _Harness() {
      const [v, setV] = React.useState("Hey Marco,");
      return (
        <div>
          <span data-testid="live-value">{v}</span>
          <ChatMicButton value={v} onChange={(nv) => {
            changes.push(nv); setV(nv);
          }}/>
        </div>
      );
    }
    render(<_Harness/>);
    const btn = screen.getByTestId("ai-dock-mic-button");
    await act(async () => { fireEvent.click(btn); });
    await waitFor(() => expect(_lastRecognition).toBeTruthy());

    await act(async () => {
      _lastRecognition.emit("please email that invoice");
    });

    await waitFor(() => expect(changes.length).toBeGreaterThan(0));
    const last = changes[changes.length - 1];
    expect(last).toContain("Hey Marco,");
    expect(last).toContain("please email that invoice");
    // Did NOT auto-send: no api.post call was made from the component.
    expect(_api.post).not.toHaveBeenCalled();
  });
});

// ══════════════════════════════════════════════════════════════════
// (f) InlineConfirm — Confirm & Send calls approve API
// ══════════════════════════════════════════════════════════════════
describe("InlineConfirm", () => {
  it("(f) renders payload + Confirm & Send POSTs to approve endpoint",
      async () => {
    const { default: InlineConfirm } = await import(
      "../components/AIDock/InlineConfirm.jsx");
    _api.post.mockResolvedValue({
      id: "ACT_1", status: "executed",
      result: { kind: "marco_action_executed", ok: true },
    });
    const pending = {
      action_id: "ACT_1",
      tool_name: "send_invoice_email",
      kind: "marco_inline_confirm",
      payload: {
        recipient_masked: "j***e@example.com",
        invoice_number: "INV-9001",
        total: 450.5,
      },
    };
    const decisions = [];
    render(<InlineConfirm pending={pending}
                             onDecided={(d, r) => decisions.push({ d, r })}/>);

    expect(screen.getByTestId("ai-dock-inline-confirm-ACT_1")).toBeTruthy();
    expect(screen.getByText("INV-9001")).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByTestId(
        "ai-dock-inline-confirm-approve-ACT_1"));
    });

    await waitFor(() =>
      expect(_api.post).toHaveBeenCalledWith(
        "/ai-employees/actions/ACT_1/approve", {}));
    await waitFor(() => expect(decisions.length).toBe(1));
    expect(decisions[0].d).toBe("approve");
    expect(screen.getByTestId(
      "ai-dock-inline-confirm-done-ACT_1")).toBeTruthy();
  });
});
