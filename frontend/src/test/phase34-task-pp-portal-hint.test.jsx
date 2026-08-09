/**
 * Task PP · Feb 2026 — regression test for the Portal Service Reports
 * "Click any visit to open details" instructional hint.
 *
 * Verifies:
 *   1. Hint renders (with testid `service-reports-click-hint`) when
 *      the fetch returns at least one report.
 *   2. Hint is absent when the fetch returns an empty list — the
 *      empty-state EmptyState component handles that case instead.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor, screen } from "@testing-library/react";

// Same mocking playbook as the mount-safety suite.
vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useLocation: () => ({ pathname: "/", search: "", hash: "" }),
  useParams: () => ({}),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
  Link: ({ children, ...rest }) => {
    const React = require("react");
    return React.createElement("a", rest, children);
  },
  Navigate: () => null,
}));

vi.mock("lucide-react", () => {
  const React = require("react");
  const _passThrough = new Set([
    "then", "catch", "finally", "$$typeof", "__esModule",
    Symbol.iterator, Symbol.toPrimitive, Symbol.toStringTag,
  ]);
  const _Component = (props) => React.createElement("span", props);
  return new Proxy({ __esModule: true, default: _Component }, {
    has: (_target, prop) => !_passThrough.has(prop) && typeof prop !== "symbol",
    get: (target, prop) => {
      if (prop === "__esModule") return true;
      if (typeof prop === "symbol") return undefined;
      if (_passThrough.has(prop)) return undefined;
      return _Component;
    },
    ownKeys: () => ["__esModule", "default"],
    getOwnPropertyDescriptor: (target, prop) => {
      if (prop === "__esModule") return { value: true, enumerable: false, configurable: true };
      if (prop === "default") return { value: _Component, enumerable: true, configurable: true };
      return { value: _Component, enumerable: true, configurable: true };
    },
  });
});

vi.mock("@/theme", () => ({
  colors: new Proxy({}, {
    get: (_target, prop) => {
      if (typeof prop === "symbol") return undefined;
      if (prop === "then" || prop === "catch" || prop === "finally") return undefined;
      return "#000";
    },
  }),
}));

// Mutable holder — swap the fetch response between tests.
const apiState = { rows: [] };
vi.mock("@/api", () => ({
  api: {
    get: (path) => {
      if (path && path.includes("service-reports")) {
        return Promise.resolve(apiState.rows);
      }
      return Promise.resolve([]);
    },
  },
}));

// Portal page also uses the shared portal auth hook. Mock it so
// authenticated-state assumptions don't blow up the render.
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "customer" }, loading: false }),
}));

// Phase 41.5 · Feb-2026 — static top-level imports (see the
// admin-page mount-safety file for the timeout rationale under
// vitest's ``forks`` pool).
import { PortalServiceReports } from "@/pages/portal/PortalServiceReports";

describe("Task PP · portal service-reports click hint", () => {
  afterEach(() => { cleanup(); apiState.rows = []; });

  it("renders the click hint when at least one visit is returned", async () => {
    apiState.rows = [{
      id: "r1",
      job_id: "j1",
      job_title: "Weekly service",
      submitted_at: "2026-02-27T10:00:00Z",
      scheduled_start: "2026-02-27T09:00:00Z",
      chemicals: {},
      photos: [],
    }];
    render(<PortalServiceReports />);
    const hint = await screen.findByTestId("service-reports-click-hint",
                                                    {}, { timeout: 3000 });
    expect(hint).toBeTruthy();
    expect(hint.textContent).toMatch(/click any visit/i);
  });

  it("does NOT render the click hint when the list is empty", async () => {
    apiState.rows = [];
    render(<PortalServiceReports />);
    // Wait a tick so the effect resolves and swaps to empty-state.
    await waitFor(() => {
      // grouped container is only rendered when rows.length > 0
      expect(
        screen.queryByTestId("portal-service-reports-grouped")
      ).toBeNull();
    });
    expect(
      screen.queryByTestId("service-reports-click-hint")
    ).toBeNull();
  });
});
