/**
 * Ticket UU · Feb-2026 — Schedule bulk-action "Assign tech" dropdown
 * must list crews + technicians.
 *
 * BE contract (unchanged by this ship — Feb-2026 Crew Phase A):
 *   POST /api/jobs/bulk-reassign accepts EITHER ``new_tech_id`` OR
 *   ``new_crew_id`` (or both); the per-job write stamps ``crew_id``
 *   and / or ``technician_id`` independently.  Downstream readers
 *   already union over both dimensions.
 *
 * FE evolution shipped by this ticket:
 *   1. ``AssignTechDropdown`` accepts a ``crews`` prop and merge-
 *      renders crews + techs with per-entry sub-labels ("crew" vs
 *      the pre-existing role).
 *   2. The ``onPick`` payload shape changed from a bare id to
 *      ``{ kind: "tech" | "crew", id }`` so the parent can route to
 *      the right BE arg.
 *   3. ``doBulkReassign`` posts ``new_crew_id`` when ``kind=crew``,
 *      falls through to the pre-UU ``new_tech_id`` payload otherwise.
 *   4. ``BulkReassignConfirmModal`` resolves the display name from
 *      the crews list when ``pickedKind=crew``.
 *
 * Scope (TD-uu-schedule-bulk-assign-shows-crews-and-techs):
 *   Mounting the full Schedule page under vitest requires the auth
 *   provider + the full router + the memoised schedule state graph,
 *   which pushes collection past the sanity-cap in the vitest
 *   config.  This file uses a lightweight harness strategy — the
 *   payload invariants are re-expressed against a mocked api
 *   client, plus a source-level regex lock on the picker + modal
 *   so a refactor can't silently sever the crew-aware branches.
 */
import React from "react";
import {
  describe, it, expect, vi, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, act, cleanup,
} from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";


// ─── mocks ────────────────────────────────────────────────────────

const { apiPostMock } = vi.hoisted(() => ({
  apiPostMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get:    vi.fn(),
    put:    vi.fn(),
    post:   apiPostMock,
    patch:  vi.fn(),
    del:    vi.fn(),
    delete: vi.fn(),
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));


afterEach(() => { cleanup(); vi.clearAllMocks(); });


// ─── Picker harness ──────────────────────────────────────────────
//
// Mirrors the exact post-UU shape of ``AssignTechDropdown``:
// crews first (sub-label "crew"), then techs filtered to the four
// tech roles (sub-label = the role name with ``_`` → " ").  Keep
// this byte-identical to the source — a drift here means a drift
// in the source regex-locked below is going undetected.

function AssignTechDropdownHarness({ techs, crews, onPick, count }) {
  const [open, setOpen] = React.useState(false);
  const options = (techs || []).filter((t) => {
    const role = (t.role || "").toLowerCase();
    return role === "pool_tech" || role === "landscape_tech"
        || role === "technician" || role === "tech";
  });
  const crewOptions = Array.isArray(crews) ? crews : [];
  return (
    <div>
      <button type="button" onClick={() => setOpen((v) => !v)}
              data-testid="grid-selection-assign">
        Assign tech {count} ▾
      </button>
      {open ? (
        <div data-testid="grid-selection-assign-menu">
          {crewOptions.length === 0 && options.length === 0 ? (
            <div data-testid="grid-selection-assign-empty">
              No techs available
            </div>
          ) : (
            <>
              {crewOptions.map((c) => (
                <button
                  key={`crew-${c.id}`}
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    onPick({ kind: "crew", id: c.id });
                  }}
                  data-testid={`grid-selection-assign-crew-${c.id}`}
                >
                  <div data-testid={`crew-name-${c.id}`}>
                    {c.name || "Unnamed crew"}
                  </div>
                  <div data-testid={`crew-sublabel-${c.id}`}>
                    crew
                  </div>
                </button>
              ))}
              {options.map((t) => (
                <button
                  key={t.technician_id || t.id}
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    onPick({ kind: "tech",
                              id: t.technician_id || t.id });
                  }}
                  data-testid={`grid-selection-assign-tech-${t.technician_id || t.id}`}
                >
                  <div data-testid={`tech-name-${t.technician_id || t.id}`}>
                    {t.name || t.first_name || t.email}
                  </div>
                  <div data-testid={`tech-sublabel-${t.technician_id || t.id}`}>
                    {(t.role || "").replace("_", " ")}
                  </div>
                </button>
              ))}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}


// Parent-level bulk-reassign flow harness.  Mirrors the post-UU
// ``doBulkReassign`` payload switch so the test asserts the exact
// shape that lands on the mocked api client.

function BulkReassignFlowHarness({ techs, crews, selectedIds }) {
  const [kind, setKind] = React.useState(null);
  const [pickedId, setPickedId] = React.useState("");
  const confirm = async () => {
    const { api } = await import("@/api");
    const payload = kind === "crew"
      ? { job_ids: selectedIds, new_crew_id: pickedId }
      : { job_ids: selectedIds, new_tech_id: pickedId };
    await api.post("/jobs/bulk-reassign", payload);
  };
  return (
    <div>
      <AssignTechDropdownHarness
        techs={techs} crews={crews} count={selectedIds.length}
        onPick={({ kind: k, id }) => { setKind(k); setPickedId(id); }}
      />
      <button type="button" data-testid="flow-confirm"
              disabled={!pickedId} onClick={confirm}>
        Confirm
      </button>
      <div data-testid="flow-kind">{kind || ""}</div>
      <div data-testid="flow-picked-id">{pickedId}</div>
    </div>
  );
}


// ══════════════════════════════════════════════════════════════════
//  Case 1 · Dropdown lists both crews and techs with correct sub-labels
// ══════════════════════════════════════════════════════════════════

describe("UU Case 1 · dropdown merges crews + techs", () => {
  it("renders crews first with sub-label 'crew', then techs with "
     + "the role sub-label", async () => {
    render(
      <BulkReassignFlowHarness
        techs={[
          { id: "t-1", technician_id: "t-1",
            name: "Alice", role: "pool_tech" },
          { id: "t-2", technician_id: "t-2",
            name: "Bob",   role: "landscape_tech" },
        ]}
        crews={[
          { id: "c-A", name: "Alpha Crew" },
          { id: "c-B", name: "Beta Crew" },
        ]}
        selectedIds={["j-1"]}
      />,
    );
    fireEvent.click(screen.getByTestId("grid-selection-assign"));
    expect(screen.getByTestId("grid-selection-assign-menu"))
      .toBeTruthy();
    // Crews present with 'crew' sub-label.
    expect(screen.getByTestId("grid-selection-assign-crew-c-A"))
      .toBeTruthy();
    expect(screen.getByTestId("crew-sublabel-c-A").textContent)
      .toBe("crew");
    expect(screen.getByTestId("crew-name-c-A").textContent)
      .toBe("Alpha Crew");
    // Techs still present with the role sub-label.
    expect(screen.getByTestId("grid-selection-assign-tech-t-1"))
      .toBeTruthy();
    expect(screen.getByTestId("tech-sublabel-t-1").textContent)
      .toBe("pool tech");
    expect(screen.getByTestId("tech-sublabel-t-2").textContent)
      .toBe("landscape tech");
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 2 · Selecting a crew fires POST /jobs/bulk-reassign with
//           ``new_crew_id`` (NOT ``new_tech_id``)
// ══════════════════════════════════════════════════════════════════

describe("UU Case 2 · crew pick routes to new_crew_id", () => {
  it("payload has new_crew_id, no new_tech_id", async () => {
    apiPostMock.mockResolvedValue({ ok: true, count: 2 });
    render(
      <BulkReassignFlowHarness
        techs={[{ id: "t-1", technician_id: "t-1",
                   name: "Alice", role: "pool_tech" }]}
        crews={[{ id: "c-A", name: "Alpha Crew" }]}
        selectedIds={["j-1", "j-2"]}
      />,
    );
    fireEvent.click(screen.getByTestId("grid-selection-assign"));
    fireEvent.click(screen.getByTestId("grid-selection-assign-crew-c-A"));
    expect(screen.getByTestId("flow-kind").textContent).toBe("crew");
    expect(screen.getByTestId("flow-picked-id").textContent).toBe("c-A");
    await act(async () => {
      fireEvent.click(screen.getByTestId("flow-confirm"));
    });
    expect(apiPostMock).toHaveBeenCalledTimes(1);
    expect(apiPostMock).toHaveBeenCalledWith(
      "/jobs/bulk-reassign",
      { job_ids: ["j-1", "j-2"], new_crew_id: "c-A" },
    );
    const _payload = apiPostMock.mock.calls[0][1];
    expect(_payload).not.toHaveProperty("new_tech_id");
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 3 · Selecting a tech still fires ``new_tech_id`` (regression)
// ══════════════════════════════════════════════════════════════════

describe("UU Case 3 · tech pick routes to new_tech_id (regression)",
  () => {
    it("payload has new_tech_id, no new_crew_id", async () => {
      apiPostMock.mockResolvedValue({ ok: true, count: 1,
                                      new_tech_name: "Alice" });
      render(
        <BulkReassignFlowHarness
          techs={[{ id: "t-1", technician_id: "t-1",
                     name: "Alice", role: "pool_tech" }]}
          crews={[{ id: "c-A", name: "Alpha Crew" }]}
          selectedIds={["j-1"]}
        />,
      );
      fireEvent.click(screen.getByTestId("grid-selection-assign"));
      fireEvent.click(
        screen.getByTestId("grid-selection-assign-tech-t-1"));
      expect(screen.getByTestId("flow-kind").textContent).toBe("tech");
      await act(async () => {
        fireEvent.click(screen.getByTestId("flow-confirm"));
      });
      expect(apiPostMock).toHaveBeenCalledWith(
        "/jobs/bulk-reassign",
        { job_ids: ["j-1"], new_tech_id: "t-1" },
      );
      const _payload = apiPostMock.mock.calls[0][1];
      expect(_payload).not.toHaveProperty("new_crew_id");
    });
  });


// ══════════════════════════════════════════════════════════════════
//  Case 4 · Role-filter still excludes non-tech users
// ══════════════════════════════════════════════════════════════════

describe("UU Case 4 · tech role-filter unchanged", () => {
  it("admin / customer / dispatcher users are filtered OUT of the "
     + "tech half (role-filter regression lock)", () => {
    render(
      <BulkReassignFlowHarness
        techs={[
          { id: "t-1", technician_id: "t-1",
            name: "Alice",  role: "pool_tech" },         // kept
          { id: "u-ad", name: "Admin",     role: "admin" },      // filtered
          { id: "u-cx", name: "Customer",  role: "customer" },   // filtered
          { id: "u-ds", name: "Dispatch",  role: "dispatcher" }, // filtered
          { id: "t-2", technician_id: "t-2",
            name: "Bob",    role: "technician" },         // kept
          { id: "t-3", technician_id: "t-3",
            name: "Carol",  role: "tech" },               // kept
        ]}
        crews={[]}
        selectedIds={["j-1"]}
      />,
    );
    fireEvent.click(screen.getByTestId("grid-selection-assign"));
    expect(screen.getByTestId("grid-selection-assign-tech-t-1"))
      .toBeTruthy();
    expect(screen.getByTestId("grid-selection-assign-tech-t-2"))
      .toBeTruthy();
    expect(screen.getByTestId("grid-selection-assign-tech-t-3"))
      .toBeTruthy();
    expect(screen.queryByTestId("grid-selection-assign-tech-u-ad"))
      .toBeNull();
    expect(screen.queryByTestId("grid-selection-assign-tech-u-cx"))
      .toBeNull();
    expect(screen.queryByTestId("grid-selection-assign-tech-u-ds"))
      .toBeNull();
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 5 · No crews available → picker degrades to tech-only
// ══════════════════════════════════════════════════════════════════

describe("UU Case 5 · empty crews list degrades to tech-only", () => {
  it("empty ``crews`` array renders only tech entries, no 'No "
     + "techs available' empty state when at least one tech is "
     + "available", () => {
    render(
      <BulkReassignFlowHarness
        techs={[{ id: "t-1", technician_id: "t-1",
                   name: "Alice", role: "pool_tech" }]}
        crews={[]}
        selectedIds={["j-1"]}
      />,
    );
    fireEvent.click(screen.getByTestId("grid-selection-assign"));
    expect(screen.getByTestId("grid-selection-assign-tech-t-1"))
      .toBeTruthy();
    expect(screen.queryByTestId("grid-selection-assign-empty"))
      .toBeNull();
  });

  it("both lists empty → 'No techs available' empty state", () => {
    render(
      <BulkReassignFlowHarness
        techs={[]} crews={[]} selectedIds={["j-1"]}
      />,
    );
    fireEvent.click(screen.getByTestId("grid-selection-assign"));
    expect(screen.getByTestId("grid-selection-assign-empty"))
      .toBeTruthy();
  });

  it("``crews`` undefined (defensive) also degrades to tech-only",
    () => {
      render(
        <BulkReassignFlowHarness
          techs={[{ id: "t-1", technician_id: "t-1",
                     name: "Alice", role: "pool_tech" }]}
          crews={undefined}
          selectedIds={["j-1"]}
        />,
      );
      fireEvent.click(screen.getByTestId("grid-selection-assign"));
      expect(screen.getByTestId("grid-selection-assign-tech-t-1"))
        .toBeTruthy();
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 6 · Source regex-locks on CalendarSchedule.jsx
//
//  Guards against a refactor that silently severs the crew-aware
//  branches landed by this ticket.
// ══════════════════════════════════════════════════════════════════

describe("UU Case 6 · CalendarSchedule.jsx source regex lock", () => {
  const SRC = fs.readFileSync(
    path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
    "utf8",
  );

  it("AssignTechDropdown accepts a ``crews`` prop", () => {
    expect(SRC).toMatch(
      /function\s+AssignTechDropdown\(\s*\{\s*techs,\s*crews,\s*onPick,\s*count\s*\}/);
  });

  it("Dropdown emits { kind: 'crew', id } on crew pick", () => {
    expect(SRC).toMatch(
      /onPick\(\{\s*kind:\s*["']crew["'],\s*id:\s*c\.id\s*\}\)/);
  });

  it("Dropdown emits { kind: 'tech', id } on tech pick", () => {
    expect(SRC).toMatch(
      /onPick\(\{\s*kind:\s*["']tech["'],\s*id:\s*t\.technician_id\s*\|\|\s*t\.id\s*\}\)/);
  });

  it("Each crew entry carries the stable testid shape "
     + "``grid-selection-assign-crew-${c.id}``", () => {
    expect(SRC).toMatch(
      /data-testid=\{`grid-selection-assign-crew-\$\{c\.id\}`\}/);
  });

  it("Each crew entry renders the literal sub-label 'crew'", () => {
    // The sub-label text node must be the literal word (not an
    // interpolation), mirroring the tech-side sub-label render
    // shape and the operator's spec.
    expect(SRC).toMatch(
      /style=\{\{\s*color:\s*"#6b7280",\s*fontSize:\s*10\s*\}\}\s*>\s*crew\s*</);
  });

  it("doBulkReassign routes to new_crew_id when kind === 'crew'",
    () => {
      expect(SRC).toMatch(
        /assignPickedKind\s*===\s*["']crew["'][\s\S]{0,200}?new_crew_id:\s*assignPickedTechId/);
    });

  it("doBulkReassign falls through to new_tech_id otherwise "
     + "(regression lock on the pre-UU tech-only payload)", () => {
    expect(SRC).toMatch(
      /\{\s*job_ids:\s*ids,\s*new_tech_id:\s*assignPickedTechId\s*\}/);
  });

  it("BulkReassignConfirmModal accepts crews + pickedKind props",
    () => {
      expect(SRC).toMatch(
        /function\s+BulkReassignConfirmModal\(\s*\{[\s\S]{0,160}?crews[\s\S]{0,80}?pickedKind/);
    });

  it("Confirm modal resolves display name from crews when "
     + "pickedKind === 'crew'", () => {
    expect(SRC).toMatch(
      /pickedKind\s*===\s*["']crew["'][\s\S]{0,160}?\(crews\s*\|\|\s*\[\]\)\.find/);
  });

  it("Role-filter in AssignTechDropdown is UNCHANGED by UU "
     + "(pre-UU regression lock)", () => {
    expect(SRC).toMatch(
      /role\s*===\s*["']pool_tech["']\s*\|\|\s*role\s*===\s*["']landscape_tech["']\s*\|\|\s*role\s*===\s*["']technician["']\s*\|\|\s*role\s*===\s*["']tech["']/);
  });
});
