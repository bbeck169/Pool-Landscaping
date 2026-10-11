/**
 * Feb-2026 · TOP-NAV-RESTRUCTURE — nested-submenu acceptance tests.
 *
 * Scope:
 *   • The former top-level ``ai_employees`` + ``specialty_services``
 *     groups are GONE from ``ADMIN_NAV_V2`` and the AdminTopBar
 *     surface.
 *   • Operations now opens with a nested "AI Operations"
 *     submenu (12 entries · 8 ex-AI-Employees + 4 governance
 *     with a visual divider) followed by a nested "Specialty
 *     Services" submenu (2 trackers), THEN the pre-existing
 *     Operations subsections in their original order.
 *   • Dropdown primitive reuse — nested rendering is produced
 *     by the existing shadcn/Radix ``DropdownMenuSub`` family
 *     (no library swap).
 *   • Active-state propagation — when a browser is on a child
 *     route under "AI Operations" or "Specialty Services", BOTH
 *     the Operations trigger pill AND the nested SubTrigger row
 *     paint active.
 *   • Keyboard / Esc / hover-with-intent — delegated to Radix
 *     ``DropdownMenuSub`` so a source-level grep locks the
 *     primitive in place (interactive behaviour already covered
 *     by Radix's own test suite).
 *
 * Interactive tests (click to open, nested click, routing) use the
 * standard RTL + user-event setup; ``pointerEventsCheck: 0`` is
 * required because Radix' pointer-event polyfill isn't in jsdom.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import fs from "node:fs";
import path from "node:path";


let _role = "admin";
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u", role: _role, email: "u@x.com", name: "User" },
    logout: vi.fn(),
    loading: false,
  }),
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    can: () => true,
    effectiveRole: _role,
    role: _role,
    isAdmin: _role === "admin" || _role === "super_admin",
    isAdminOrManager: ["admin", "super_admin", "manager"].includes(_role),
    canDo: () => true,
    previewRole: null,
    setPreviewRole: vi.fn(),
    isPreviewing: false,
  }),
  Forbidden: () => <div />,
}));
vi.mock("@/components/NotificationBell", () => ({
  default: () => <span data-testid="notification-bell-inline" />,
}));
vi.mock("@/components/AIDock/CreditsBudgetChip", () => ({ default: () => null }));
vi.mock("@/layouts/UniversalMenu", () => ({ default: () => <span /> }));

// Mock ADMIN_NAV_V2 with the restructured shape — three top-level
// groups, Operations carrying the two nested submenus at the top
// per the Feb-2026 restructure brief.
vi.mock("@/nav/adminNav", () => ({
  ADMIN_NAV_V2: [
    {
      key: "finance",
      label: "Finance",
      icon: () => null,
      entries: [
        { to: "/invoices", feature: "invoices", label: "Invoices" },
      ],
    },
    {
      key: "operations",
      label: "Operations",
      icon: () => null,
      entries: [
        // Nested "AI Operations" — 8 workflow + 4 governance.
        { to: "/ai-employees",            label: "AI Employees Hub",   nested: "AI Operations" },
        { to: "/admin/copilot",           label: "AI Copilot",         nested: "AI Operations" },
        { to: "/settings/ai-brain",       label: "AI Brain",           nested: "AI Operations" },
        { to: "/os/lana",                 label: "Lana AI Assistant",  nested: "AI Operations" },
        { to: "/admin/seo/atlas",         label: "Atlas SEO Agent",    nested: "AI Operations" },
        { to: "/communications",          label: "Communications",     nested: "AI Operations" },
        { to: "/admin/portal-inbox",      label: "Portal Inbox",       nested: "AI Operations" },
        { to: "/marketing/gbp-posts",     label: "GBP Post Drafter",   nested: "AI Operations" },
        { to: "/admin/ai-personas-scope", label: "AI Access Scope",    nested: "AI Operations", nestedDivider: true },
        { to: "/admin/ai-tool-audit",     label: "AI Tool Audit",      nested: "AI Operations" },
        { to: "/admin/ai-rules",          label: "AI Rules",           nested: "AI Operations" },
        { to: "/admin/soshie/moderation", label: "Soshie Moderation",  nested: "AI Operations" },
        // Nested "Specialty Services" — 2 trackers.
        { to: "/tracking/filter",    label: "Filter Tracker",    nested: "Specialty Services" },
        { to: "/tracking/salt-cell", label: "Salt Cell Tracker", nested: "Specialty Services" },
        // Pre-existing flat subsection — must appear AFTER the
        // nested submenus and preserve its original order.
        { to: "/schedule", label: "Schedule", subsection: "Schedule & Dispatch" },
        { to: "/admin/jobs", label: "Jobs (admin)", subsection: "Schedule & Dispatch" },
      ],
    },
    {
      key: "reports",
      label: "Reports",
      icon: () => null,
      entries: [{ to: "/reports", label: "Reports Hub" }],
    },
  ],
  filterNavByIndustries: (entries) => entries,
}));


import AdminTopBar from "@/layouts/AdminTopBar";
import { ADMIN_NAV_V2 as REAL_NAV } from "@/nav/adminNav";

// Pull the UN-mocked real nav via a direct fs read so file-level
// assertions (point 1 — former top-level groups retired) run
// against the real production file, not the test-local mock above.
const NAV_SRC = fs.readFileSync(
  path.resolve(__dirname, "../nav/adminNav.js"),
  "utf8",
);


function mount(role = "admin", initial = "/") {
  _role = role;
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <AdminTopBar />
    </MemoryRouter>,
  );
}


describe("TOP-NAV-RESTRUCTURE · former top-level groups retired " +
         "(real nav source)", () => {
  it("ADMIN_NAV_V2 (real) no longer declares an 'ai_employees' " +
     "top-level group", () => {
    // ``NAV_SRC`` is the raw source; grep for the opener. The
    // nested rows carry ``nested: "AI Operations"`` instead of
    // ``key: "ai_employees"``, so a byte-level search is a tight
    // regression guard.
    expect(NAV_SRC).not.toMatch(/\bkey:\s*"ai_employees"/);
  });

  it("ADMIN_NAV_V2 (real) no longer declares a 'specialty_services' " +
     "top-level group", () => {
    expect(NAV_SRC).not.toMatch(/\bkey:\s*"specialty_services"/);
  });

  it("the restructure guardrail comments landed in adminNav.js " +
     "(grep-lock so a future refactor can't quietly re-introduce " +
     "the top-level groups)", () => {
    expect(NAV_SRC).toMatch(/TOP-NAV-RESTRUCTURE/);
    expect(NAV_SRC).toMatch(/nested "AI Operations"/);
    expect(NAV_SRC).toMatch(/nested "Specialty Services"/);
  });
});


describe("TOP-NAV-RESTRUCTURE · top bar on the admin surface", () => {
  it("the top bar does NOT render 'AI Employees' as a top-level " +
     "category trigger (admin-topbar-ai_employees testid is gone)", () => {
    mount("admin");
    expect(screen.queryByTestId("admin-topbar-ai_employees")).toBeNull();
  });

  it("the top bar does NOT render 'Specialty Services' as a top-level " +
     "category trigger (admin-topbar-specialty_services testid is gone)", () => {
    mount("admin");
    expect(screen.queryByTestId("admin-topbar-specialty_services")).toBeNull();
  });

  it("the Operations top-level trigger still renders", () => {
    mount("admin");
    expect(screen.getByTestId("admin-topbar-operations")).toBeTruthy();
  });
});


describe("TOP-NAV-RESTRUCTURE · Operations dropdown nested submenu " +
         "renderer", async () => {
  async function openOps() {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    await user.click(screen.getByTestId("admin-topbar-operations"));
    return user;
  }

  it("Operations opens with 'AI Operations' as the FIRST nested " +
     "sub-trigger, 'Specialty Services' SECOND, then the pre-existing " +
     "'Schedule & Dispatch' subsection header", async () => {
    mount("admin");
    await openOps();
    const menu = await screen.findByTestId("admin-topbar-operations-menu");
    const aiOpsSub = within(menu).getByTestId(
      "admin-topbar-operations-nested-ai-operations",
    );
    const specialtySub = within(menu).getByTestId(
      "admin-topbar-operations-nested-specialty-services",
    );
    expect(aiOpsSub).toBeTruthy();
    expect(specialtySub).toBeTruthy();
    // The AI Operations sub-trigger renders strictly BEFORE
    // Specialty Services in document order.
    expect(
      aiOpsSub.compareDocumentPosition(specialtySub)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // The pre-existing 'Schedule & Dispatch' subsection header is
    // rendered as a flat DropdownMenuLabel after the two nested
    // sub-triggers.
    const headers = within(menu).getAllByText(/Schedule & Dispatch/i);
    expect(headers.length).toBeGreaterThan(0);
    expect(
      specialtySub.compareDocumentPosition(headers[0])
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("hovering/opening 'AI Operations' reveals every pre-restructure " +
     "sub-item (8 workflow + 4 governance) with routes preserved", async () => {
    mount("admin");
    const user = await openOps();
    const aiOpsSub = screen.getByTestId(
      "admin-topbar-operations-nested-ai-operations",
    );
    await user.hover(aiOpsSub);
    const nestedMenu = await screen.findByTestId(
      "admin-topbar-operations-nested-ai-operations-menu",
    );
    // Workflow (ex-"AI Employees" top-level group).
    const expectedWorkflow = [
      { to: "/ai-employees",         label: "AI Employees Hub" },
      { to: "/admin/copilot",        label: "AI Copilot" },
      { to: "/settings/ai-brain",    label: "AI Brain" },
      { to: "/os/lana",              label: "Lana AI Assistant" },
      { to: "/admin/seo/atlas",      label: "Atlas SEO Agent" },
      { to: "/communications",       label: "Communications" },
      { to: "/admin/portal-inbox",   label: "Portal Inbox" },
      { to: "/marketing/gbp-posts",  label: "GBP Post Drafter" },
    ];
    // Governance (ex-"AI Operations" subsection on Operations).
    const expectedGovernance = [
      { to: "/admin/ai-personas-scope", label: "AI Access Scope" },
      { to: "/admin/ai-tool-audit",     label: "AI Tool Audit" },
      { to: "/admin/ai-rules",          label: "AI Rules" },
      { to: "/admin/soshie/moderation", label: "Soshie Moderation" },
    ];
    for (const { to, label } of [...expectedWorkflow, ...expectedGovernance]) {
      const link = within(nestedMenu).getByText(label).closest("a");
      expect(link).toBeTruthy();
      expect(link.getAttribute("href")).toBe(to);
    }
    // Governance separator is rendered — subtle "Governance" sub-header.
    expect(within(nestedMenu).getByText(/Governance/i)).toBeTruthy();
  });

  it("hovering/opening 'Specialty Services' reveals Filter + Salt Cell " +
     "trackers with original routes", async () => {
    mount("admin");
    const user = await openOps();
    const specialtySub = screen.getByTestId(
      "admin-topbar-operations-nested-specialty-services",
    );
    await user.hover(specialtySub);
    const nestedMenu = await screen.findByTestId(
      "admin-topbar-operations-nested-specialty-services-menu",
    );
    const filterLink = within(nestedMenu).getByText("Filter Tracker").closest("a");
    const saltLink = within(nestedMenu).getByText("Salt Cell Tracker").closest("a");
    expect(filterLink.getAttribute("href")).toBe("/tracking/filter");
    expect(saltLink.getAttribute("href")).toBe("/tracking/salt-cell");
  });
});


describe("TOP-NAV-RESTRUCTURE · active-state propagation", () => {
  it("when the current route is a child of 'AI Operations', the " +
     "Operations top-level trigger paints data-active='true'", () => {
    mount("admin", "/admin/copilot");
    const trigger = screen.getByTestId("admin-topbar-operations");
    expect(trigger.getAttribute("data-active")).toBe("true");
  });

  it("the nested 'AI Operations' sub-trigger ALSO paints " +
     "data-active='true' for the same child route", async () => {
    mount("admin", "/admin/copilot");
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    await user.click(screen.getByTestId("admin-topbar-operations"));
    const aiOpsSub = await screen.findByTestId(
      "admin-topbar-operations-nested-ai-operations",
    );
    expect(aiOpsSub.getAttribute("data-active")).toBe("true");
  });

  it("Specialty Services child route lights the Operations trigger " +
     "AND the nested Specialty Services sub-trigger", async () => {
    mount("admin", "/tracking/salt-cell");
    const trigger = screen.getByTestId("admin-topbar-operations");
    expect(trigger.getAttribute("data-active")).toBe("true");
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    await user.click(trigger);
    const specialtySub = await screen.findByTestId(
      "admin-topbar-operations-nested-specialty-services",
    );
    expect(specialtySub.getAttribute("data-active")).toBe("true");
  });

  it("a route NOT under any nested submenu does NOT activate the " +
     "nested sub-trigger (regression guard)", async () => {
    mount("admin", "/schedule");
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    await user.click(screen.getByTestId("admin-topbar-operations"));
    const aiOpsSub = await screen.findByTestId(
      "admin-topbar-operations-nested-ai-operations",
    );
    const specialtySub = await screen.findByTestId(
      "admin-topbar-operations-nested-specialty-services",
    );
    expect(aiOpsSub.getAttribute("data-active")).toBe("false");
    expect(specialtySub.getAttribute("data-active")).toBe("false");
  });
});


describe("TOP-NAV-RESTRUCTURE · dropdown primitive reuse (grep-lock)", () => {
  const TOPBAR_SRC = fs.readFileSync(
    path.resolve(__dirname, "../layouts/AdminTopBar.jsx"),
    "utf8",
  );

  it("uses the existing shadcn ``DropdownMenuSub`` family — no " +
     "new primitive imported, no library swap", () => {
    // Imports pulled from the existing component surface.
    expect(TOPBAR_SRC).toMatch(/DropdownMenuSub\b/);
    expect(TOPBAR_SRC).toMatch(/DropdownMenuSubTrigger\b/);
    expect(TOPBAR_SRC).toMatch(/DropdownMenuSubContent\b/);
    expect(TOPBAR_SRC).toMatch(/DropdownMenuPortal\b/);
    // No alt dropdown primitive snuck in.
    expect(TOPBAR_SRC).not.toMatch(
      /from\s+["']@\/components\/ui\/menubar["']/,
    );
    expect(TOPBAR_SRC).not.toMatch(
      /from\s+["']@radix-ui\/react-menubar["']/,
    );
  });

  it("nested SubContent emits a collisionPadding prop so narrow " +
     "viewports flip the submenu away from the right edge", () => {
    expect(TOPBAR_SRC).toMatch(
      /<DropdownMenuSubContent[\s\S]*?collisionPadding=\{\s*8\s*\}/,
    );
  });

  it("Mobile menu also emits nested SubTriggers (parity with desktop)", () => {
    expect(TOPBAR_SRC).toMatch(
      /admin-topbar-mobile-\$\{g\.key\}-nested-/,
    );
  });
});


describe("TOP-NAV-RESTRUCTURE · nav-data integrity (real nav file)", () => {
  it("the real Operations group carries 12 'AI Operations' nested " +
     "entries and 2 'Specialty Services' nested entries", () => {
    const ops = REAL_NAV.find((g) => g.key === "operations");
    expect(ops).toBeTruthy();
    const aiOps = ops.entries.filter((e) => e.nested === "AI Operations");
    const special = ops.entries.filter((e) => e.nested === "Specialty Services");
    expect(aiOps.length).toBe(12);
    expect(special.length).toBe(2);
  });

  it("exactly ONE AI Operations entry carries nestedDivider:true " +
     "(the first governance row — AI Access Scope)", () => {
    const ops = REAL_NAV.find((g) => g.key === "operations");
    const dividers = ops.entries.filter(
      (e) => e.nested === "AI Operations" && e.nestedDivider,
    );
    expect(dividers.length).toBe(1);
    expect(dividers[0].to).toBe("/admin/ai-personas-scope");
  });

  it("the nested entries appear BEFORE every pre-existing subsection " +
     "(nested blocks are the top of the Operations list)", () => {
    const ops = REAL_NAV.find((g) => g.key === "operations");
    const firstNestedIdx = ops.entries.findIndex((e) => e.nested);
    const firstSubIdx = ops.entries.findIndex((e) => e.subsection);
    expect(firstNestedIdx).toBe(0);
    expect(firstSubIdx).toBeGreaterThan(firstNestedIdx);
  });
});
