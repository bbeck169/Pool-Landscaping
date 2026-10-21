/**
 * TD-82-mobile-calendar-bulk · calendar bulk delete → canonical /jobs/bulk-delete.
 * Behaviour on the helper (the 2.5k-line calendar screen has no passing render
 * harness); wiring + legacy-path lock via source scan of calendar.tsx.
 */
import fs from "fs";
import path from "path";

const mockPost = jest.fn();
jest.mock("@/src/api", () => ({ api: { post: (u: string, b: any) => mockPost(u, b) } }));

import { bulkDeleteJobs } from "@/src/lib/jobsBulkDelete";

const CAL = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf8");
const HANDLER = CAL.slice(CAL.indexOf("const bulkDelete = async"), CAL.indexOf("const openReassign = async"));

beforeEach(() => mockPost.mockReset());

it("B1 · POSTs canonical /jobs/bulk-delete with { ids } (never the legacy shim / job_ids)", async () => {
  mockPost.mockResolvedValue({ ok: true, deleted_count: 2, deleted: ["a", "b"], failed: [] });
  await bulkDeleteJobs(["a", "b"]);
  expect(mockPost).toHaveBeenCalledTimes(1);
  expect(mockPost).toHaveBeenCalledWith("/jobs/bulk-delete", { ids: ["a", "b"] });
  expect(mockPost).not.toHaveBeenCalledWith("/jobs/bulk-soft-delete", expect.anything());
});

it("B2 · count reads deleted_count first (partial lock: 1 of 2 deleted)", async () => {
  mockPost.mockResolvedValue({ ok: true, deleted_count: 1, deleted: ["a"], failed: [{ id: "b", reason: "locked", status_code: 409 }] });
  await expect(bulkDeleteJobs(["a", "b"])).resolves.toEqual({ count: 1, failed: [{ id: "b", reason: "locked", status_code: 409 }] });
});

it("B3 · deleted_count missing → deleted.length (web e57734f00 fallback)", async () => {
  mockPost.mockResolvedValue({ deleted: ["a", "b", "c"] });
  await expect(bulkDeleteJobs(["a", "b", "c"])).resolves.toEqual({ count: 3, failed: [] });
});

it("B4 · deleted_count: 0 is honoured (?? not ||)", async () => {
  mockPost.mockResolvedValue({ deleted_count: 0, deleted: ["x"], failed: [] });
  expect((await bulkDeleteJobs(["x"])).count).toBe(0);
});

it("B5 · empty / unexpected envelope → legacy value (requested id count)", async () => {
  mockPost.mockResolvedValue(null);
  await expect(bulkDeleteJobs(["a", "b"])).resolves.toEqual({ count: 2, failed: [] });
});

it("B6 · API error propagates (calendar catch keeps the 'Delete failed.' error toast)", async () => {
  mockPost.mockRejectedValue(new Error("403 Forbidden"));
  await expect(bulkDeleteJobs(["a"])).rejects.toThrow("403 Forbidden");
});

it("W1 · calendar handler uses the helper; success + error toast wording preserved", () => {
  expect(HANDLER).toContain("await bulkDeleteJobs([...checked])");
  expect(HANDLER).toContain('showToast(`${count} job${count === 1 ? "" : "s"} removed.`)');
  expect(HANDLER).toContain('showToast(e?.message || "Delete failed.", "error")');
  expect(HANDLER).toContain('message: "Soft-deleted jobs can be recovered by a super admin."');
});

it("W2 · regression lock: no mobile source references the legacy shim or job_ids delete body", () => {
  expect(CAL).not.toContain("/jobs/bulk-soft-delete");
  expect(HANDLER).not.toMatch(/job_ids/);
});
