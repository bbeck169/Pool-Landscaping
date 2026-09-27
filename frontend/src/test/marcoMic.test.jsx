/**
 * Feb-2026 · MARCO Sub-phase C — mic dictation card tests.
 *
 * Locks the 4 contracts from the ruling:
 *   (a) Click toggles recording state — idle → recording testid flips.
 *   (b) MediaRecorder emits blob → mocked transcribe → auto-POST to
 *       MARCO's conversation endpoint with the correct payload shape.
 *   (c) Reply panel renders MARCO's returned message.
 *   (d) MARCO-not-seeded state disables the button + surfaces the
 *       error banner.
 *
 * Bonus:
 *   (e) Escape key while recording cancels + discards the audio
 *       (no transcribe / send call fires).
 *   (f) Conversation id is cached in localStorage across renders so
 *       repeat dictations don't spawn duplicate threads.
 */
import React from "react";
import { render, screen, waitFor, act, fireEvent, cleanup }
  from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// ── Mocks ──────────────────────────────────────────────────────────
const _apiCalls = { get: [], post: [] };
const _apiGetImpl = vi.fn();
const _apiPostImpl = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (p, timeoutMs) => {
      _apiCalls.get.push({ p, timeoutMs });
      return _apiGetImpl(p, timeoutMs);
    },
    post: (p, body) => {
      _apiCalls.post.push({ p, body });
      return _apiPostImpl(p, body);
    },
  },
  api_base: () => "http://localhost/api",
  TOKEN_KEY: "token",
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", onSurface: "#111", muted: "#888",
    border: "#ddd", surfaceSecondary: "#eee", brand: "#123456",
  },
  gradients: {
    navyToGreen: { css: "linear-gradient(#1B1F5C, #10B981)" },
  },
}));

vi.mock("lucide-react", () => ({
  Mic:      (p) => <span data-testid="icon-mic"       {...p}/>,
  MicOff:   (p) => <span data-testid="icon-mic-off"   {...p}/>,
  Send:     (p) => <span data-testid="icon-send"      {...p}/>,
  Sparkles: (p) => <span data-testid="icon-sparkles"  {...p}/>,
  X:        (p) => <span data-testid="icon-x"         {...p}/>,
}));

// ── MediaRecorder + getUserMedia stubs ─────────────────────────────
const _mrInstances = [];
class _StubMediaRecorder {
  constructor(stream) {
    this.stream = stream;
    this.state = "inactive";
    this.mimeType = "audio/webm";
    this.ondataavailable = null;
    this.onstop = null;
    _mrInstances.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    if (this.ondataavailable) {
      const blob = new Blob(["fake-audio-bytes"], { type: "audio/webm" });
      this.ondataavailable({ data: blob });
    }
    if (this.onstop) this.onstop();
  }
  static isTypeSupported() { return true; }
}

const _stubStream = {
  getTracks: () => [{ stop: () => {} }],
};

beforeEach(() => {
  _apiCalls.get.length = 0;
  _apiCalls.post.length = 0;
  _apiGetImpl.mockReset();
  _apiPostImpl.mockReset();
  _mrInstances.length = 0;

  // Fresh localStorage per test.
  localStorage.clear();
  localStorage.setItem("token", "test-jwt");

  // MediaRecorder + mic permission stubs.
  Object.defineProperty(window, "MediaRecorder", {
    value: _StubMediaRecorder,
    configurable: true, writable: true,
  });
  Object.defineProperty(navigator, "mediaDevices", {
    value: {
      getUserMedia: vi.fn().mockResolvedValue(_stubStream),
    },
    configurable: true, writable: true,
  });

  // fetch stub for /api/audio/transcribe.
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      transcript: "MARCO please have Casey audit the home page.",
      language: null,
      duration_sec: null,
      model: "whisper-1",
    }),
  });
});

afterEach(() => {
  cleanup();
});

// ── Test helpers ──────────────────────────────────────────────────
async function _loadAndRenderCard(userId = "admin-user-1") {
  const mod = await import("../pages/os/LanaAndPlans.jsx");
  const { MarcoVoiceCard } = mod;
  return render(<MarcoVoiceCard userId={userId}/>);
}

function _seedMarcoAvailable() {
  _apiGetImpl.mockImplementation(async (path) => {
    if (path === "/ai-employees") {
      return [
        { id: "casey-1", key: "casey", name: "Casey" },
        { id: "marco-1", key: "marco_executive",
          name: "MARCO: Executive Assistant AI",
          orchestrator: true },
      ];
    }
    return null;
  });
}

function _seedMarcoNotSeeded() {
  _apiGetImpl.mockImplementation(async (path) => {
    if (path === "/ai-employees") {
      return [
        { id: "casey-1", key: "casey", name: "Casey" },
      ];
    }
    return null;
  });
}

function _seedConversationAndReply() {
  _apiPostImpl.mockImplementation(async (path, body) => {
    if (path.endsWith("/conversations")) {
      return { id: "conv-marco-42",
                 participant_employee_ids: [body?.participant_employee_ids?.[0]] };
    }
    if (path.match(/\/messages$/)) {
      return {
        user: { text: body.text },
        assistant: { text: "Handing this off to Casey — she'll draft the audit." },
      };
    }
    return null;
  });
}

// ══════════════════════════════════════════════════════════════════
// (a) Click toggles recording state.
// ══════════════════════════════════════════════════════════════════
describe("MarcoVoiceCard · Sub-phase C", () => {
  it("(a) mic-button click toggles recording state (testid flips)",
      async () => {
    _seedMarcoAvailable();
    _seedConversationAndReply();
    await _loadAndRenderCard();

    // Wait for MARCO resolution.
    await waitFor(() => {
      expect(screen.getByTestId("marco-mic-button")).toBeTruthy();
    });

    const btn = screen.getByTestId("marco-mic-button");
    expect(btn.disabled).toBe(false);

    // Click → recording state.
    await act(async () => { fireEvent.click(btn); });
    await waitFor(() => {
      expect(screen.getByTestId("marco-mic-recording")).toBeTruthy();
    });
    expect(screen.getByTestId("marco-mic-timer")).toBeTruthy();

    // Click again → stop → transcribe → auto-send → replied.
    const stopBtn = screen.getByTestId("marco-mic-recording");
    await act(async () => { fireEvent.click(stopBtn); });

    await waitFor(() => {
      expect(screen.queryByTestId("marco-mic-recording")).toBeNull();
      expect(screen.getByTestId("marco-mic-button")).toBeTruthy();
    });
  });

  // ════════════════════════════════════════════════════════════════
  // (b) Blob → transcribe → auto-POST to MARCO conversation
  //     with the right payload shape.
  // ════════════════════════════════════════════════════════════════
  it("(b) records → transcribes → auto-POSTS transcript to MARCO",
      async () => {
    _seedMarcoAvailable();
    _seedConversationAndReply();
    await _loadAndRenderCard("admin-user-42");
    await waitFor(() =>
      expect(screen.getByTestId("marco-mic-button")).toBeTruthy());

    // Start + stop the recording.
    await act(async () => {
      fireEvent.click(screen.getByTestId("marco-mic-button"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("marco-mic-recording")).toBeTruthy());
    await act(async () => {
      fireEvent.click(screen.getByTestId("marco-mic-recording"));
    });

    // fetch was called against the audio-transcribe endpoint with a
    // FormData body carrying the audio file.
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toContain("/audio/transcribe");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.headers.Authorization).toBe("Bearer test-jwt");

    // Auto-POST fired against MARCO's conversation with the
    // transcript verbatim.  Order: (1) create conversation,
    // (2) POST message.
    await waitFor(() =>
      expect(_apiCalls.post.length).toBeGreaterThanOrEqual(2));
    const [convCreate, msgPost] = _apiCalls.post;
    expect(convCreate.p).toBe("/ai-employees/marco-1/conversations");
    expect(convCreate.body.participant_employee_ids).toEqual(["marco-1"]);
    expect(msgPost.p)
      .toBe("/ai-employees/marco-1/conversations/conv-marco-42/messages");
    expect(msgPost.body.text)
      .toBe("MARCO please have Casey audit the home page.");
    // Feb-2026 · Sub-phase D — mic path stamps source_channel="voice"
    // so ``create_admin_todo`` correctly attributes ``created_via``.
    expect(msgPost.body.source_channel).toBe("voice");
  });

  // ════════════════════════════════════════════════════════════════
  // (c) Reply panel renders MARCO's returned assistant message.
  // ════════════════════════════════════════════════════════════════
  it("(c) reply panel renders MARCO's returned message", async () => {
    _seedMarcoAvailable();
    _seedConversationAndReply();
    await _loadAndRenderCard();

    await waitFor(() =>
      expect(screen.getByTestId("marco-mic-button")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByTestId("marco-mic-button"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("marco-mic-recording")).toBeTruthy());
    await act(async () => {
      fireEvent.click(screen.getByTestId("marco-mic-recording"));
    });

    await waitFor(() => {
      const panel = screen.getByTestId("marco-reply-panel");
      const msg = screen.getByTestId("marco-reply-message");
      expect(panel).toBeTruthy();
      expect(msg.textContent).toContain("Casey");
    });
  });

  // ════════════════════════════════════════════════════════════════
  // (d) MARCO-not-seeded — button disabled + error banner surfaced.
  // ════════════════════════════════════════════════════════════════
  it("(d) disables mic + shows banner when MARCO isn't seeded",
      async () => {
    _seedMarcoNotSeeded();
    await _loadAndRenderCard();

    // Wait for the lookup to complete + the not-seeded banner to
    // appear.
    await waitFor(() => {
      expect(screen.getByTestId("marco-mic-error")).toBeTruthy();
    });
    const btn = screen.getByTestId("marco-mic-button");
    expect(btn.disabled).toBe(true);
    expect(btn.title).toMatch(/MARCO not available/i);

    // Clicking a disabled button does not start recording.
    await act(async () => { fireEvent.click(btn); });
    expect(screen.queryByTestId("marco-mic-recording")).toBeNull();
  });

  // ════════════════════════════════════════════════════════════════
  // (e) Escape key while recording cancels the recording (no
  //     transcribe / send calls fire).
  // ════════════════════════════════════════════════════════════════
  it("(e) Escape while recording cancels + discards the audio",
      async () => {
    _seedMarcoAvailable();
    _seedConversationAndReply();
    await _loadAndRenderCard();

    await waitFor(() =>
      expect(screen.getByTestId("marco-mic-button")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByTestId("marco-mic-button"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("marco-mic-recording")).toBeTruthy());

    // Fire Escape.
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });

    await waitFor(() => {
      expect(screen.queryByTestId("marco-mic-recording")).toBeNull();
      expect(screen.getByTestId("marco-mic-button")).toBeTruthy();
    });
    // No transcribe / conversation calls fired.
    expect(global.fetch).not.toHaveBeenCalled();
    expect(_apiCalls.post.length).toBe(0);
  });

  // ════════════════════════════════════════════════════════════════
  // (f) Conversation id cached in localStorage across dictations.
  // ════════════════════════════════════════════════════════════════
  it("(f) caches MARCO conversation id in localStorage across sessions",
      async () => {
    _seedMarcoAvailable();
    _seedConversationAndReply();
    await _loadAndRenderCard("admin-user-99");

    await waitFor(() =>
      expect(screen.getByTestId("marco-mic-button")).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByTestId("marco-mic-button"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("marco-mic-recording")).toBeTruthy());
    await act(async () => {
      fireEvent.click(screen.getByTestId("marco-mic-recording"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("marco-reply-panel")).toBeTruthy());

    // Cache written.
    expect(localStorage.getItem("marco_conversation:admin-user-99"))
      .toBe("conv-marco-42");

    // A second dictation reuses the cached id — no new create call.
    _apiCalls.post.length = 0;
    await act(async () => {
      fireEvent.click(screen.getByTestId("marco-mic-button"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("marco-mic-recording")).toBeTruthy());
    await act(async () => {
      fireEvent.click(screen.getByTestId("marco-mic-recording"));
    });
    await waitFor(() =>
      expect(_apiCalls.post.length).toBeGreaterThanOrEqual(1));

    // Exactly ONE call this round: message POST (no create).
    const createCalls = _apiCalls.post.filter(
      c => c.p.endsWith("/conversations"),
    );
    expect(createCalls.length).toBe(0);
  });
});
