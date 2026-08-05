/**
 * Task OO regression guard · Feb 2026.
 *
 * The 3 P1 admin pages (Users, Tags, Service Reports) originally
 * shipped with `useEffect(load, [])` where `load` was an arrow
 * function without braces — it implicitly returned the Promise from
 * `api.get(...).then(...)`. React interpreted that Promise as a
 * cleanup function and on effect re-run/unmount blew up with
 * "destroy is not a function" (Promises don't have `.destroy`).
 *
 * These tests mount every P1 page + JobsList and assert render does
 * not throw. Adds a regression net so a similar arrow-body slip on
 * any new admin bulk list page fails at Jest time instead of white-
 * screening in prod.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";

// This file predates the repo's Vitest migration; kept in Jest
// syntax and no longer run by Vitest (the Vitest runner errors out
// on ``jest is not defined`` and skips the file). The mount-safety
// regressions this file was designed to catch on the P1 admin pages
// (Users / Tags / Service Reports) are covered elsewhere by end-
// to-end + smoke tests. The 3 new Task RR/SS Phase 2 admin surfaces
// have their own smoke-import coverage in
// ``task-rr-ss-p2-mount-safety.test.jsx``.
// Mock react-router-dom hooks used by the pages under test. v7 ships
// as ESM and Jest can't resolve it under CJS test transform without
// extra config — mocking is faster and covers exactly what we need.
vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useLocation: () => ({ pathname: "/", search: "", hash: "" }),
  useParams: () => ({}),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
  Link: ({ children, ...rest }) => {
    const React = require("react");
    return React.createElement("a", rest, children);
  },
  NavLink: ({ children, ...rest }) => {
    const React = require("react");
    return React.createElement("a", rest, children);
  },
  Navigate: () => null,
}));

// Mock the api module (all pages call api.get on mount). Use plain
// functions rather than vi.fn() so the mock survives jest's
// per-test mock-reset heuristics — we don't need call assertions,
// just non-throwing promise returns.
vi.mock("@/api", () => ({
  api: {
    get: () => Promise.resolve([]),
    post: () => Promise.resolve({ ok: true }),
    patch: () => Promise.resolve({ ok: true }),
    put: () => Promise.resolve({ ok: true }),
    delete: () => Promise.resolve({ ok: true }),
  },
}));

// Mock sonner (some pages import `toast` at top level).
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(),
  { success: vi.fn(), error: vi.fn() }) }));

// Mock lucide-react icons to plain <span> so we don't have to bring
// in the SVG registry.
vi.mock("lucide-react", () => {
  const React = require("react");
  return new Proxy({}, {
    get: () => (props) => React.createElement("span", props),
  });
});

// Mock the theme + colors module. Pages import `colors.*` scalars.
vi.mock("@/theme", () => ({
  colors: new Proxy({}, { get: () => "#000" }),
}));

function mountsCleanly(Page, name) {
  const errors = [];
  const origError = console.error;
  console.error = (...args) => { errors.push(args.join(" ")); };
  try {
    expect(() => render(<Page />)).not.toThrow();
    // React logs "The above error occurred" via console.error when a
    // child throws — surface those too.
    const destroyErr = errors.find((e) => /destroy is not a function/.test(e));
    expect(destroyErr).toBeUndefined();
    const uncaught = errors.find((e) => /Uncaught|Error:/.test(e));
    expect(uncaught).toBeUndefined();
  } finally {
    console.error = origError;
    cleanup();
  }
}

// Phase 41.5 · Feb-2026 — static imports hoisted to the top of the
// file so vitest's dynamic-import machinery isn't invoked inside
// each ``it`` (which triggered 5s timeouts under the ``forks`` pool
// while the transitive dep graph resolved). ``vi.mock`` hoists
// AHEAD of these imports at compile time.
import AdminUsersList from "@/pages/admin/AdminUsersList";
import AdminTagsList from "@/pages/admin/AdminTagsList";
import AdminServiceReportsList from "@/pages/admin/AdminServiceReportsList";
import AdminTimeEntriesList from "@/pages/admin/AdminTimeEntriesList";
import AdminReviewsPage from "@/pages/admin/AdminReviewsPage";
import ReflowHistoryPage from "@/pages/admin/ReflowHistoryPage";
import JobsList from "@/pages/jobs/JobsList";

describe("P1 admin bulk list pages — mount-safety regression guard", () => {
  it("AdminUsersList mounts without 'destroy is not a function'", () => {
    mountsCleanly(AdminUsersList, "AdminUsersList");
  });
  it("AdminTagsList mounts without 'destroy is not a function'", () => {
    mountsCleanly(AdminTagsList, "AdminTagsList");
  });
  it("AdminServiceReportsList mounts without 'destroy is not a function'", () => {
    mountsCleanly(AdminServiceReportsList, "AdminServiceReportsList");
  });
  it("AdminTimeEntriesList mounts cleanly (already-working reference)", () => {
    mountsCleanly(AdminTimeEntriesList, "AdminTimeEntriesList");
  });
  it("AdminReviewsPage mounts cleanly (already-working reference)", () => {
    mountsCleanly(AdminReviewsPage, "AdminReviewsPage");
  });
  it("ReflowHistoryPage mounts cleanly (already-working reference)", () => {
    mountsCleanly(ReflowHistoryPage, "ReflowHistoryPage");
  });
  it("JobsList mounts cleanly (P0 reference)", () => {
    mountsCleanly(JobsList, "JobsList");
  });
});
