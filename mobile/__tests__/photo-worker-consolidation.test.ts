/**
 * Phase P21 · photo-worker-consolidation.test.ts
 *
 * Source-level lint tests ensuring all photo capture surfaces route
 * through the durable SQLite-backed photoWorker pipeline and that
 * no capture surface holds full base64 in JS memory.
 */

import * as fs from "fs";
import * as path from "path";

const ROOT = path.resolve(__dirname, "..");

function readSrc(relPath: string): string {
  return fs.readFileSync(path.join(ROOT, relPath), "utf-8");
}

// ── Capture surfaces that handle job photos ────────────────────────
const JOB_DETAIL = "app/job/[id].tsx";
const JOB_CHECKLIST = "app/job/[id]/checklist.tsx";

// ── Surfaces that are exempt (different resource type, sync upload) ─
const EXEMPT_SURFACES = [
  "app/job/[id]/checkin.tsx",   // uploadFile → needs fileId back synchronously
  "app/customer/new.tsx",       // avatar inline in POST body
  "app/customer/[id].tsx",      // document attachment
  "app/equipment.tsx",          // equipment photo inline
  "app/landscape.tsx",          // AI render input
  "app/card.tsx",               // company logo
];

describe("Photo pipeline consolidation (P21)", () => {
  it("job/[id].tsx imports capturePhoto from photoWorker", () => {
    const src = readSrc(JOB_DETAIL);
    expect(src).toMatch(/capturePhoto.*photoWorker|photoWorker.*capturePhoto/s);
  });

  it("job/[id].tsx does NOT import queuePhoto from offline", () => {
    const src = readSrc(JOB_DETAIL);
    expect(src).not.toMatch(/import.*queuePhoto.*from.*offline/);
  });

  it("job/[id].tsx does NOT use {base64: true} in ImagePicker options", () => {
    const src = readSrc(JOB_DETAIL);
    // Strip single-line comments before checking.
    const noComments = src.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(noComments).not.toMatch(/base64\s*:\s*true/);
  });

  it("job/[id].tsx does NOT call pendingForJob", () => {
    const src = readSrc(JOB_DETAIL);
    expect(src).not.toMatch(/pendingForJob/);
  });

  it("job/[id]/checklist.tsx imports capturePhoto from photoWorker", () => {
    const src = readSrc(JOB_CHECKLIST);
    expect(src).toMatch(/capturePhoto.*photoWorker|photoWorker.*capturePhoto/s);
  });

  it("no readAsStringAsync + base64 in any capture surface", () => {
    const ALL_SURFACES = [JOB_DETAIL, JOB_CHECKLIST, ...EXEMPT_SURFACES];
    for (const rel of ALL_SURFACES) {
      const full = path.join(ROOT, rel);
      if (!fs.existsSync(full)) continue;
      const src = fs.readFileSync(full, "utf-8");
      expect(src).not.toMatch(
        /readAsStringAsync\s*\([^)]*base64/i,
      );
    }
  });

  it("no direct fetch/axios to *photos* endpoint outside photoWorker.ts", () => {
    // Check the job capture surfaces — they must NOT have direct upload calls.
    const src = readSrc(JOB_DETAIL);
    // Should not have `api.post(\`/jobs/${id}/photos\`` since that's photoWorker's job.
    expect(src).not.toMatch(/api\.post\s*\(\s*`\/jobs\/\$\{.*\}\/photos`/);
  });

  it("SyncBanner uses flushPhotos from photoWorker, not flushPendingPhotos from offline", () => {
    const src = readSrc("src/components/SyncBanner.tsx");
    expect(src).toMatch(/flushPhotos.*photoWorker|photoWorker.*flushPhotos/s);
    expect(src).not.toMatch(/flushPendingPhotos/);
  });

  it("jobs.tsx uses flushPhotos from photoWorker, not flushPendingPhotos from offline", () => {
    const src = readSrc("app/(app)/jobs.tsx");
    expect(src).toMatch(/flushPhotos.*photoWorker|photoWorker.*flushPhotos/s);
    expect(src).not.toMatch(/flushPendingPhotos/);
  });
});
