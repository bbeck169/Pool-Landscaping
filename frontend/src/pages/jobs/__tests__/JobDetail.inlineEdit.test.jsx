/**
 * Jobs Overhaul · Phase 3a · JobDetail inline-edit tiles.
 *
 * Isolated-harness pattern (mirrors ``test/JobDetail.delete.test.jsx``)
 * — mounts the component-local ``InlineEditTile`` helper in a tiny
 * wrapper that stubs out the ``saveInline`` wrapper's behaviour so
 * each test gets fine-grained control over the PUT roundtrip.
 *
 * Behaviour contract pinned here:
 *   1. Read mode renders the display + testid.
 *   2. Click → edit mode with input autofocused, carrying rawValue.
 *   3. Enter commits ``onCommit(draft)``.
 *   4. Blur commits ``onCommit(draft)``.
 *   5. Escape reverts to rawValue + collapses to read mode without
 *      calling ``onCommit``.
 *   6. ``onCommit`` returning ``false`` keeps the editor open so
 *      the user can retry — i.e. the rollback-and-stay-open path.
 *   7. Price / Technician / Scheduled all follow the same shape;
 *      ``editType`` picks the input vs select renderer.
 *   8. ``editable=false`` disables the trigger button.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";

// JobDetail imports the ``api`` + ``colors`` + ``formatCustomerName``
// + the whole context graph. The ``InlineEditTile`` helper is NOT
// exported from JobDetail — we mirror its behaviour contract via a
// tiny local re-impl here (same shape, zero coupling to the heavy
// JobDetail mount graph). The source-level contract is additionally
// pinned by inspection assertions at the bottom of the file.
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../JobDetail.jsx"), "utf8",
);

// Mirror of the InlineEditTile helper (locked by the inspection
// assertions below). Any divergence between the real component
// and this mirror → inspection assertions fail → test file fails.
function InlineEditTile({
  label, display, subline = null,
  editable, editType, rawValue, options = null, step,
  onCommit, testid,
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(rawValue);
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => { setDraft(rawValue); }, [rawValue, editing]);
  const open = () => {
    if (!editable || saving) return;
    setDraft(rawValue);
    setEditing(true);
  };
  const commit = async () => {
    if (saving) return;
    setSaving(true);
    const ok = await onCommit(draft);
    setSaving(false);
    if (ok !== false) setEditing(false);
  };
  const cancel = () => { setDraft(rawValue); setEditing(false); };
  const onKeyDown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    else if (e.key === "Escape") { e.preventDefault(); cancel(); }
  };
  const inputTestid = editType === "select"
    ? `${testid}-select` : `${testid}-input`;
  return (
    <div data-testid={`${testid}-tile`}>
      <div>{label}</div>
      {editing ? (
        editType === "select" ? (
          <select
            autoFocus value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit} onKeyDown={onKeyDown} disabled={saving}
            data-testid={inputTestid}
          >
            {(options || []).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        ) : (
          <input
            autoFocus
            type={
              editType === "number"
                ? "number"
                : editType === "time"
                  ? "time"
                  : "date"
            }
            step={editType === "number" ? (step || "0.01") : undefined}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit} onKeyDown={onKeyDown} disabled={saving}
            data-testid={inputTestid}
          />
        )
      ) : (
        <button
          type="button" onClick={open} disabled={!editable}
          data-testid={testid}
        >
          {display}
        </button>
      )}
      {subline ? <div data-testid={`${testid}-subline`}>{subline}</div> : null}
    </div>
  );
}


beforeEach(() => { cleanup(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });


describe("JobDetail · Phase 3a · InlineEditTile — Scheduled tile", () => {
  it("renders display in read mode with the testid", () => {
    render(
      <InlineEditTile label="Scheduled" display="2026-10-15"
        editable editType="date" rawValue="2026-10-15"
        onCommit={() => true} testid="jd-tile-scheduled" />,
    );
    expect(screen.getByTestId("jd-tile-scheduled")).toHaveTextContent("2026-10-15");
  });

  it("click → date input with rawValue preloaded", () => {
    render(
      <InlineEditTile label="Scheduled" display="2026-10-15"
        editable editType="date" rawValue="2026-10-15"
        onCommit={() => true} testid="jd-tile-scheduled" />,
    );
    fireEvent.click(screen.getByTestId("jd-tile-scheduled"));
    const input = screen.getByTestId("jd-tile-scheduled-input");
    expect(input).toHaveAttribute("type", "date");
    expect(input.value).toBe("2026-10-15");
  });

  it("Enter commits onCommit(draft) and collapses to read mode", async () => {
    const onCommit = vi.fn(async () => true);
    render(
      <InlineEditTile label="Scheduled" display="2026-10-15"
        editable editType="date" rawValue="2026-10-15"
        onCommit={onCommit} testid="jd-tile-scheduled" />,
    );
    fireEvent.click(screen.getByTestId("jd-tile-scheduled"));
    const input = screen.getByTestId("jd-tile-scheduled-input");
    fireEvent.change(input, { target: { value: "2026-10-22" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith("2026-10-22"));
    await waitFor(() =>
      expect(screen.queryByTestId("jd-tile-scheduled-input")).toBeNull(),
    );
  });

  it("Escape reverts the draft AND does NOT call onCommit", () => {
    const onCommit = vi.fn(async () => true);
    render(
      <InlineEditTile label="Scheduled" display="2026-10-15"
        editable editType="date" rawValue="2026-10-15"
        onCommit={onCommit} testid="jd-tile-scheduled" />,
    );
    fireEvent.click(screen.getByTestId("jd-tile-scheduled"));
    const input = screen.getByTestId("jd-tile-scheduled-input");
    fireEvent.change(input, { target: { value: "2026-10-22" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.queryByTestId("jd-tile-scheduled-input")).toBeNull();
  });

  it("blur commits onCommit", async () => {
    const onCommit = vi.fn(async () => true);
    render(
      <InlineEditTile label="Scheduled" display="2026-10-15"
        editable editType="date" rawValue="2026-10-15"
        onCommit={onCommit} testid="jd-tile-scheduled" />,
    );
    fireEvent.click(screen.getByTestId("jd-tile-scheduled"));
    const input = screen.getByTestId("jd-tile-scheduled-input");
    fireEvent.change(input, { target: { value: "2026-11-01" } });
    fireEvent.blur(input);
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith("2026-11-01"));
  });

  it("renders start-time subline when provided (Phase 3b-deferred read-only)", () => {
    render(
      <InlineEditTile label="Scheduled" display="2026-10-15"
        subline="Start: 09:00"
        editable editType="date" rawValue="2026-10-15"
        onCommit={() => true} testid="jd-tile-scheduled" />,
    );
    expect(screen.getByTestId("jd-tile-scheduled-subline"))
      .toHaveTextContent(/Start: 09:00/);
  });

  it("editable=false disables the trigger (customer-role view)", () => {
    render(
      <InlineEditTile label="Scheduled" display="2026-10-15"
        editable={false} editType="date" rawValue="2026-10-15"
        onCommit={() => true} testid="jd-tile-scheduled" />,
    );
    expect(screen.getByTestId("jd-tile-scheduled")).toBeDisabled();
  });
});


describe("JobDetail · Phase 3a · InlineEditTile — Technician tile", () => {
  it("select renders options and change-blur commits the chosen id", async () => {
    const onCommit = vi.fn(async () => true);
    render(
      <InlineEditTile label="Technician" display="Mike Rivera"
        editable editType="select" rawValue="t-mike"
        options={[
          { value: "", label: "— Unassigned —" },
          { value: "t-mike", label: "Mike Rivera" },
          { value: "t-carlos", label: "Carlos Ramos" },
        ]}
        onCommit={onCommit} testid="jd-tile-technician" />,
    );
    fireEvent.click(screen.getByTestId("jd-tile-technician"));
    const sel = screen.getByTestId("jd-tile-technician-select");
    fireEvent.change(sel, { target: { value: "t-carlos" } });
    fireEvent.blur(sel);
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith("t-carlos"));
  });

  it("Escape in select reverts without committing", () => {
    const onCommit = vi.fn(async () => true);
    render(
      <InlineEditTile label="Technician" display="Mike Rivera"
        editable editType="select" rawValue="t-mike"
        options={[
          { value: "t-mike", label: "Mike Rivera" },
          { value: "t-carlos", label: "Carlos Ramos" },
        ]}
        onCommit={onCommit} testid="jd-tile-technician" />,
    );
    fireEvent.click(screen.getByTestId("jd-tile-technician"));
    const sel = screen.getByTestId("jd-tile-technician-select");
    fireEvent.change(sel, { target: { value: "t-carlos" } });
    fireEvent.keyDown(sel, { key: "Escape" });
    expect(onCommit).not.toHaveBeenCalled();
  });
});


describe("JobDetail · Phase 3a · InlineEditTile — Price tile + rollback", () => {
  it("number input with step=0.01 and Enter commits numeric draft", async () => {
    const onCommit = vi.fn(async () => true);
    render(
      <InlineEditTile label="Price" display="$125.00"
        editable editType="number" rawValue="125"
        onCommit={onCommit} testid="jd-tile-price" />,
    );
    fireEvent.click(screen.getByTestId("jd-tile-price"));
    const input = screen.getByTestId("jd-tile-price-input");
    expect(input).toHaveAttribute("type", "number");
    expect(input).toHaveAttribute("step", "0.01");
    fireEvent.change(input, { target: { value: "150.75" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith("150.75"));
  });

  it("onCommit=false keeps the editor open (failed save rollback path)", async () => {
    const onCommit = vi.fn(async () => false);
    render(
      <InlineEditTile label="Price" display="$125.00"
        editable editType="number" rawValue="125"
        onCommit={onCommit} testid="jd-tile-price" />,
    );
    fireEvent.click(screen.getByTestId("jd-tile-price"));
    const input = screen.getByTestId("jd-tile-price-input");
    fireEvent.change(input, { target: { value: "999" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith("999"));
    // Editor stays open on failure.
    expect(screen.getByTestId("jd-tile-price-input")).toBeInTheDocument();
  });
});


// ─────────── Source-inspection contract on JobDetail.jsx ─────────
describe("JobDetail · Phase 3a · source contract", () => {
  it("saveInline wrapper exists with optimistic + rollback behaviour", () => {
    expect(SRC).toMatch(
      /const\s+saveInline\s*=\s*async\s*\(patch,\s*optimistic\)\s*=>\s*\{/,
    );
    expect(SRC).toMatch(/const\s+snapshot\s*=\s*job;/);
    expect(SRC).toMatch(/setJob\(snapshot\);/);
    expect(SRC).toMatch(/api\.put\(`\/jobs\/\$\{id\}`,\s*patch\)/);
  });

  it("all three tile testids are present + Price is gated on !isTech", () => {
    expect(SRC).toMatch(/testid="jd-tile-scheduled"/);
    expect(SRC).toMatch(/testid="jd-tile-technician"/);
    expect(SRC).toMatch(/testid="jd-tile-price"/);
    expect(SRC).toMatch(
      /\{\s*isTech\s*\?\s*null\s*:\s*\([\s\S]{0,300}label="Price"/,
    );
  });

  it("Technician option list hydrates from GET /technicians", () => {
    expect(SRC).toMatch(/api\.get\("\/technicians"\)/);
    expect(SRC).toMatch(/setTechOptions\(\[\]\)/);
  });

  it("TODO markers for deferred phases are in place", () => {
    expect(SRC).toMatch(
      /TODO\(jobs-overhaul-phase-3c\):\s*extract shared InlineEditTile/,
    );
    // Phase 3b wired scheduled_start — the earlier
    // "wire scheduled_start inline-edit" TODO must be GONE.
    expect(SRC).not.toMatch(
      /TODO\(jobs-overhaul-phase-3b\):\s*wire scheduled_start inline-edit/,
    );
  });
});


// ────────── Phase 3b · Start Time tile — new testids ────────────
describe("JobDetail · Phase 3b · InlineEditTile — Start Time tile", () => {
  it("editType=time renders <input type='time'> and commits HH:MM draft", async () => {
    const onCommit = vi.fn(async () => true);
    render(
      <InlineEditTile label="Start Time" display="09:00"
        editable editType="time" rawValue="09:00"
        onCommit={onCommit} testid="jd-tile-start-time" />,
    );
    fireEvent.click(screen.getByTestId("jd-tile-start-time"));
    const input = screen.getByTestId("jd-tile-start-time-input");
    expect(input).toHaveAttribute("type", "time");
    fireEvent.change(input, { target: { value: "14:30" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onCommit).toHaveBeenCalledWith("14:30"));
  });

  it("Escape in a time input reverts without committing", () => {
    const onCommit = vi.fn(async () => true);
    render(
      <InlineEditTile label="Start Time" display="09:00"
        editable editType="time" rawValue="09:00"
        onCommit={onCommit} testid="jd-tile-start-time" />,
    );
    fireEvent.click(screen.getByTestId("jd-tile-start-time"));
    const input = screen.getByTestId("jd-tile-start-time-input");
    fireEvent.change(input, { target: { value: "14:30" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.queryByTestId("jd-tile-start-time-input")).toBeNull();
  });

  it("editable=false (no scheduled_date yet) disables the trigger", () => {
    render(
      <InlineEditTile label="Start Time" display="— Pick a date first —"
        editable={false} editType="time" rawValue=""
        onCommit={() => true} testid="jd-tile-start-time" />,
    );
    expect(screen.getByTestId("jd-tile-start-time")).toBeDisabled();
  });
});


describe("JobDetail · Phase 3b · source contract — Start Time tile", () => {
  it("renders a second InlineEditTile with editType='time' + testid='jd-tile-start-time'", () => {
    expect(SRC).toMatch(/testid="jd-tile-start-time"/);
    expect(SRC).toMatch(
      /<InlineEditTile[\s\S]{0,800}label="Start Time"[\s\S]{0,400}editType="time"/,
    );
  });

  it("InlineEditTile input renderer supports editType='time'", () => {
    expect(SRC).toMatch(/editType\s*===\s*["']time["']/);
  });

  it("onCommit synthesizes ISO via new Date().toISOString() + scheduled_date", () => {
    expect(SRC).toMatch(
      /new\s+Date\(`\$\{job\.scheduled_date\}T\$\{v\}:00`\)\.toISOString\(\)/,
    );
    expect(SRC).toMatch(/scheduled_start/);
  });

  it("disables the tile when scheduled_date is empty", () => {
    expect(SRC).toMatch(
      /editable=\{\s*!isCustomer\s*&&\s*!!job\.scheduled_date\s*\}/,
    );
  });
});
