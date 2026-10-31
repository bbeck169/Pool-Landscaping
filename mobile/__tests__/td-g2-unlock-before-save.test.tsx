/**
 * TD-g2 · mobile K6 unlock-before-save (web β 1eff40b8a parity).
 * Lib orchestration + reason modal (rendered) + checklist.tsx source locks.
 * The full checklist screen is not rendered (precedent: job-k6-unlock,
 * k61-checklist-contract use source-level assertions).
 */
import * as fs from "fs";
import * as path from "path";
import React from "react";
import { render, fireEvent } from "@testing-library/react-native";

const mockPost = jest.fn();
const mockGet = jest.fn();
jest.mock("@/src/api", () => {
  class ApiError extends Error {
    status: number; detail: unknown;
    constructor(m: string, s: number, d: unknown) { super(m); this.status = s; this.detail = d; }
  }
  return { api: { post: (...a: any[]) => mockPost(...a), get: (...a: any[]) => mockGet(...a) }, ApiError };
});
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("@/src/theme", () => ({
  colors: { brand: "#0284C7", surface: "#fff", border: "#ddd", error: "#DC2626", muted: "#999", onSurface: "#111" },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32 },
  radius: { md: 8, lg: 12 },
  font: { regular: "r", semibold: "s", bold: "b" },
  fontSize: { sm: 12, base: 14, lg: 16 },
}));

// eslint-disable-next-line import/first
import { ApiError } from "@/src/api";
// eslint-disable-next-line import/first
import {
  UNLOCK_ADMIN_ROLES, submittedSaveMode, isValidUnlockReason, saveWithUnlock,
  unlockSubmittedJob, mergeUnlockedReport, reclassifyAfterSave, UNLOCK_OFFLINE_MESSAGE, UNLOCK_REFETCH_FAILED_MESSAGE,
  type FlushSaveResult,
} from "@/src/lib/submittedReportUnlock";
// eslint-disable-next-line import/first
import UnlockReasonModal from "@/src/components/checklist/UnlockReasonModal";

const SRC = fs.readFileSync(path.resolve(__dirname, "../app/job/[id]/checklist.tsx"), "utf-8");
const AE: any = ApiError;

function harness(opts: { first: FlushSaveResult; reason?: string | null; unlockErr?: any; fresh?: any; online?: boolean }) {
  const calls: string[] = [];
  const flush = jest.fn(async () => {
    calls.push("flush");
    return calls.filter((c) => c === "flush").length === 1 ? opts.first : { ok: true };
  });
  const requestReason = jest.fn(async () => { calls.push("prompt"); return opts.reason === undefined ? "Fixing wrong FC reading" : opts.reason; });
  const unlock = jest.fn(async (_r: string) => { calls.push("unlock"); if (opts.unlockErr) throw opts.unlockErr; return { ok: true }; });
  const refetch = jest.fn(async () => { calls.push("refetch"); return opts.fresh === undefined ? { id: "sr1", notes: "srv" } : opts.fresh; });
  const applyUnlocked = jest.fn(() => { calls.push("apply"); });
  const run = () => saveWithUnlock({ flush, online: opts.online ?? true, requestReason, unlock, refetch, applyUnlocked });
  return { calls, flush, requestReason, unlock, refetch, applyUnlocked, run };
}

describe("TD-g2 · role split (D1a)", () => {
  it("unlock admin set = BE jobs.py:4331 / web JobUnlockButton (no dispatcher)", () => {
    expect([...UNLOCK_ADMIN_ROLES].sort()).toEqual(["admin", "manager", "owner", "super_admin"]);
  });
  it("submitted report → technician bypass / admin unlock / others read-only", () => {
    const sub = { submitted_at: "2026-10-01T00:00:00Z" };
    expect(submittedSaveMode("technician", sub)).toBe("tech-bypass");
    for (const r of ["admin", "super_admin", "manager", "owner"]) expect(submittedSaveMode(r, sub)).toBe("needs-unlock");
    for (const r of ["dispatcher", "customer", "tech", "employee", ""]) expect(submittedSaveMode(r, sub)).toBe("read-only");
    expect(submittedSaveMode("admin", { submitted_at: null })).toBe("open");
    expect(submittedSaveMode("technician", {})).toBe("open");
  });
  it("reason ≥ 8 chars after trim", () => {
    expect(isValidUnlockReason("1234567")).toBe(false);
    expect(isValidUnlockReason("   1234567   ")).toBe(false);
    expect(isValidUnlockReason("12345678")).toBe(true);
    expect(isValidUnlockReason(null)).toBe(false);
  });
});

describe("TD-g2 · saveWithUnlock orchestration", () => {
  it("admin: prompt → unlock(reason) → refetch → apply → PATCH flush, in order", async () => {
    const h = harness({ first: { ok: false, needsUnlock: true } });
    const res = await h.run();
    expect(h.calls).toEqual(["flush", "prompt", "unlock", "refetch", "apply", "flush"]);
    expect(h.unlock).toHaveBeenCalledWith("Fixing wrong FC reading");
    expect(res).toEqual({ ok: true });
  });
  it("admin cancels → no unlock, no second flush, cancelled (caller shows no toast)", async () => {
    const h = harness({ first: { ok: false, needsUnlock: true }, reason: null });
    const res = await h.run();
    expect(h.calls).toEqual(["flush", "prompt"]);
    expect(res).toEqual({ ok: false, cancelled: true });
  });
  it.each([
    [new AE("Forbidden", 403, "Only admin roles can unlock submitted jobs"), "You don't have permission to unlock this report."],
    [new AE("Server", 500, null), "The server couldn't unlock this report. Try again in a moment."],
    [new AE("Bad", 400, { detail: "reason_too_short", message: "Reason must be at least 8 characters" }), "Reason must be at least 8 characters"],
    [new TypeError("Network request failed"), "Couldn't reach the server to unlock this report. Check your connection and try again."],
  ])("unlock failure %#: error surfaced, save aborted", async (err, msg) => {
    const h = harness({ first: { ok: false, needsUnlock: true }, unlockErr: err });
    const res = await h.run();
    expect(h.calls).toEqual(["flush", "prompt", "unlock"]);
    expect(res).toEqual({ ok: false, error: msg });
  });
  it("offline → no prompt, no unlock queued, network message", async () => {
    const h = harness({ first: { ok: false, needsUnlock: true }, online: false });
    const res = await h.run();
    expect(h.calls).toEqual(["flush"]);
    expect(res).toEqual({ ok: false, error: UNLOCK_OFFLINE_MESSAGE });
  });
  it("technician / unsubmitted: first flush result returned as-is, no prompt", async () => {
    const h = harness({ first: { ok: true } });
    expect(await h.run()).toEqual({ ok: true });
    expect(h.calls).toEqual(["flush"]);
  });
  it("read-only role: blocked result passes through (never ok:true)", async () => {
    const h = harness({ first: { ok: false, blocked: true, error: "locked" } });
    expect(await h.run()).toEqual({ ok: false, blocked: true, error: "locked" });
    expect(h.requestReason).not.toHaveBeenCalled();
  });
  it("short reason defensively rejected — no API", async () => {
    const h = harness({ first: { ok: false, needsUnlock: true }, reason: "short" });
    const res = await h.run();
    expect(h.unlock).not.toHaveBeenCalled();
    expect(res.ok).toBe(false);
  });
  it("409 not_locked (unlocked elsewhere) → re-fetch confirms → save proceeds", async () => {
    const h = harness({ first: { ok: false, needsUnlock: true }, unlockErr: new AE("Conflict", 409, { detail: "not_locked" }) });
    expect(await h.run()).toEqual({ ok: true });
    expect(h.calls).toEqual(["flush", "prompt", "unlock", "refetch", "apply", "flush"]);
  });
  it("re-fetch still submitted → abort, no PATCH", async () => {
    const h = harness({ first: { ok: false, needsUnlock: true }, fresh: { submitted_at: "x" } });
    expect(await h.run()).toEqual({ ok: false, error: UNLOCK_REFETCH_FAILED_MESSAGE });
    expect(h.applyUnlocked).not.toHaveBeenCalled();
  });
  it("unlockSubmittedJob → POST /jobs/{jid}/unlock {reason trimmed}; merge keeps local edits", async () => {
    mockPost.mockResolvedValueOnce({ ok: true });
    await unlockSubmittedJob("J1", "  Fixing wrong FC reading ");
    expect(mockPost).toHaveBeenCalledWith("/jobs/J1/unlock", { reason: "Fixing wrong FC reading" });
    const m = mergeUnlockedReport({ id: "sr1", notes: "srv", template: "pool" }, { notes: "local", submitted_at: "old" });
    expect(m).toEqual({ id: "sr1", notes: "local", template: "pool" });
  });
});

describe("TD-g2 follow-up · reclassify through the unlock orchestration", () => {
  const reclass = (h: ReturnType<typeof harness>) => {
    const reclassify = jest.fn(async () => { h.calls.push("reclassify"); });
    return { reclassify, run: () => reclassifyAfterSave({ save: h.run, reclassify }) };
  };
  it("admin: prompt → unlock → refetch/merge → PATCH → reclassify, in order", async () => {
    const h = harness({ first: { ok: false, needsUnlock: true } });
    const r = reclass(h);
    expect(await r.run()).toEqual({ ok: true });
    expect(h.calls).toEqual(["flush", "prompt", "unlock", "refetch", "apply", "flush", "reclassify"]);
  });
  it("admin cancels → no unlock, no reclassify (edits untouched)", async () => {
    const h = harness({ first: { ok: false, needsUnlock: true }, reason: null });
    const r = reclass(h);
    expect(await r.run()).toEqual({ ok: false, cancelled: true });
    expect(r.reclassify).not.toHaveBeenCalled();
    expect(h.applyUnlocked).not.toHaveBeenCalled();
  });
  it.each([
    [new AE("Forbidden", 403, null)], [new AE("Server", 503, null)], [new TypeError("Network request failed")],
  ])("unlock failure %#: error returned, reclassify aborted", async (err) => {
    const h = harness({ first: { ok: false, needsUnlock: true }, unlockErr: err });
    const r = reclass(h);
    const res = await r.run();
    expect(res.ok).toBe(false);
    expect(res.error).toBeTruthy();
    expect(r.reclassify).not.toHaveBeenCalled();
    expect(h.applyUnlocked).not.toHaveBeenCalled();
  });
  it("technician / already-unlocked-in-session: no prompt, reclassify fires", async () => {
    const h = harness({ first: { ok: true } });
    const r = reclass(h);
    expect(await r.run()).toEqual({ ok: true });
    expect(h.calls).toEqual(["flush", "reclassify"]);
  });
  it("read-only role: blocked, reclassify not fired", async () => {
    const h = harness({ first: { ok: false, blocked: true, error: "locked" } });
    const r = reclass(h);
    expect(await r.run()).toEqual({ ok: false, blocked: true, error: "locked" });
    expect(r.reclassify).not.toHaveBeenCalled();
  });
  it("offline admin: no prompt, no queue, reclassify not fired", async () => {
    const h = harness({ first: { ok: false, needsUnlock: true }, online: false });
    const r = reclass(h);
    expect(await r.run()).toEqual({ ok: false, error: UNLOCK_OFFLINE_MESSAGE });
    expect(h.calls).toEqual(["flush"]);
  });
  it("plain save failure (PATCH error) also aborts — refetch can no longer wipe edits", async () => {
    const h = harness({ first: { ok: false, error: "Save failed" } });
    const r = reclass(h);
    expect((await r.run()).ok).toBe(false);
    expect(r.reclassify).not.toHaveBeenCalled();
  });
  it("checklist wiring: handleReclassify uses reclassifyAfterSave + runSave; no bare flushSave", () => {
    const body = SRC.slice(SRC.indexOf("const handleReclassify = useCallback"), SRC.indexOf("}, [id, runSave, showToast]);"));
    expect(body).toContain("await reclassifyAfterSave({");
    expect(body).toContain("save: () => runSave(),");
    expect(body).not.toContain("flushSave(");
    expect(body.indexOf("api.put(`/jobs/${id}`")).toBeGreaterThan(body.indexOf("reclassify: async () =>"));
    expect(body).toContain("} else if (!pre.cancelled) {");
    expect(body.indexOf('showToast("Service type updated.")')).toBeGreaterThan(body.indexOf("if (pre.ok)"));
    expect(SRC).toMatch(/const canEditServiceType: boolean = !effectiveLocked && \(\s*isUnlockAdminRole\(role\) \|\|/);
  });
});

describe("TD-g2 · UnlockReasonModal", () => {
  const setup = (busy = false) => {
    const onSubmit = jest.fn(); const onCancel = jest.fn();
    const r = render(<UnlockReasonModal visible busy={busy} onSubmit={onSubmit} onCancel={onCancel} />);
    return { ...r, onSubmit, onCancel };
  };
  it("< 8 chars: confirm blocked with inline error, onSubmit not called", () => {
    const { getByTestId, onSubmit } = setup();
    fireEvent.changeText(getByTestId("unlock-reason-input"), "short");
    fireEvent.press(getByTestId("unlock-reason-confirm"));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(getByTestId("unlock-reason-error").props.children).toMatch(/at least 8 characters/);
  });
  it("valid reason → onSubmit(trimmed)", () => {
    const { getByTestId, onSubmit } = setup();
    fireEvent.changeText(getByTestId("unlock-reason-input"), "  Fixing wrong FC reading  ");
    fireEvent.press(getByTestId("unlock-reason-confirm"));
    expect(onSubmit).toHaveBeenCalledWith("Fixing wrong FC reading");
  });
  it("cancel + backdrop dismiss; ignored while busy", () => {
    const a = setup();
    fireEvent.press(a.getByTestId("unlock-reason-cancel"));
    fireEvent.press(a.getByTestId("unlock-reason-backdrop"));
    expect(a.onCancel).toHaveBeenCalledTimes(2);
    a.unmount();
    const b = setup(true);
    fireEvent.press(b.getByTestId("unlock-reason-backdrop"));
    expect(b.onCancel).not.toHaveBeenCalled();
  });
});

describe("TD-g2 · checklist.tsx wiring (source locks)", () => {
  it("silent submitted_at → ok:true drop is gone; role split via the lib", () => {
    expect(SRC).not.toMatch(/current\.submitted_at\)\s*return\s*\{\s*ok:\s*true\s*\}/);
    expect(SRC).toContain("const submittedMode = submittedSaveMode(role, current);");
    expect(SRC).toContain("return { ok: false, needsUnlock: true };");
    expect(SRC).toContain("return { ok: false, blocked: true, error: SUBMITTED_READ_ONLY_MESSAGE };");
  });
  it("Save draft / Save & close / Close-job pre-flush all go through runSave", () => {
    const body = (start: string, end: string) => SRC.slice(SRC.indexOf(start), SRC.indexOf(end, SRC.indexOf(start)));
    const saveDraft = body("const saveDraft = async", "saveDraftRef.current = saveDraft;");
    const saveClose = body("const handleSaveAndClose = useCallback", "const handleDiscard");
    const closeJob = body("const doCloseJob = async", "// 2) Submit / close.");
    for (const b of [saveDraft, saveClose, closeJob]) {
      expect(b).toContain("await runSave(");
      expect(b).not.toContain("await flushSave()");
    }
    expect(SRC).toContain("unlock: (reason) => unlockSubmittedJob(String(id), reason)");
  });
  it('"Draft saved." only on real success; cancelled paths stay silent', () => {
    const saveDraft = SRC.slice(SRC.indexOf("const saveDraft = async"), SRC.indexOf("saveDraftRef.current = saveDraft;"));
    expect((SRC.match(/showToast\("Draft saved\."\)/g) || []).length).toBe(1);
    expect(saveDraft.indexOf('showToast("Draft saved.")')).toBeGreaterThan(saveDraft.indexOf("if (result.ok)"));
    expect(saveDraft.indexOf('showToast("Draft saved.")')).toBeLessThan(saveDraft.indexOf("result.cancelled"));
    expect(SRC).toContain("if (!flushed.cancelled)");
    expect(SRC).toContain("} else if (!result.cancelled) {");
  });
  it("modal + notice mounted; canWrite gate unchanged", () => {
    expect(SRC).toContain("<UnlockReasonModal");
    expect(SRC).toContain("<SubmittedReportUnlockNotice");
    expect(SRC).toContain('const canWrite = role === "admin" || role === "super_admin" || role === "technician";');
  });
});
