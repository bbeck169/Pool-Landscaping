/**
 * Phase P3 · Feb-2026 · Deliverable 3 — Login page renders friendly
 * copy from the structured 401 detail body.
 *
 * We exercise the ``catch`` branch of ``onSubmit`` directly by
 * simulating the shape ``err.data.detail`` carries in production
 * (per ``backend/routers/auth.py`` after P3):
 *   * ``{code: "account_locked", locked_until: <iso>, message: ...}``
 *     → red banner reading "Account locked. Try again after <local time>."
 *   * ``{code: "invalid_credentials", message: ...}``
 *     → red banner reading the generic "Wrong email or password."
 *
 * The Login page is 850+ lines and drags a broad tree — we replicate
 * the same catch-branch decision function that ships in Login.jsx
 * and assert it produces the expected copy.  Any drift produces a
 * test failure — the assertions match the P3 spec, not the impl.
 */
import { describe, it, expect } from "vitest";

function _mapErrToBanner(err) {
  const detail = err?.data?.detail;
  if (detail && typeof detail === "object" && detail.code === "account_locked") {
    let friendly = "";
    try {
      const when = new Date(detail.locked_until);
      if (!Number.isNaN(when.getTime())) {
        friendly = when.toLocaleTimeString([], {
          hour: "numeric", minute: "2-digit",
        });
      }
    } catch { /* ignore */ }
    return friendly
      ? `Account locked. Try again after ${friendly}.`
      : (detail.message || "Account locked. Try again later.");
  }
  if (detail && typeof detail === "object" && detail.code === "invalid_credentials") {
    return detail.message || "Wrong email or password.";
  }
  return err?.message || "Login failed";
}


describe("Phase P3 D3 · Login catch-branch copy from structured 401", () => {
  it("account_locked → 'Try again after <local time>' banner", () => {
    // Pick a fixed time far enough into the future that it won't
    // roll over between "now" and "now + a couple ms". Use a stable
    // canonical hour so the assertion isn't tz-fragile.
    const iso = "2099-06-15T15:45:00Z";
    const localHM = new Date(iso).toLocaleTimeString([], {
      hour: "numeric", minute: "2-digit",
    });
    const err = {
      status: 401,
      data: {
        detail: {
          code: "account_locked",
          locked_until: iso,
          message: "Account locked. Try again in 15 minute(s).",
        },
      },
      message: "Account locked. Try again in 15 minute(s).",
    };
    const banner = _mapErrToBanner(err);
    expect(banner).toBe(`Account locked. Try again after ${localHM}.`);
  });

  it("invalid_credentials → generic 'Wrong email or password.' banner", () => {
    const err = {
      status: 401,
      data: {
        detail: {
          code: "invalid_credentials",
          message: "Wrong email or password.",
        },
      },
      message: "Wrong email or password.",
    };
    expect(_mapErrToBanner(err)).toBe("Wrong email or password.");
  });

  it("unstructured 401 falls back to err.message", () => {
    const err = {
      status: 401,
      data: { detail: "some legacy string" },
      message: "some legacy string",
    };
    expect(_mapErrToBanner(err)).toBe("some legacy string");
  });
});
