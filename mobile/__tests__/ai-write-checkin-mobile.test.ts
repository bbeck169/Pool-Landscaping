/**
 * AI Write button on Check-In composer — source-scanning + contract tests.
 *
 * Tests:
 *   a) Button renders and is initially in "AI Write" state
 *   b) Successful call updates note and switches to "Undo AI"
 *   c) 429 shows correct rate-limit toast
 *   d) Pattern A: draft creation + reuse
 *   e) Undo restores pre-AI text
 */

import fs from "fs";
import path from "path";

function readComposer(): string {
  return fs.readFileSync(
    path.resolve(__dirname, "../app/job/[id]/checkin.tsx"),
    "utf8",
  );
}

describe("AI Write button · renders and initial state", () => {
  const src = readComposer();

  it("button exists with correct testID", () => {
    expect(src).toContain('testID="checkin-ai-write-btn"');
  });

  it("initial aiState is 'write'", () => {
    expect(src).toMatch(
      /const\s*\[aiState,\s*setAiState\]\s*=\s*useState<[^>]+>\("write"\)/,
    );
  });

  it("shows 'AI Write' text in write state", () => {
    expect(src).toMatch(/aiState\s*===\s*"undo"\s*\?\s*"Undo AI"\s*:\s*"AI Write"/);
  });

  it("shows sparkle emoji in write state, undo icon in undo state", () => {
    expect(src).toContain("✨");
    expect(src).toMatch(/aiState\s*===\s*"undo"[\s\S]{0,100}arrow-undo/);
  });

  it("exposes accessibilityState.selected for undo mode", () => {
    expect(src).toMatch(/accessibilityState=\{\{\s*selected:\s*aiState\s*===\s*"undo"\s*\}\}/);
  });

  it("icon testID is present", () => {
    expect(src).toContain('testID="checkin-ai-write-btn-icon"');
  });
});

describe("AI Write button · successful call → note prefilled + undo state", () => {
  const src = readComposer();

  it("calls POST /checkins/{id}/ai-description", () => {
    expect(src).toMatch(
      /api\.post\(`\/checkins\/\$\{checkinId\}\/ai-description`/,
    );
  });

  it("on success, stashes current note as preAiValue", () => {
    expect(src).toMatch(/setPreAiValue\(note\)/);
  });

  it("on success, sets note to AI description", () => {
    expect(src).toMatch(/setNote\(text\)/);
  });

  it("on success, switches to undo state", () => {
    expect(src).toMatch(/setAiState\("undo"\)/);
  });

  it("empty description falls through to failure toast", () => {
    expect(src).toMatch(
      /if\s*\(!text\)[\s\S]{0,100}AI Write failed\. Please write manually\./,
    );
  });
});

describe("AI Write button · 429 rate-limit toast", () => {
  const src = readComposer();

  it("detects 429 status or rate_limit_exceeded code", () => {
    expect(src).toMatch(/e\?\.status\s*===\s*429/);
    expect(src).toMatch(/rate_limit_exceeded/);
  });

  it("computes minutes from retry_after_seconds with Math.ceil", () => {
    expect(src).toMatch(/Math\.ceil\(retryAfter\s*\/\s*60\)/);
  });

  it("toast copy matches spec exactly", () => {
    expect(src).toMatch(
      /AI Write rate limit reached\. Try again in \$\{mins\} minutes\./,
    );
  });

  it("defaults to 60 minutes when no retry_after_seconds", () => {
    expect(src).toMatch(/retryAfter\s*\?\s*Math\.ceil\(retryAfter\s*\/\s*60\)\s*:\s*60/);
  });
});

describe("AI Write button · 500 / network error toast", () => {
  const src = readComposer();

  it("non-429 errors show manual-write toast", () => {
    // This appears in both the empty-description check and the catch
    const matches = src.match(/AI Write failed\. Please write manually\./g);
    expect(matches?.length).toBeGreaterThanOrEqual(2);
  });
});

describe("AI Write button · Undo restores pre-AI text", () => {
  const src = readComposer();

  it("undo click restores preAiValue", () => {
    expect(src).toMatch(/setNote\(preAiValue\s*\?\?\s*""\)/);
  });

  it("undo click clears preAiValue", () => {
    expect(src).toMatch(/setPreAiValue\(null\)/);
  });

  it("undo click resets to write state", () => {
    // In the undo branch: setAiState("write")
    const undoBranch = src.match(
      /aiState\s*===\s*"undo"[\s\S]{0,200}setAiState\("write"\)/,
    );
    expect(undoBranch).not.toBeNull();
  });
});

describe("AI Write button · Pattern A: draft creation + reuse on Submit", () => {
  const src = readComposer();

  it("ensureDraft creates a check-in via POST /checkins", () => {
    // ensureDraft function exists and calls api.post("/checkins")
    expect(src).toMatch(/const ensureDraft/);
    const fnStart = src.indexOf("const ensureDraft");
    const fnChunk = src.slice(fnStart, fnStart + 800);
    expect(fnChunk).toMatch(/api\.post\("\/checkins"/);
  });

  it("ensureDraft stores the draft id", () => {
    expect(src).toMatch(
      /setDraftCheckinId\(id\)/,
    );
  });

  it("handleSubmit reuses draftCheckinId if it exists", () => {
    expect(src).toMatch(
      /let\s+checkinId\s*=\s*draftCheckinId/,
    );
  });

  it("handleSubmit patches draft with final data when reusing", () => {
    expect(src).toMatch(
      /api\.patch\(`\/checkins\/\$\{checkinId\}`/,
    );
  });

  it("handleSubmit creates new check-in when no draft exists", () => {
    // The else branch in handleSubmit creates fresh via api.post
    const submitStart = src.indexOf("const handleSubmit");
    const submitChunk = src.slice(submitStart, submitStart + 1200);
    expect(submitChunk).toMatch(/else\s*\{/);
    expect(submitChunk).toMatch(/api\.post\("\/checkins"/);
  });
});

describe("AI Write button · disabled states", () => {
  const src = readComposer();

  it("disabled during AI request (busy)", () => {
    expect(src).toMatch(
      /disabled=\{aiState\s*===\s*"busy"\s*\|\|\s*submitting\}/,
    );
  });

  it("shows spinner during busy state", () => {
    expect(src).toMatch(
      /aiState\s*===\s*"busy"[\s\S]{0,100}ActivityIndicator/,
    );
  });
});
