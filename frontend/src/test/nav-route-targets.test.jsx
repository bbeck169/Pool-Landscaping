/**
 * Feb-2026 · Nav Tester Follow-ups · Fix 2
 *
 * Regression guard — every ``to:`` / ``href:`` target emitted by
 * the admin nav MUST resolve to a defined ``<Route>`` in
 * ``frontend/src/App.js``.  Prior to this guard a stale target
 * (``/communications``) silently rendered the 404 catch-all
 * instead of the real page (``/admin/communications-log``).
 *
 * Implementation:
 *   1. Parse ``App.js`` with a brace-balanced JSX walker.  For
 *      every ``<Route path="X" ...>`` encountered, resolve the
 *      full path by composing with the parent's full path (nested
 *      ``<Route>`` children inherit their parent's base when
 *      ``X`` is relative).
 *   2. Build a regex per resolved path (``:param`` → ``[^/]+``,
 *      ``*`` → ``.*``), skipping the top-level ``/*`` catch-all.
 *   3. For every nav ``to:`` across ``ADMIN_NAV_V2``, strip the
 *      query / hash and assert at least one route regex matches.
 *
 * Scope: ``ADMIN_NAV_V2`` only — portal + public routes have
 * their own guards elsewhere.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { ADMIN_NAV_V2 } from "@/nav/adminNav";


const APP_SRC = fs.readFileSync(
  path.resolve(__dirname, "../App.js"),
  "utf8",
);


function resolveRoutes(src) {
  // Walk the source and emit a Set of resolved full paths by
  // tracking a stack of parent paths.  Brace-balanced attribute
  // parsing is required because ``element={<Foo />}`` contains a
  // ``/>`` that must NOT be treated as the Route's own self-close.
  const stack = ["/"];
  const routes = new Set();
  const n = src.length;
  let i = 0;
  while (i < n) {
    const close = src.indexOf("</Route>", i);
    let open = src.indexOf("<Route", i);
    // Skip ``<Routes>`` (plural).
    while (open !== -1 && src.substr(open, 7) === "<Routes") {
      open = src.indexOf("<Route", open + 1);
    }
    if (close === -1 && open === -1) break;
    if (open !== -1 && (close === -1 || open < close)) {
      // Opener — scan for the tag's closing ``>`` with brace +
      // string awareness.
      let j = open + "<Route".length;
      let depth = 0;
      let inStr = false;
      let strCh = "";
      while (j < n) {
        const ch = src[j];
        if (inStr) {
          if (ch === "\\") { j += 2; continue; }
          if (ch === strCh) { inStr = false; j += 1; continue; }
          j += 1; continue;
        }
        if (ch === '"' || ch === "'") { inStr = true; strCh = ch; j += 1; continue; }
        if (ch === "{") depth += 1;
        else if (ch === "}") depth -= 1;
        else if (ch === ">" && depth === 0) {
          const tagText = src.slice(open, j + 1);
          const selfClosed = /\/\s*>$/.test(tagText.trimEnd());
          const pm = /\bpath="([^"]+)"/.exec(tagText);
          if (pm) {
            const rel = pm[1];
            const base = stack[stack.length - 1];
            let full;
            if (rel.startsWith("/")) full = rel;
            else if (base === "/") full = "/" + rel;
            else full = base.replace(/\/$/, "") + "/" + rel;
            routes.add(full);
            if (!selfClosed) stack.push(full);
          } else {
            // ``<Route index />`` or similar — push parent again
            // so the matching close pops without unbalancing.
            if (!selfClosed) stack.push(stack[stack.length - 1]);
          }
          i = j + 1;
          break;
        }
        j += 1;
      }
      if (j >= n) break;
    } else {
      // Closer.
      if (stack.length > 1) stack.pop();
      i = close + "</Route>".length;
    }
  }
  routes.delete("/*");
  return routes;
}


function toRegex(route) {
  // Escape, then convert :param → [^/]+ and * → .*
  const escaped = route.replace(/[.+?^${}()|[\]\\]/g, "\\$&");
  const paramed = escaped.replace(/:[A-Za-z_][A-Za-z0-9_]*/g, "[^/]+");
  const wildcarded = paramed.replace(/\\\*/g, ".*");
  return new RegExp("^" + wildcarded + "$");
}


const ROUTES = resolveRoutes(APP_SRC);
const ROUTE_REGEXES = [...ROUTES].map((r) => [r, toRegex(r)]);


function collectNavTargets() {
  // Flatten ADMIN_NAV_V2 into a list of {to, label, group} tuples.
  const out = [];
  for (const g of ADMIN_NAV_V2) {
    for (const e of g.entries) {
      if (typeof e.to === "string") {
        out.push({ to: e.to, label: e.label, group: g.label });
      }
    }
  }
  return out;
}


describe("nav-route-targets · every admin nav target resolves to a " +
         "real <Route> in App.js", () => {
  const targets = collectNavTargets();

  it("resolveRoutes extracted a non-trivial route set from App.js", () => {
    expect(ROUTES.size).toBeGreaterThan(100);
    // Sanity probes — these are known-stable top-level + nested
    // routes.  If any of these flip to MISS the parser is broken,
    // not the nav.
    for (const probe of [
      "/customers",
      "/settings/integrations",
      "/admin/communications-log",
      "/os/dashboard",
      "/reports/revenue-by-service",
    ]) {
      const hit = ROUTE_REGEXES.some(([, rx]) => rx.test(probe));
      expect(hit, `probe ${probe} failed — parser regression?`).toBe(true);
    }
  });

  it("ADMIN_NAV_V2 yields at least 150 nav targets", () => {
    expect(targets.length).toBeGreaterThan(150);
  });

  it("ZERO orphan targets — every nav ``to:`` matches a defined " +
     "<Route> (query / hash stripped before match)", () => {
    const orphans = [];
    for (const t of targets) {
      if (t.to.startsWith("http")) continue; // External link.
      const pathname = t.to.split("?")[0].split("#")[0];
      const matched = ROUTE_REGEXES.some(([, rx]) => rx.test(pathname));
      if (!matched) orphans.push(t);
    }
    expect(
      orphans,
      "orphan nav targets found:\n" +
      orphans
        .map((o) => `  ${o.group} > ${o.label} → ${o.to}`)
        .join("\n"),
    ).toEqual([]);
  });

  it("the Feb-2026 Fix 2 remediations landed — no stale target " +
     "survives on the known-bad list", () => {
    const stale = [
      "/communications",
      "/gbp/posts",
      "/gbp/reviews",
      "/gbp/business",
      "/reports/revenue-slices",
    ];
    const bad = targets.filter((t) => stale.includes(t.to));
    expect(
      bad,
      `stale nav target still shipping: ${bad.map((b) => b.to).join(", ")}`,
    ).toEqual([]);
  });

  it("the Feb-2026 Fix 2 new targets ARE present in the nav", () => {
    const toSet = new Set(targets.map((t) => t.to));
    expect(toSet.has("/admin/communications-log")).toBe(true);
    expect(toSet.has("/gbp?tab=posts")).toBe(true);
    expect(toSet.has("/gbp?tab=reviews")).toBe(true);
    expect(toSet.has("/gbp?tab=business")).toBe(true);
    expect(toSet.has("/reports/revenue-by-service")).toBe(true);
  });
});
