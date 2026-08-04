// Phase 34 · Endpoint Path Normalization (Feb 2026) — source-inspection
// vitest that locks in the mobile ReviewSubmit page migration from the
// legacy `/public/r/*` prefix to the canonical `/reviews/public/r/*`.
//
// The backend still exposes both (via `routers/reviews_public_alias.py`)
// with a `Deprecation: true` header on the alias — but new code must
// call the canonical path. This test scans the mobile source to make
// sure no `api.get("/public/r/...")` or `api.post("/public/r/...")`
// slipped back in.

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const REVIEW_SUBMIT_PATH = resolve(
  __dirname,
  "../../../mobile/app/portal/review-submit.tsx",
);

describe("Phase 34 · Mobile endpoint normalization (review-submit)", () => {
  it("exposes mobile/app/portal/review-submit.tsx", () => {
    expect(existsSync(REVIEW_SUBMIT_PATH)).toBe(true);
  });

  const src = existsSync(REVIEW_SUBMIT_PATH)
    ? readFileSync(REVIEW_SUBMIT_PATH, "utf8")
    : "";

  it("calls the canonical GET /reviews/public/r/{token} on landing", () => {
    expect(src).toMatch(
      /api\.get\(\s*`?\/reviews\/public\/r\/\$\{token\}`?/,
    );
  });

  it("posts the canonical rating path", () => {
    expect(src).toMatch(
      /api\.post\(\s*`?\/reviews\/public\/r\/\$\{token\}\/rating`?/,
    );
  });

  it("posts the canonical google-clicked path", () => {
    expect(src).toMatch(
      /api\.post\(\s*`?\/reviews\/public\/r\/\$\{token\}\/google-clicked`?/,
    );
  });

  it("no longer calls the legacy `/public/r/*` prefix directly", () => {
    // Any `api.get("/public/r/…")` / `api.post("/public/r/…")` regression
    // would break Phase 34's normalization. The backend still serves the
    // alias, but new code must not use it.
    expect(src).not.toMatch(/api\.(get|post)\(\s*`?\/public\/r\//);
  });

  it("carries a Phase 34 comment pointing readers at the migration", () => {
    // Locks in the developer note so `git blame` explains itself.
    expect(src).toMatch(/Phase 34/);
  });
});

const BACKEND_ALIAS_PATH = resolve(
  __dirname,
  "../../../backend/routers/reviews_public_alias.py",
);

describe("Phase 34 · Backend alias router shape", () => {
  it("exposes backend/routers/reviews_public_alias.py", () => {
    expect(existsSync(BACKEND_ALIAS_PATH)).toBe(true);
  });

  const src = existsSync(BACKEND_ALIAS_PATH)
    ? readFileSync(BACKEND_ALIAS_PATH, "utf8")
    : "";

  it("mirrors all 5 public review-request endpoints", () => {
    expect(src).toMatch(/@router\.get\("\/public\/r\/\{token\}"\)/);
    expect(src).toMatch(/@router\.post\("\/public\/r\/\{token\}\/rating"\)/);
    expect(src).toMatch(
      /@router\.post\("\/public\/r\/\{token\}\/google-clicked"\)/,
    );
    expect(src).toMatch(
      /@router\.post\("\/public\/r\/\{token\}\/platform-clicked"\)/,
    );
    expect(src).toMatch(
      /@router\.post\("\/public\/r\/\{token\}\/private-feedback"\)/,
    );
  });

  it("stamps Deprecation + Link headers on every alias response", () => {
    expect(src).toMatch(/Deprecation.*true/);
    expect(src).toMatch(/rel="alternate"/);
    expect(src).toMatch(/\/api\/reviews\/public\/r/);
  });

  it("does not duplicate handler logic — imports from canonical module", () => {
    // Alias handlers must defer to the real ones, otherwise divergence
    // (bugs, headers, gating) can drift between the two paths.
    expect(src).toMatch(/from \. import reviews as _reviews/);
    expect(src).toMatch(/await _reviews\.public_landing/);
    expect(src).toMatch(/await _reviews\.submit_rating/);
    expect(src).toMatch(/await _reviews\.google_clicked/);
  });
});
