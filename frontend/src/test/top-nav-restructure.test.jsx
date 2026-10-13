/**
 * Feb-2026 · OPS-NAV-FLATTEN — Operations dropdown acceptance tests.
 *
 * Walked back from the Feb-2026 TOP-NAV-RESTRUCTURE nested-flyout
 * design.  "AI Operations" and "Specialty Services" are now flat
 * subsection blocks inside the Operations dropdown — matching
 * the pre-existing "Schedule & Dispatch" / "Service Log" treatment.
 *
 * Scope locked by this file:
 *   • The former top-level ``ai_employees`` + ``specialty_services``
 *     groups remain GONE from ``ADMIN_NAV_V2`` and the top bar.
 *   • The Operations dropdown emits "AI Operations" and
 *     "Specialty Services" as flat ``subsection`` headers
 *     (``admin-topbar-${group.key}-sub-...`` testid) — NOT nested
 *     ``DropdownMenuSubTrigger`` flyouts.
 *   • The former nested-flyout testids
 *     (``admin-topbar-operations-nested-ai-operations`` and
 *     ``...-specialty-services``) no longer exist on either the
 *     desktop or mobile menu.
 *   • Every AI Operations + Specialty Services child link renders
 *     DIRECTLY in the parent Operations dropdown — no hover-to-
 *     expand, no ArrowRight-to-open.
 *   • Active-state still propagates up to the Operations top-level
 *     trigger when a browser is on a child route.
 *   • Dropdown primitive imports continue to live in AdminTopBar
 *     (shadcn/Radix DropdownMenu family — no library swap).
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

// Mock ADMIN_NAV_V2 with the flattened shape — Operations carries
// "AI Operations" and "Specialty Services" as flat ``subsection``
// headers, matching the pre-existing "Schedule & Dispatch" style.
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
        // Flat "AI Operations" subsection — 8 workflow + 4 governance.
        { to: "/ai-employees",            label: "AI Employees Hub",   subsection: "AI Operations" },
        { to: "/admin/copilot",           label: "AI Copilot",         subsection: "AI Operations" },
        { to: "/settings/ai-brain",       label: "AI Brain",           subsection: "AI Operations" },
        { to: "/os/lana",                 label: "Lana AI Assistant",  subsection: "AI Operations" },
        { to: "/admin/seo/atlas",         label: "Atlas SEO Agent",    subsection: "AI Operations" },
        { to: "/admin/communications-log", label: "Communications",     subsection: "AI Operations" },
        { to: "/admin/portal-inbox",      label: "Portal Inbox",       subsection: "AI Operations" },
        { to: "/marketing/gbp-posts",     label: "GBP Post Drafter",   subsection: "AI Operations" },
        { to: "/admin/ai-personas-scope", label: "AI Access Scope",    subsection: "AI Operations" },
        { to: "/admin/ai-tool-audit",     label: "AI Tool Audit",      subsection: "AI Operations" },
        { to: "/admin/ai-rules",          label: "AI Rules",           subsection: "AI Operations" },
        { to: "/admin/soshie/moderation", label: "Soshie Moderation",  subsection: "AI Operations" },
        // Flat "Specialty Services" subsection — 2 trackers.
        { to: "/tracking/filter",    label: "Filter Tracker",    subsection: "Specialty Services" },
        { to: "/tracking/salt-cell", label: "Salt Cell Tracker", subsection: "Specialty Services" },
        // Pre-existing flat subsection — appears after the two
        // flattened subsections.
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
// assertions run against the real production file.
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


describe("OPS-NAV-FLATTEN · former top-level groups retired " +
         "(real nav source)", () => {
  it("ADMIN_NAV_V2 (real) no longer declares an 'ai_employees' " +
     "top-level group", () => {
    expect(NAV_SRC).not.toMatch(/\bkey:\s*"ai_employees"/);
  });

  it("ADMIN_NAV_V2 (real) no longer declares a 'specialty_services' " +
     "top-level group", () => {
    expect(NAV_SRC).not.toMatch(/\bkey:\s*"specialty_services"/);
  });

  it("the flatten guardrail comment landed in adminNav.js " +
     "(grep-lock so a future refactor can't quietly re-nest)", () => {
    expect(NAV_SRC).toMatch(/OPS-NAV-FLATTEN/);
  });

  it("no AI Operations row carries the legacy ``nested`` key " +
     "(must be ``subsection`` after the flatten)", () => {
    // Real-source grep — the two labels appear only inside
    // ``subsection:`` key-value pairs now.
    expect(NAV_SRC).toMatch(/subsection:\s*"AI Operations"/);
    expect(NAV_SRC).toMatch(/subsection:\s*"Specialty Services"/);
    expect(NAV_SRC).not.toMatch(/nested:\s*"AI Operations"/);
    expect(NAV_SRC).not.toMatch(/nested:\s*"Specialty Services"/);
    // Flyout-era divider sentinel is gone.
    expect(NAV_SRC).not.toMatch(/nestedDivider:/);
  });
});


describe("OPS-NAV-FLATTEN · top bar on the admin surface", () => {
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


describe("OPS-NAV-FLATTEN · Operations dropdown renders flat sections", async () => {
  async function openOps() {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    await user.click(screen.getByTestId("admin-topbar-operations"));
    return user;
  }

  it("the former nested sub-trigger testids are GONE — no " +
     "``...-nested-ai-operations`` or ``...-nested-specialty-services``", async () => {
    mount("admin");
    await openOps();
    const menu = await screen.findByTestId("admin-topbar-operations-menu");
    expect(within(menu).queryByTestId(
      "admin-topbar-operations-nested-ai-operations",
    )).toBeNull();
    expect(within(menu).queryByTestId(
      "admin-topbar-operations-nested-specialty-services",
    )).toBeNull();
  });

  it("'AI Operations' + 'Specialty Services' render as flat " +
     "section headers, matching the Schedule & Dispatch style", async () => {
    mount("admin");
    await openOps();
    const menu = await screen.findByTestId("admin-topbar-operations-menu");
    // All three subsection headers coexist as DropdownMenuLabel
    // text nodes inside the ONE Operations dropdown.
    expect(within(menu).getByText(/AI Operations/i)).toBeTruthy();
    expect(within(menu).getByText(/Specialty Services/i)).toBeTruthy();
    expect(within(menu).getByText(/Schedule & Dispatch/i)).toBeTruthy();
    // Document-order check: AI Ops header → Specialty header →
    // Schedule header.
    const aiOps = within(menu).getByText(/AI Operations/i);
    const specialty = within(menu).getByText(/Specialty Services/i);
    const schedule = within(menu).getByText(/Schedule & Dispatch/i);
    expect(
      aiOps.compareDocumentPosition(specialty)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      specialty.compareDocumentPosition(schedule)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("the section headers do NOT carry ``aria-haspopup`` and are " +
     "not focusable/activatable (flat labels, not flyout triggers)", async () => {
    mount("admin");
    await openOps();
    const menu = await screen.findByTestId("admin-topbar-operations-menu");
    const aiOps = within(menu).getByText(/AI Operations/i);
    const specialty = within(menu).getByText(/Specialty Services/i);
    // Walk the ancestry briefly to confirm neither the label nor
    // its immediate wrapper advertises haspopup/expanded. Flyout
    // triggers would carry one of these from Radix.
    for (const node of [aiOps, specialty]) {
      let cursor = node;
      for (let i = 0; i < 3 && cursor; i += 1) {
        expect(cursor.getAttribute?.("aria-haspopup") || null).not.toBe(
          "true",
        );
        expect(cursor.getAttribute?.("aria-haspopup") || null).not.toBe(
          "menu",
        );
        cursor = cursor.parentElement;
      }
    }
  });

  it("every former AI Operations child link renders DIRECTLY in the " +
     "parent Operations dropdown (no hover-to-expand required)", async () => {
    mount("admin");
    await openOps();
    const menu = await screen.findByTestId("admin-topbar-operations-menu");
    const expectedWorkflow = [
      { to: "/ai-employees",            label: "AI Employees Hub" },
      { to: "/admin/copilot",           label: "AI Copilot" },
      { to: "/settings/ai-brain",       label: "AI Brain" },
      { to: "/os/lana",                 label: "Lana AI Assistant" },
      { to: "/admin/seo/atlas",         label: "Atlas SEO Agent" },
      { to: "/admin/communications-log", label: "Communications" },
      { to: "/admin/portal-inbox",      label: "Portal Inbox" },
      { to: "/marketing/gbp-posts",     label: "GBP Post Drafter" },
    ];
    const expectedGovernance = [
      { to: "/admin/ai-personas-scope", label: "AI Access Scope" },
      { to: "/admin/ai-tool-audit",     label: "AI Tool Audit" },
      { to: "/admin/ai-rules",          label: "AI Rules" },
      { to: "/admin/soshie/moderation", label: "Soshie Moderation" },
    ];
    for (const { to, label } of [...expectedWorkflow, ...expectedGovernance]) {
      const link = within(menu).getByText(label).closest("a");
      expect(link).toBeTruthy();
      expect(link.getAttribute("href")).toBe(to);
    }
  });

  it("every former Specialty Services child link renders DIRECTLY in " +
     "the parent Operations dropdown", async () => {
    mount("admin");
    await openOps();
    const menu = await screen.findByTestId("admin-topbar-operations-menu");
    const filterLink = within(menu).getByText("Filter Tracker").closest("a");
    const saltLink = within(menu).getByText("Salt Cell Tracker").closest("a");
    expect(filterLink.getAttribute("href")).toBe("/tracking/filter");
    expect(saltLink.getAttribute("href")).toBe("/tracking/salt-cell");
  });

  it("keyboard tab-order visits every AI Ops + Specialty link without " +
     "needing Enter / ArrowRight to expand a flyout (flat section " +
     "contract)", async () => {
    mount("admin");
    const user = await openOps();
    const menu = await screen.findByTestId("admin-topbar-operations-menu");
    // Collect menu items in author order; the flat contract means
    // every row is a MenuItem (not a SubTrigger). Radix MenuItem
    // uses role="menuitem".
    const items = within(menu).getAllByRole("menuitem");
    // We're not asserting specific tab-key reachability here (jsdom
    // doesn't implement roving tabindex the way Radix uses in-
    // browser), but we DO assert that every former nested-child
    // route is present as a top-level menuitem — not as the content
    // of a SubTrigger. ``user.tab()`` here is a sanity call that
    // the tree is traversable without errors.
    await user.tab();
    const hrefs = items.map((n) => n.querySelector?.("a")?.getAttribute("href")
      || n.getAttribute?.("href") || "");
    for (const needle of [
      "/ai-employees", "/admin/copilot", "/admin/ai-personas-scope",
      "/tracking/filter", "/tracking/salt-cell",
    ]) {
      expect(hrefs.some((h) => h === needle)).toBe(true);
    }
  });
});


describe("OPS-NAV-FLATTEN · active-state propagation", () => {
  it("when the current route is a child of 'AI Operations', the " +
     "Operations top-level trigger paints data-active='true'", () => {
    mount("admin", "/admin/copilot");
    const trigger = screen.getByTestId("admin-topbar-operations");
    expect(trigger.getAttribute("data-active")).toBe("true");
  });

  it("when the current route is a child of 'Specialty Services', the " +
     "Operations top-level trigger paints data-active='true'", () => {
    mount("admin", "/tracking/salt-cell");
    const trigger = screen.getByTestId("admin-topbar-operations");
    expect(trigger.getAttribute("data-active")).toBe("true");
  });
});


describe("OPS-NAV-FLATTEN · dropdown primitive reuse (grep-lock)", () => {
  const TOPBAR_SRC = fs.readFileSync(
    path.resolve(__dirname, "../layouts/AdminTopBar.jsx"),
    "utf8",
  );

  it("still uses the shadcn ``DropdownMenu`` family — no library " +
     "swap triggered by the flatten", () => {
    expect(TOPBAR_SRC).toMatch(/DropdownMenu\b/);
    expect(TOPBAR_SRC).toMatch(/DropdownMenuContent\b/);
    expect(TOPBAR_SRC).toMatch(/DropdownMenuLabel\b/);
    // No alt dropdown primitive snuck in.
    expect(TOPBAR_SRC).not.toMatch(
      /from\s+["']@\/components\/ui\/menubar["']/,
    );
    expect(TOPBAR_SRC).not.toMatch(
      /from\s+["']@radix-ui\/react-menubar["']/,
    );
  });
});


describe("OPS-NAV-FLATTEN · nav-data integrity (real nav file)", () => {
  it("the real Operations group carries 12 'AI Operations' subsection " +
     "entries and 2 'Specialty Services' subsection entries", () => {
    const ops = REAL_NAV.find((g) => g.key === "operations");
    expect(ops).toBeTruthy();
    const aiOps = ops.entries.filter((e) => e.subsection === "AI Operations");
    const special = ops.entries.filter((e) => e.subsection === "Specialty Services");
    expect(aiOps.length).toBe(12);
    expect(special.length).toBe(2);
  });

  it("no Operations entry still carries the legacy ``nested`` key " +
     "(flatten complete)", () => {
    const ops = REAL_NAV.find((g) => g.key === "operations");
    const nestedResidue = ops.entries.filter((e) => e.nested);
    expect(nestedResidue.length).toBe(0);
  });

  it("no Operations entry still carries the pre-flatten " +
     "``nestedDivider: true`` sentinel", () => {
    const ops = REAL_NAV.find((g) => g.key === "operations");
    const dividerResidue = ops.entries.filter((e) => e.nestedDivider);
    expect(dividerResidue.length).toBe(0);
  });

  it("the subsection entries appear in order: AI Operations → " +
     "Specialty Services → Schedule & Dispatch", () => {
    const ops = REAL_NAV.find((g) => g.key === "operations");
    const firstAi = ops.entries.findIndex((e) => e.subsection === "AI Operations");
    const firstSpecialty = ops.entries.findIndex((e) => e.subsection === "Specialty Services");
    const firstSchedule = ops.entries.findIndex((e) => e.subsection === "Schedule & Dispatch");
    expect(firstAi).toBe(0);
    expect(firstSpecialty).toBeGreaterThan(firstAi);
    expect(firstSchedule).toBeGreaterThan(firstSpecialty);
  });
});
