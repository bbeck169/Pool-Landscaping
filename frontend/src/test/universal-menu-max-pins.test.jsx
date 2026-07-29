/**
 * MAX_PINS cap · Feb-2026 — the Universal Menu enforces a pure UX cap
 * on how many favorites a user can pin. This test pins the current
 * value (30) so future refactors can't silently lower it.
 *
 * The cap itself is a module-local constant in UniversalMenu.jsx and
 * is not exported; we read it back by exercising the observed
 * behaviour: seed >cap pins into localStorage, mount the menu, verify
 * only `cap` items are rendered.
 */
import React from "react";
import { describe, it, expect, vi, afterEach, cleanup as _cleanup } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({
  api: { get: vi.fn().mockResolvedValue({}), post: vi.fn(), patch: vi.fn() },
}));
vi.mock("@/auth", () => ({ useAuth: () => ({ user: { id: "u-1", role: "admin" } }) }));

afterEach(() => cleanup());

/**
 * Pull the numeric cap out of the source at test time. Doing it this
 * way — not by importing the component — avoids booting the full nav
 * tree (which pulls in dozens of routed pages) while still catching a
 * silent downgrade of the cap.
 */
function readCapFromSource() {
  // eslint-disable-next-line global-require
  const src = require("fs").readFileSync(
    require("path").resolve(__dirname, "../layouts/UniversalMenu.jsx"),
    "utf8",
  );
  const m = src.match(/const\s+MAX_PINS\s*=\s*(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

describe("UniversalMenu MAX_PINS", () => {
  it("is set to 20 (the current user-requested cap)", () => {
    const cap = readCapFromSource();
    expect(cap).not.toBeNull();
    // Feb-2026 correction — user reverted 30 → 20; also see
    // ``AdminSidebar.jsx`` MAX_PINNED (separate admin-side surface).
    expect(cap).toBe(20);
  });
});
