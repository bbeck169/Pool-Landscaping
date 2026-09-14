/**
 * Tech Check-In Mobile — source-scanning + contract tests.
 *
 * Tests:
 *   1. Submit disabled until GPS + note + ≥1 photo.
 *   2. Two-step submission fires /checkins then /checkins/{id}/submit-public.
 *   3. Photo upload failure blocks Submit until resolved.
 *   4. Correct testIDs present.
 *   5. Job Detail "Log Check-in" button present.
 */

import fs from "fs";
import path from "path";

function readComposer(): string {
  return fs.readFileSync(
    path.resolve(__dirname, "../app/job/[id]/checkin.tsx"),
    "utf8",
  );
}
function readJobDetail(): string {
  return fs.readFileSync(
    path.resolve(__dirname, "../app/job/[id].tsx"),
    "utf8",
  );
}

describe("Check-In Composer · Submit disabled until GPS + note + photo", () => {
  const src = readComposer();

  it("canSubmit requires gpsLocked", () => {
    expect(src).toMatch(
      /const canSubmit\s*=\s*gpsLocked/,
    );
  });

  it("canSubmit requires noteValid", () => {
    expect(src).toMatch(/canSubmit[\s\S]{0,60}noteValid/);
  });

  it("canSubmit requires allPhotosUploaded", () => {
    expect(src).toMatch(/canSubmit[\s\S]{0,120}allPhotosUploaded/);
  });

  it("Submit button is disabled when canSubmit is false", () => {
    expect(src).toMatch(/disabled=\{!canSubmit\}/);
  });

  it("allPhotosUploaded requires photos.length > 0", () => {
    expect(src).toMatch(
      /const allPhotosUploaded\s*=\s*photos\.length\s*>\s*0/,
    );
  });

  it("allPhotosUploaded requires every photo has fileId and no error", () => {
    expect(src).toMatch(
      /photos\.every\(\(p\)\s*=>\s*p\.fileId\s*&&\s*!p\.uploading\s*&&\s*!p\.error\)/,
    );
  });

  it("noteValid requires non-empty and <= 2000 chars", () => {
    expect(src).toMatch(/note\.trim\(\)\.length\s*>=\s*1/);
    expect(src).toMatch(/note\.trim\(\)\.length\s*<=\s*NOTE_MAX/);
  });
});

describe("Check-In Composer · Two-step submission", () => {
  const src = readComposer();

  it("Step 1: POST /api/checkins with correct payload shape", () => {
    expect(src).toMatch(/api\.post\("\/checkins"\s*,\s*body\)/);
    expect(src).toContain("job_id: jobId");
    expect(src).toContain("latitude: gps.lat");
    expect(src).toContain("longitude: gps.lng");
    expect(src).toContain("photo_file_ids:");
  });

  it("Step 2: POST /api/checkins/{id}/submit-public after Step 1 succeeds", () => {
    expect(src).toMatch(
      /api\.post\(`\/checkins\/\$\{checkinId\}\/submit-public`/,
    );
  });

  it("Step 1 failure shows error toast and stays on composer", () => {
    // After the first try/catch, it shows toast but does NOT call router.back()
    expect(src).toMatch(
      /showToast\(e\?\.message[\s\S]{0,50}"Failed to create check-in"/,
    );
  });

  it("Step 2 failure shows warning toast and navigates back", () => {
    expect(src).toMatch(
      /showToast\("Check-in saved but not submitted for review/,
    );
  });

  it("Success shows review toast and navigates back", () => {
    expect(src).toContain('showToast("Check-in submitted for review")');
  });
});

describe("Check-In Composer · Photo upload failure blocks Submit", () => {
  const src = readComposer();

  it("upload failure sets error on the photo slot", () => {
    // In the catch block of pickPhoto, error is set
    expect(src).toMatch(
      /error:\s*e\?\.message\s*\|\|\s*"Upload failed"/,
    );
  });

  it("photo error blocks allPhotosUploaded", () => {
    // allPhotosUploaded checks !p.error
    expect(src).toMatch(/!p\.error/);
  });

  it("retry button exists per photo", () => {
    expect(src).toMatch(/testID=\{`checkin-photo-retry-\$\{i\}`\}/);
  });

  it("retryPhoto re-uploads the same localUri", () => {
    expect(src).toMatch(/const retryPhoto\s*=\s*async/);
    expect(src).toMatch(/uri:\s*slot\.localUri/);
  });
});

describe("Check-In Composer · testID map", () => {
  const src = readComposer();

  it("note input", () => {
    expect(src).toContain('testID="checkin-note-input"');
  });

  it("photo picker container", () => {
    expect(src).toContain('testID="checkin-photo-picker"');
  });

  it("photo thumbnails per-index", () => {
    expect(src).toMatch(/testID=\{`checkin-photo-thumb-\$\{i\}`\}/);
  });

  it("photo remove per-index", () => {
    expect(src).toMatch(/testID=\{`checkin-photo-remove-\$\{i\}`\}/);
  });

  it("submit button", () => {
    expect(src).toContain('testID="checkin-submit-btn"');
  });

  it("GPS recapture button", () => {
    expect(src).toContain('testID="checkin-gps-recapture-btn"');
  });
});

describe("Job Detail · Log Check-in button", () => {
  const src = readJobDetail();

  it("Log Check-in button exists with correct testID", () => {
    expect(src).toContain('testID="job-detail-log-checkin-btn"');
  });

  it("navigates to /job/{id}/checkin route", () => {
    expect(src).toMatch(/router\.push\(`\/job\/\$\{id\}\/checkin`\)/);
  });

  it("only renders for canManage users", () => {
    // The button is gated: {canManage && job.id ? ( ... log-checkin-btn ... ) : null}
    // Both patterns must appear in the file
    expect(src).toContain('testID="job-detail-log-checkin-btn"');
    // And the surrounding block is gated on canManage
    const idx = src.indexOf('job-detail-log-checkin-btn');
    const chunk = src.slice(Math.max(0, idx - 800), idx);
    expect(chunk).toMatch(/canManage\s*&&\s*job\.id/);
  });
});

describe("Check-In Composer · Photo upload uses files/upload with purpose", () => {
  const src = readComposer();

  it("imports uploadFile from files API", () => {
    expect(src).toMatch(/import\s*\{[^}]*uploadFile[^}]*\}\s*from\s*"@\/src\/api\/files"/);
  });

  it("sets purpose to public_checkin", () => {
    expect(src).toContain('purpose: "public_checkin"');
  });

  it("has onProgress callback for upload tracking", () => {
    expect(src).toMatch(/onProgress:\s*\(pct\)/);
  });
});
