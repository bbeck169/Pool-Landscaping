/**
 * Phase 8 · Feb-2026 — Marco wake-word arm-on-click contract.
 *
 * 11 brief cases covering:
 *   1  No auto-start on mount
 *   2  Toggle flips isArmed true → false → true
 *   3  Armed state renders pulse ring + aria-pressed=true
 *   4  Disarmed state renders muted icon + aria-pressed=false
 *   5  Toast on arm
 *   6  Toast on disarm
 *   7  10-min idle expiry → auto-disarm + auto-disarm toast
 *   8  Wake-word detection resets the idle timer
 *   9  beforeunload disarms (phantom-armed-after-reload lock)
 *  10  No audio API calls — no new Audio, no AudioContext,
 *      no OscillatorNode during any arm / disarm / detect flow
 *  11  Role gate — non-Marco roles see nothing (no widening)
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, act, cleanup, fireEvent, waitFor,
} from "@testing-library/react";


// ─── Mocks ────────────────────────────────────────────────────────

const { toastSuccess, toastInfo, toastMessage, toastError } = vi.hoisted(
  () => ({
    toastSuccess: vi.fn(),
    toastInfo:    vi.fn(),
    toastMessage: vi.fn(),
    toastError:   vi.fn(),
  }),
);

vi.mock("sonner", () => ({
  toast: {
    success: toastSuccess,
    info:    toastInfo,
    message: toastMessage,
    error:   toastError,
  },
}));


// Stub a controllable SpeechRecognition.  The mock remembers the
// most recent instance so a test can emit a phrase + inspect the
// recogniser's lifecycle.
let _lastRecognition = null;
let _constructedCount = 0;


function _installSpeechRecognition() {
  _lastRecognition = null;
  _constructedCount = 0;

  class FakeSpeechRecognition {
    constructor() {
      _constructedCount += 1;
      this.continuous      = false;
      this.interimResults  = false;
      this.lang            = "";
      this.maxAlternatives = 1;
      this.onresult        = null;
      this.onerror         = null;
      this.onend           = null;
      this._started        = false;
      _lastRecognition     = this;
    }

    start() { this._started = true; }
    stop()  {
      this._started = false;
      if (typeof this.onend === "function") this.onend();
    }

    // Test helper: feed a transcript as a recognition result event.
    emit(transcript) {
      if (!this.onresult) return;
      this.onresult({
        resultIndex: 0,
        results: [[
          { transcript, confidence: 0.9 },
        ].concat({ isFinal: false, length: 1 })],
      });
    }
  }

  Object.defineProperty(window, "SpeechRecognition", {
    configurable: true,
    writable:     true,
    value:        FakeSpeechRecognition,
  });
}


function _uninstallSpeechRecognition() {
  try { delete window.SpeechRecognition;        } catch (_e) {}
  try { delete window.webkitSpeechRecognition;  } catch (_e) {}
  _lastRecognition = null;
  _constructedCount = 0;
}


// Audio sentinels — assert nothing in the wake-word code path
// touches new Audio / AudioContext.  We spy via constructor
// patching; a single construct ⇒ test failure.
let _audioCtorCount = 0;
let _audioContextCtorCount = 0;
let _oscillatorCtorCount = 0;
const _OrigAudio        = globalThis.Audio;
const _OrigAudioContext = globalThis.AudioContext;
const _OrigOscillator   = globalThis.OscillatorNode;


function _installAudioSpies() {
  _audioCtorCount = 0;
  _audioContextCtorCount = 0;
  _oscillatorCtorCount = 0;
  globalThis.Audio = function AudioSpy() {
    _audioCtorCount += 1;
    return {};
  };
  globalThis.AudioContext = function AudioContextSpy() {
    _audioContextCtorCount += 1;
    return { close: () => {} };
  };
  globalThis.OscillatorNode = function OscillatorSpy() {
    _oscillatorCtorCount += 1;
    return {};
  };
}


function _uninstallAudioSpies() {
  globalThis.Audio          = _OrigAudio;
  globalThis.AudioContext   = _OrigAudioContext;
  globalThis.OscillatorNode = _OrigOscillator;
}


beforeEach(() => {
  _installSpeechRecognition();
  _installAudioSpies();
  vi.useFakeTimers();
});


afterEach(() => {
  // Flush any pending timers so a provider timeout doesn't bleed
  // into the next test.
  try { vi.runOnlyPendingTimers(); } catch (_e) { /* noop */ }
  vi.useRealTimers();
  cleanup();
  _uninstallSpeechRecognition();
  _uninstallAudioSpies();
  vi.clearAllMocks();
});


// ─── Helpers ──────────────────────────────────────────────────────

async function _mountProvider(role = "admin") {
  const { MarcoMicProvider, MicToggleButton } = await import(
    "@/components/marco/MarcoMicController");
  const utils = render(
    <MarcoMicProvider user={{ role }}>
      <MicToggleButton />
    </MarcoMicProvider>,
  );
  return { utils, MicToggleButton };
}


// ══════════════════════════════════════════════════════════════════
//  Case 1 — No auto-start on mount
// ══════════════════════════════════════════════════════════════════

describe("Case 1 · no auto-start on mount", () => {
  it("mounting the provider does NOT construct SpeechRecognition",
    async () => {
      await _mountProvider("admin");
      expect(_constructedCount).toBe(0);
      expect(_lastRecognition).toBeNull();
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 2 + 3 + 4 — Toggle + visual states
// ══════════════════════════════════════════════════════════════════

describe("Case 2+3+4 · toggle + visual state", () => {
  it("toggle flips isArmed true → false → true + aria-pressed tracks",
    async () => {
      await _mountProvider("admin");
      const btn = screen.getByTestId("marco-mic-toggle-btn");
      expect(btn.getAttribute("aria-pressed")).toBe("false");
      expect(btn.getAttribute("data-armed")).toBe("false");
      // Disarmed → muted icon rendered.
      expect(screen.getByTestId("marco-mic-icon-disarmed")).toBeTruthy();

      await act(async () => { fireEvent.click(btn); });
      expect(btn.getAttribute("aria-pressed")).toBe("true");
      expect(btn.getAttribute("data-armed")).toBe("true");
      // Armed → pulse ring + mic icon rendered.
      expect(screen.getByTestId("marco-mic-icon-armed")).toBeTruthy();
      expect(screen.getByTestId("marco-mic-pulse-ring")).toBeTruthy();

      await act(async () => { fireEvent.click(btn); });
      expect(btn.getAttribute("aria-pressed")).toBe("false");

      await act(async () => { fireEvent.click(btn); });
      expect(btn.getAttribute("aria-pressed")).toBe("true");
    });

  it("armed label describes the DISARM action; disarmed label the ARM",
    async () => {
      await _mountProvider("admin");
      const btn = screen.getByTestId("marco-mic-toggle-btn");
      expect(btn.getAttribute("aria-label")).toBe("Arm Marco wake-word");

      await act(async () => { fireEvent.click(btn); });
      expect(btn.getAttribute("aria-label")).toBe("Disarm Marco wake-word");
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 5 + 6 — Toasts on arm / disarm
// ══════════════════════════════════════════════════════════════════

describe("Case 5+6 · toasts on arm / disarm", () => {
  it("Case 5 · armed → sonner success toast with the exact copy",
    async () => {
      await _mountProvider("admin");
      await act(async () => {
        fireEvent.click(screen.getByTestId("marco-mic-toggle-btn"));
      });
      expect(toastSuccess).toHaveBeenCalledWith(
        "Marco wake-word armed", expect.any(Object),
      );
    });

  it("Case 6 · disarmed → sonner message toast with the exact copy",
    async () => {
      await _mountProvider("admin");
      const btn = screen.getByTestId("marco-mic-toggle-btn");
      await act(async () => { fireEvent.click(btn); });   // arm
      await act(async () => { fireEvent.click(btn); });   // disarm
      expect(toastMessage).toHaveBeenCalledWith(
        "Marco wake-word disarmed", expect.any(Object),
      );
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 7 + 8 — 10-min idle auto-disarm + reset-on-detect
// ══════════════════════════════════════════════════════════════════

describe("Case 7+8 · idle auto-disarm", () => {
  it("Case 7 · fires auto-disarm toast after exactly 10 minutes idle",
    async () => {
      await _mountProvider("admin");
      await act(async () => {
        fireEvent.click(screen.getByTestId("marco-mic-toggle-btn"));
      });

      // Not quite 10 min — nothing fires.
      await act(async () => { vi.advanceTimersByTime(9 * 60 * 1000); });
      expect(toastInfo).not.toHaveBeenCalled();
      expect(screen.getByTestId("marco-mic-toggle-btn")
        .getAttribute("aria-pressed")).toBe("true");

      // Cross the 10-min threshold.
      await act(async () => { vi.advanceTimersByTime(2 * 60 * 1000); });
      // Allow any state-flush microtasks to resolve inside act.
      await act(async () => { await Promise.resolve(); });
      expect(toastInfo).toHaveBeenCalledWith(
        "Marco wake-word auto-disarmed (10 min idle)",
        expect.any(Object),
      );
      expect(screen.getByTestId("marco-mic-toggle-btn")
        .getAttribute("aria-pressed")).toBe("false");
    });

  it("Case 8 · wake-word detection resets the idle timer",
    async () => {
      await _mountProvider("admin");
      await act(async () => {
        fireEvent.click(screen.getByTestId("marco-mic-toggle-btn"));
      });

      // 9 min pass — detection happens — timer resets.
      await act(async () => { vi.advanceTimersByTime(9 * 60 * 1000); });
      await act(async () => {
        _lastRecognition.emit("hey marco what is the weather");
      });

      // Another 9 min — still not expired because the detection
      // reset the countdown.
      await act(async () => { vi.advanceTimersByTime(9 * 60 * 1000); });
      expect(toastInfo).not.toHaveBeenCalled();
      expect(screen.getByTestId("marco-mic-toggle-btn")
        .getAttribute("aria-pressed")).toBe("true");

      // Cross from the post-detect reset point.
      await act(async () => { vi.advanceTimersByTime(2 * 60 * 1000); });
      expect(toastInfo).toHaveBeenCalled();
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 9 — beforeunload disarms
// ══════════════════════════════════════════════════════════════════

describe("Case 9 · beforeunload disarms", () => {
  it("fires the hook's disarm path on page unload (no phantom armed state)",
    async () => {
      await _mountProvider("admin");
      await act(async () => {
        fireEvent.click(screen.getByTestId("marco-mic-toggle-btn"));
      });
      // Confirm armed first so the beforeunload has something to tear down.
      expect(screen.getByTestId("marco-mic-toggle-btn")
        .getAttribute("aria-pressed")).toBe("true");
      // Recognition instance exists while armed.
      expect(_lastRecognition).toBeTruthy();
      const rec = _lastRecognition;

      await act(async () => {
        window.dispatchEvent(new Event("beforeunload"));
      });

      // Hook's stop() nulled onresult/onerror/onend AND called
      // rec.stop().  Our fake flips _started=false on stop() so
      // assert that.
      expect(rec._started).toBe(false);
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 10 — No audio API calls in the wake-word path
// ══════════════════════════════════════════════════════════════════

describe("Case 10 · zero audible feedback", () => {
  it("arm + detect + disarm never construct Audio / AudioContext / Oscillator",
    async () => {
      await _mountProvider("admin");

      await act(async () => {
        fireEvent.click(screen.getByTestId("marco-mic-toggle-btn"));
      });
      await act(async () => {
        _lastRecognition.emit("hey marco check the dashboard");
      });
      await act(async () => {
        fireEvent.click(screen.getByTestId("marco-mic-toggle-btn"));
      });

      expect(_audioCtorCount).toBe(0);
      expect(_audioContextCtorCount).toBe(0);
      expect(_oscillatorCtorCount).toBe(0);
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 11 — Role gate (no widening)
// ══════════════════════════════════════════════════════════════════

describe("Case 11 · role gate preserves pre-Phase-8 Marco scope", () => {
  it("admin sees the mic button", async () => {
    await _mountProvider("admin");
    expect(screen.getByTestId("marco-mic-toggle-btn")).toBeTruthy();
  });

  it("super_admin sees it", async () => {
    await _mountProvider("super_admin");
    expect(screen.getByTestId("marco-mic-toggle-btn")).toBeTruthy();
  });

  it("manager sees it", async () => {
    await _mountProvider("manager");
    expect(screen.getByTestId("marco-mic-toggle-btn")).toBeTruthy();
  });

  it("owner sees it", async () => {
    await _mountProvider("owner");
    expect(screen.getByTestId("marco-mic-toggle-btn")).toBeTruthy();
  });

  it("technician does NOT see it (regression lock on no widening)",
    async () => {
      await _mountProvider("technician");
      expect(screen.queryByTestId("marco-mic-toggle-btn")).toBeNull();
    });

  it("customer does NOT see it", async () => {
    await _mountProvider("customer");
    expect(screen.queryByTestId("marco-mic-toggle-btn")).toBeNull();
  });

  it("customer_portal does NOT see it", async () => {
    await _mountProvider("customer_portal");
    expect(screen.queryByTestId("marco-mic-toggle-btn")).toBeNull();
  });

  it("hides on Firefox / Safari <14.5 (no SpeechRecognition)",
    async () => {
      _uninstallSpeechRecognition();
      await _mountProvider("admin");
      expect(screen.queryByTestId("marco-mic-toggle-btn")).toBeNull();
    });
});
