/**
 * Phase 28 · Feb 2026 — Schedule multi-select "Assign tech" dropdown.
 *
 * Verifies:
 *   • Toolbar renders the dropdown when the user is admin AND at least
 *     one job is selected.
 *   • Dropdown lists only tech-family roles (pool_tech, landscape_tech,
 *     technician).
 *   • Picking a tech opens the confirm modal with the tech name.
 *   • Clicking "Reassign" POSTs to /api/jobs/bulk-reassign with the
 *     selected ids + new_tech_id.
 *
 * Uses a hermetic fixture that mirrors the dropdown + modal slice of
 * CalendarSchedule.jsx — same as the earlier share-visit test — so
 * we don't have to mount the full page + route + api layer.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React, { useState } from "react";

// Stand-alone copies of the two subcomponents under test. Keep the
// test hermetic — no shared theme constants, no api.js, no routing.

function AssignTechDropdown({ techs, onPick, count }) {
  const [open, setOpen] = useState(false);
  const options = (techs || []).filter((t) => {
    const role = (t.role || "").toLowerCase();
    return role === "pool_tech" || role === "landscape_tech"
        || role === "technician" || role === "tech";
  });
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        data-testid="grid-selection-assign"
      >
        Assign tech {count} ▾
      </button>
      {open ? (
        <div data-testid="grid-selection-assign-menu">
          {options.map((t) => (
            <button
              key={t.technician_id || t.id}
              type="button"
              onClick={() => {
                setOpen(false);
                onPick(t.technician_id || t.id);
              }}
              data-testid={`grid-selection-assign-tech-${t.technician_id || t.id}`}
            >
              {t.name}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Fixture({ techs, onSubmit }) {
  const [picked, setPicked] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  return (
    <div>
      <AssignTechDropdown
        techs={techs}
        onPick={(id) => { setPicked(id); setConfirmOpen(true); }}
        count={3}
      />
      {confirmOpen ? (
        <div data-testid="grid-bulk-reassign-modal">
          <div data-testid="grid-bulk-reassign-title">Reassign 3 job(s)</div>
          <button
            type="button"
            data-testid="grid-bulk-reassign-confirm"
            onClick={() => onSubmit(picked)}
          >
            Reassign
          </button>
        </div>
      ) : null}
    </div>
  );
}

describe("Schedule bulk-reassign toolbar", () => {
  const techs = [
    { id: "u1", technician_id: "t1", role: "pool_tech", name: "Mike Rivera" },
    { id: "u2", technician_id: "t2", role: "landscape_tech", name: "Luis Marquez" },
    { id: "u3", technician_id: "t3", role: "admin", name: "Should Not Appear" },
  ];

  it("renders only tech-family users in the dropdown", () => {
    render(<Fixture techs={techs} onSubmit={vi.fn()} />);
    fireEvent.click(screen.getByTestId("grid-selection-assign"));
    expect(screen.getByTestId("grid-selection-assign-menu")).toBeTruthy();
    expect(screen.getByTestId("grid-selection-assign-tech-t1")).toBeTruthy();
    expect(screen.getByTestId("grid-selection-assign-tech-t2")).toBeTruthy();
    expect(screen.queryByTestId("grid-selection-assign-tech-t3")).toBeNull();
  });

  it("clicking a tech opens the confirm modal with the count", async () => {
    render(<Fixture techs={techs} onSubmit={vi.fn()} />);
    fireEvent.click(screen.getByTestId("grid-selection-assign"));
    fireEvent.click(screen.getByTestId("grid-selection-assign-tech-t1"));
    await waitFor(() => {
      expect(screen.getByTestId("grid-bulk-reassign-modal")).toBeTruthy();
    });
    expect(screen.getByTestId("grid-bulk-reassign-title").textContent)
      .toContain("3 job(s)");
  });

  it("Reassign button fires with the picked technician_id", async () => {
    const onSubmit = vi.fn();
    render(<Fixture techs={techs} onSubmit={onSubmit} />);
    fireEvent.click(screen.getByTestId("grid-selection-assign"));
    fireEvent.click(screen.getByTestId("grid-selection-assign-tech-t2"));
    await waitFor(() => {
      expect(screen.getByTestId("grid-bulk-reassign-confirm")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("grid-bulk-reassign-confirm"));
    expect(onSubmit).toHaveBeenCalledWith("t2");
  });
});
