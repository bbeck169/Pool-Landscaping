/**
 * Feb-2026 P0 · Template save payload — channel field must be
 * included in the ``PATCH /marketing/templates/{id}`` body.
 *
 * The Item-2 ship added the Email/SMS segmented control but the
 * save handler's payload dict omitted ``channel``, so switching to
 * SMS appeared to work in the UI but the persisted row stayed on
 * ``email``. Source-inspection guard so this can't silently
 * regress again.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(__dirname, "../pages/marketing/MarketingTemplatesAdmin.jsx"),
  "utf8",
);

describe("Templates admin — save() payload includes channel", () => {
  it("payload literal contains ``channel: row.channel``", () => {
    // Locate the save function block, then assert on that slice so
    // an unrelated ``channel:`` elsewhere in the file (e.g. list
    // filter state) can't false-positive the match.
    const idx = src.indexOf("async function save()");
    expect(idx).toBeGreaterThan(-1);
    // ~1KB block is more than enough — the function is <30 lines.
    const block = src.slice(idx, idx + 1200);
    expect(block).toMatch(/channel:\s*row\.channel/);
  });

  it("clears subject when saving as SMS", () => {
    // ``row.channel === "sms" ? null : row.subject`` in the payload.
    const idx = src.indexOf("async function save()");
    const block = src.slice(idx, idx + 1200);
    expect(block).toMatch(
      /subject:\s*row\.channel\s*===\s*"sms"\s*\?\s*null\s*:\s*row\.subject/,
    );
  });

  it("still PATCHes /marketing/templates/{id} on save", () => {
    const idx = src.indexOf("async function save()");
    const block = src.slice(idx, idx + 1200);
    expect(block).toMatch(
      /api\.patch\(`\/marketing\/templates\/\$\{id\}`,\s*payload\)/,
    );
  });
});
