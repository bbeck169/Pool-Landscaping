/**
 * K36 · Diagnostic ring-buffer.
 *
 * The buffer keeps the last 20 nav + last 20 API entries and writes
 * through to AsyncStorage. Tests use the in-memory AsyncStorage mock
 * that ships with jest-expo.
 */
jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);

import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  logNav,
  logApi,
  getDiagnostics,
  clearDiagnostics,
  persistCrash,
  consumePendingCrash,
  formatDiagnostics,
} from "@/src/utils/diagnostics";

describe("diagnostics ring-buffer", () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
    await clearDiagnostics();
  });

  it("logNav is capped at 20 entries", async () => {
    for (let i = 0; i < 25; i++) logNav(`route-${i}`);
    // Small wait to let the async setItem drain — but getDiagnostics
    // reads the in-memory buffer, so it's already the source of truth.
    const snap = await getDiagnostics();
    expect(snap.nav.length).toBe(20);
    expect(snap.nav[0].route).toBe("route-5");
    expect(snap.nav[19].route).toBe("route-24");
  });

  it("logApi is capped at 20 entries with normalized shape", async () => {
    for (let i = 0; i < 22; i++) {
      logApi({ method: "GET", path: `/x/${i}`, status: 200, ms: 10 });
    }
    const snap = await getDiagnostics();
    expect(snap.api.length).toBe(20);
    expect(snap.api[0].path).toBe("/x/2");
    expect(snap.api[19].path).toBe("/x/21");
    expect(snap.api[19].status).toBe(200);
  });

  it("persistCrash / consumePendingCrash round-trip", async () => {
    persistCrash(new Error("boom"), "in Foo\nin Bar");
    // Give AsyncStorage.setItem a tick.
    await new Promise((r) => setTimeout(r, 5));
    const c = await consumePendingCrash();
    expect(c).not.toBeNull();
    expect(c!.message).toBe("boom");
    expect(c!.componentStack).toContain("in Foo");
    // Second call returns null (slot consumed).
    const c2 = await consumePendingCrash();
    expect(c2).toBeNull();
  });

  it("clearDiagnostics empties everything", async () => {
    logNav("a");
    logApi({ method: "GET", path: "/b", status: 200 });
    persistCrash(new Error("c"));
    await new Promise((r) => setTimeout(r, 5));
    await clearDiagnostics();
    const snap = await getDiagnostics();
    expect(snap.nav.length).toBe(0);
    expect(snap.api.length).toBe(0);
    expect(snap.lastCrash).toBeNull();
  });

  it("formatDiagnostics produces a shareable multiline string", async () => {
    logNav("schedule/calendar.focus", { role: "technician" });
    logApi({ method: "GET", path: "/jobs?start=x", status: 200, ms: 123 });
    const snap = await getDiagnostics();
    const out = formatDiagnostics(snap);
    expect(out).toContain("Pool Landscaping");
    expect(out).toContain("schedule/calendar.focus");
    expect(out).toContain("GET /jobs?start=x");
    expect(out).toContain("200");
  });
});
