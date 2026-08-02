/**
 * Phase 27 · Feb-2026 — Web avatar swap for dense layouts vitest.
 *
 * Scenarios:
 *   1. `<TechAvatar />` renders at the correct pixel size for `xs`
 *      (20px), `sm` (28px), and `md` (40px).
 *   2. `<TechAvatar />` falls back to initials when no photo URL is
 *      given.
 *   3. Dispatch Board `TechLoadStrip` row source imports and mounts
 *      `<TechAvatar />` at size `xs` for each tech row.
 *   4. Schedule card source (`TodaySchedule`) imports and mounts
 *      `<TechAvatar />` at size `xs` for jobs that carry an assigned
 *      tech identity.
 *   5. Regression guard — the old `<UserRound />` inline icon is
 *      gone from `TechLoadStrip.jsx`.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import TechAvatar, { TECH_SIZE_PX }
  from "@/components/common/TechAvatar";

const DISPATCH_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/dispatch/TechLoadStrip.jsx"),
  "utf-8",
);
const SCHEDULE_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/TodaySchedule.jsx"),
  "utf-8",
);
// Phase 27 follow-up · Feb-2026 — the /schedule route mounts
// CalendarSchedule, not TodaySchedule. The avatar swap has to land
// on the primary surface too, so we source-inspect it here.
const CALENDAR_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
  "utf-8",
);

describe("Phase 27 · TechAvatar pixel size contract", () => {
  it("exposes xs/sm/md size vocabulary matching the Phase-27 spec", () => {
    // Spec: xs~20 · sm~28 · md~40. These are the exact numbers the
    // dense layouts depend on — bumping them changes row heights.
    expect(TECH_SIZE_PX).toEqual({ xs: 20, sm: 28, md: 40 });
  });

  it("renders at 20px for size='xs'", () => {
    render(
      <TechAvatar
        user={{ name: "Luis Marquez" }}
        size="xs"
        testid="p27-xs"
      />,
    );
    const el = screen.getByTestId("p27-xs");
    // The underlying UserAvatar sets width/height inline via style.
    expect(el).toBeInTheDocument();
    expect(el.style.width).toBe("20px");
    expect(el.style.height).toBe("20px");
  });

  it("renders at 28px for size='sm' and 40px for size='md'", () => {
    render(
      <>
        <TechAvatar user={{ name: "Sam Tech" }} size="sm" testid="p27-sm" />
        <TechAvatar user={{ name: "Ali Dispatcher" }} size="md" testid="p27-md" />
      </>,
    );
    expect(screen.getByTestId("p27-sm").style.width).toBe("28px");
    expect(screen.getByTestId("p27-md").style.width).toBe("40px");
  });

  it("falls back to initials when no photo url is present", () => {
    render(
      <TechAvatar
        user={{ name: "Luis Marquez" }}
        size="xs"
        testid="p27-initials"
      />,
    );
    // UserAvatar tags the initials text with `${testid}-initials`.
    expect(screen.getByTestId("p27-initials-initials"))
      .toHaveTextContent("LM");
  });
});

describe("Phase 27 · Dispatch Board TechLoadStrip source contract", () => {
  it("imports TechAvatar from the shared common component", () => {
    expect(DISPATCH_SRC).toMatch(
      /import\s+TechAvatar\s+from\s+["']@\/components\/common\/TechAvatar["']/,
    );
  });

  it("mounts <TechAvatar size='xs' /> in each tech-load row", () => {
    expect(DISPATCH_SRC).toMatch(/<TechAvatar[\s\S]*?size=["']xs["']/);
  });

  it("attaches a per-tech testid to the avatar for downstream assertions", () => {
    expect(DISPATCH_SRC).toMatch(/testid=\{`dispatch-tech-avatar-\$\{[^}]+\}`\}/);
  });

  it("removed the pre-Phase-27 <UserRound /> inline icon", () => {
    // The lucide UserRound icon was the placeholder Phase-17 tech
    // representation. Regression guard so future refactors don't
    // silently re-import it. We only check the actual runtime code
    // (imports + JSX rendering), NOT the header JSDoc which
    // deliberately mentions the pre-Phase-27 name.
    expect(DISPATCH_SRC).not.toMatch(/UserRound[\s,}]*\s*from ["']lucide-react["']/);
    expect(DISPATCH_SRC).not.toMatch(/import\s*\{[^}]*UserRound[^}]*\}\s*from/);
    // JSX open-tag (a `<` followed immediately by capital U, not
    // a `//` line comment).
    const codeLines = DISPATCH_SRC
      .split("\n")
      .filter((line) => !line.trim().startsWith("//"))
      .join("\n");
    expect(codeLines).not.toMatch(/<UserRound[\s/>]/);
  });
});

describe("Phase 27 · Schedule card source contract", () => {
  it("TodaySchedule imports the shared TechAvatar", () => {
    expect(SCHEDULE_SRC).toMatch(
      /import\s+TechAvatar\s+from\s+["']@\/components\/common\/TechAvatar["']/,
    );
  });

  it("TodaySchedule mounts <TechAvatar size='xs' /> in the card header", () => {
    expect(SCHEDULE_SRC).toMatch(/<TechAvatar[\s\S]*?size=["']xs["']/);
  });

  it("card avatar carries a per-job testid so admins can assert on it", () => {
    // Pattern: `schedule-card-tech-avatar-${j.id}` in a template
    // string literal.
    expect(SCHEDULE_SRC).toMatch(
      /schedule-card-tech-avatar-\$\{j\.id\}/,
    );
  });
});

describe("Phase 27 follow-up · Primary /schedule (CalendarSchedule) source contract", () => {
  it("CalendarSchedule imports the shared TechAvatar", () => {
    expect(CALENDAR_SRC).toMatch(
      /import\s+TechAvatar\s+from\s+["']@\/components\/common\/TechAvatar["']/,
    );
  });

  it("CalendarSchedule mounts <TechAvatar size='xs' /> inside its per-job card", () => {
    expect(CALENDAR_SRC).toMatch(/<TechAvatar[\s\S]*?size=["']xs["']/);
  });

  it("CalendarSchedule attaches schedule-card-tech-avatar-${j.id} testid", () => {
    // Same testid pattern as TodaySchedule so the tester selector
    // `[data-testid^=\"schedule-card-tech-avatar-\"]` resolves on
    // whichever surface is currently rendering.
    expect(CALENDAR_SRC).toMatch(
      /schedule-card-tech-avatar-\$\{j\.id\}/,
    );
  });

  it("CalendarSchedule avatar is guarded behind a technician-identity conditional", () => {
    // Same guard shape as TodaySchedule — no chip when the job has
    // no assigned tech.
    expect(CALENDAR_SRC).toMatch(
      /j\.technician_name\s*\|\|\s*j\.assigned_technician_name/,
    );
  });
});
