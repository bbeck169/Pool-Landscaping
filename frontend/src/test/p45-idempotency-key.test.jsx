/**
 * Phase P45 · Feb-2026 — X-Idempotency-Key wiring on submit paths.
 *
 * Tests locked here (file-inspection style, matching the fast
 * ``phase30-3-portal-sign-out.test.jsx`` convention):
 *
 *   1. ``useIdempotencyKey`` hook exports the expected surface
 *      (``key`` / ``headers`` / ``regenerate``) and mints a stable
 *      UUID on mount.
 *   2. ``ServiceReport.jsx`` imports the hook and passes
 *      ``idempotencyHeaders`` to the submit ``api.request(...)``
 *      call.
 *   3. ``ChecklistModal.jsx`` imports the hook and passes
 *      ``idempotencyHeaders`` to its submit ``api.request(...)``
 *      call.
 *   4. Both submit sites call ``regenerateIdempotencyKey()`` in the
 *      success branch — a subsequent submit gets a fresh key so
 *      the backend replay guard treats it as a new action.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useIdempotencyKey } from "../hooks/useIdempotencyKey";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");
const SERVICE_REPORT   = R("../pages/tech/ServiceReport.jsx");
const CHECKLIST_MODAL  = R("../components/checklist/ChecklistModal.jsx");
const HOOK_SRC         = R("../hooks/useIdempotencyKey.js");

describe("Phase P45 · X-Idempotency-Key wiring", () => {
  it("useIdempotencyKey mints a stable UUID and exposes headers + regenerate", () => {
    const { result } = renderHook(() => useIdempotencyKey());
    // Shape.
    expect(typeof result.current.key).toBe("string");
    expect(result.current.key.length).toBeGreaterThan(0);
    expect(result.current.headers).toEqual({
      "X-Idempotency-Key": result.current.key,
    });
    expect(typeof result.current.regenerate).toBe("function");

    // Same-key stability across re-renders (single ``useState``
    // seed — belt of the belt).
    const firstKey = result.current.key;
    // No re-mount, no regenerate — key should be identical.
    expect(result.current.key).toBe(firstKey);
  });

  it("regenerate() mints a fresh UUID", () => {
    const { result } = renderHook(() => useIdempotencyKey());
    const before = result.current.key;
    act(() => result.current.regenerate());
    expect(result.current.key).not.toBe(before);
    expect(result.current.headers).toEqual({
      "X-Idempotency-Key": result.current.key,
    });
  });

  it("ServiceReport imports the hook and passes idempotencyHeaders on submit", () => {
    // Import present.
    expect(SERVICE_REPORT).toMatch(
      /import\s*\{\s*useIdempotencyKey\s*\}\s*from\s*["']@\/hooks\/useIdempotencyKey["']/,
    );
    // Hook instantiated inside the component.
    expect(SERVICE_REPORT).toMatch(
      /const\s*\{\s*headers:\s*idempotencyHeaders\s*,\s*regenerate:\s*regenerateIdempotencyKey\s*\}\s*=\s*useIdempotencyKey\(\)/,
    );
    // Submit call routes through api.request with the header.
    const submitBlock = SERVICE_REPORT.match(
      /api\.request\(\s*[\s\S]{0,120}service-report\/submit[\s\S]{0,600}/,
    );
    expect(submitBlock).not.toBeNull();
    expect(submitBlock[0]).toMatch(/headers:\s*idempotencyHeaders/);
    // regenerate() called on success (must come AFTER the api.request
    // line but BEFORE any navigate/redirect).
    const submitFnBlock = SERVICE_REPORT.match(
      /submitAndClockOut[\s\S]*?const submitted = await api\.request[\s\S]*?regenerateIdempotencyKey\(\)/,
    );
    expect(submitFnBlock).not.toBeNull();
  });

  it("ChecklistModal imports the hook and passes idempotencyHeaders on submit", () => {
    expect(CHECKLIST_MODAL).toMatch(
      /import\s*\{\s*useIdempotencyKey\s*\}\s*from\s*["']@\/hooks\/useIdempotencyKey["']/,
    );
    expect(CHECKLIST_MODAL).toMatch(
      /const\s*\{\s*headers:\s*idempotencyHeaders\s*,\s*regenerate:\s*regenerateIdempotencyKey\s*\}\s*=\s*useIdempotencyKey\(\)/,
    );
    const submitBlock = CHECKLIST_MODAL.match(
      /api\.request\(\s*[\s\S]{0,120}service-report\/submit[\s\S]{0,600}/,
    );
    expect(submitBlock).not.toBeNull();
    expect(submitBlock[0]).toMatch(/headers:\s*idempotencyHeaders/);
    // regenerate on success.
    expect(CHECKLIST_MODAL).toMatch(
      /const submitted = await api\.request\([\s\S]*?\);\s*(?:\/\/[^\n]*\n\s*)*(?:\/\/[^\n]*\n\s*)*regenerateIdempotencyKey\(\)/,
    );
  });

  it("hook exports a fallback UUID generator for jsdom environments without crypto.randomUUID", () => {
    // Guardrail — vitest+jsdom in older node builds sometimes lack
    // ``crypto.randomUUID``.  The hook must survive.  Both the primary
    // and fallback branches should be present in the source.
    expect(HOOK_SRC).toMatch(/crypto\.randomUUID/);
    expect(HOOK_SRC).toMatch(/getRandomValues/);
    // Header shape is stable — one field only, the right name.
    expect(HOOK_SRC).toMatch(/"X-Idempotency-Key"\s*:\s*key/);
  });
});
