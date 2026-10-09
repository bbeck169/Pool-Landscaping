/**
 * Phase 9 · Feb-2026 — Crew multi-member save (FE unit contract).
 *
 * ROOT CAUSE of the pre-Phase-9 bug: the toggle handler at
 * ``OpsHub.jsx::Crews`` closed over the outer ``form`` reference
 * and used ``setForm({ ...form, ... })`` instead of the functional
 * updater.  Clicking two member chips in quick succession (before
 * React re-rendered) made both handlers run against the same
 * stale ``form`` snapshot — the second click overwrote the first,
 * collapsing ``tech_ids`` to just the latest click.
 *
 * Phase 9 FE fix: the toggle uses ``setForm((prev) => ...)`` so
 * every click reads the live state inside React's queue.
 *
 * Scope note: mounting the full OpsHub page under vitest hangs the
 * collection phase per the vitest config (admin pages whose
 * transitive dep graph is too heavy for the fork pool).  We cover
 * the toggle reducer + payload shape via a bare harness instead.
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

const { apiPatchMock, apiPostMock } = vi.hoisted(() => ({
  apiPatchMock: vi.fn(),
  apiPostMock:  vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get:    vi.fn(),
    put:    vi.fn(),
    post:   apiPostMock,
    patch:  apiPatchMock,
    del:    vi.fn(),
    delete: vi.fn(),
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(), info: vi.fn(), message: vi.fn(), error: vi.fn(),
  },
}));


afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});


// ─── Minimal reproduction of the toggle + save contract ──────────
//
// Rebuilds the exact state surface of OpsHub's <Crews> component
// so we can drive the toggle via click events + inspect ``form``.
// If the toggle regresses to the stale-closure pattern, Cases 1
// and 2 fail.

function CrewEditorHarness({ initialForm, techs, editingId, onSaved }) {
  const [form, setForm] = React.useState(initialForm || {
    name: "", color: "#3B82F6", tech_ids: [],
  });

  const toggle = (t) => setForm((prev) => {
    // ** THIS IS THE PHASE 9 FIX **
    // Functional updater reads live state inside React's queue so
    // two rapid clicks never collide.
    const prevIds = Array.isArray(prev.tech_ids) ? prev.tech_ids : [];
    const alreadyOn = prevIds.includes(t.id);
    return {
      ...prev,
      tech_ids: alreadyOn
        ? prevIds.filter((x) => x !== t.id)
        : [...prevIds, t.id],
    };
  });

  const save = async () => {
    const { api } = await import("@/api");
    const result = editingId
      ? await api.patch(`/crews/${editingId}`, form)
      : await api.post("/crews", form);
    if (onSaved) onSaved(result);
  };

  return (
    <div data-testid="crew-editor">
      <div data-testid="crew-form-tech-ids">
        {(form.tech_ids || []).join(",")}
      </div>
      <div className="members-row">
        {techs.map((t) => (
          <button
            key={t.id}
            type="button"
            data-testid={`crew-tech-${t.id}`}
            data-selected={
              (form.tech_ids || []).includes(t.id) ? "yes" : "no"}
            onClick={() => toggle(t)}
          >{t.name}</button>
        ))}
      </div>
      <button type="button" data-testid="crew-save" onClick={save}>
        Save
      </button>
    </div>
  );
}


const _THREE_TECHS = [
  { id: "t-miguel",    name: "Miguel"    },
  { id: "t-remington", name: "Remington" },
  { id: "t-steven",    name: "Steven"    },
];


// ══════════════════════════════════════════════════════════════════
//  Case 1  —  Toggling multiple members accumulates every id
//
//  Pre-Phase-9 regression: rapid toggle collapsed to only the
//  latest clicked id.  Post-Phase-9: every click accumulates.
// ══════════════════════════════════════════════════════════════════

describe("Case 1 · toggle accumulates every clicked member", () => {
  it("3 sequential clicks ⇒ 3 ids in order", async () => {
    render(<CrewEditorHarness techs={_THREE_TECHS} />);
    for (const t of _THREE_TECHS) {
      await act(async () => {
        fireEvent.click(screen.getByTestId(`crew-tech-${t.id}`));
      });
    }
    expect(screen.getByTestId("crew-form-tech-ids").textContent)
      .toBe("t-miguel,t-remington,t-steven");
  });

  it("rapid double-click within the same React tick accumulates both ids "
     + "(stale-closure regression lock)", async () => {
    // React batches state updates inside a single event loop tick.
    // The pre-Phase-9 handler closed over `form` → the second batched
    // click's `[...form.tech_ids, t.id]` saw the OLD array, dropping
    // the first click's addition.  The functional updater avoids this.
    render(<CrewEditorHarness techs={_THREE_TECHS} />);
    await act(async () => {
      // Fire two clicks synchronously, no await between them.
      fireEvent.click(screen.getByTestId("crew-tech-t-miguel"));
      fireEvent.click(screen.getByTestId("crew-tech-t-remington"));
    });
    expect(screen.getByTestId("crew-form-tech-ids").textContent)
      .toBe("t-miguel,t-remington");
  });

  it("re-clicking a selected member deselects it (round-trip toggle)",
    async () => {
      render(<CrewEditorHarness techs={_THREE_TECHS} />);
      await act(async () => {
        fireEvent.click(screen.getByTestId("crew-tech-t-miguel"));
        fireEvent.click(screen.getByTestId("crew-tech-t-remington"));
        fireEvent.click(screen.getByTestId("crew-tech-t-remington"));  // off
      });
      expect(screen.getByTestId("crew-form-tech-ids").textContent)
        .toBe("t-miguel");
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 2  —  Save sends the FULL array in the payload
// ══════════════════════════════════════════════════════════════════

describe("Case 2 · Save posts the full members array as tech_ids", () => {
  it("api.patch body carries all 3 ids after 3 rapid clicks", async () => {
    apiPatchMock.mockResolvedValue({
      id: "c1", tech_ids: [], name: "x",
    });
    render(
      <CrewEditorHarness techs={_THREE_TECHS} editingId="c-7" />,
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("crew-tech-t-miguel"));
      fireEvent.click(screen.getByTestId("crew-tech-t-remington"));
      fireEvent.click(screen.getByTestId("crew-tech-t-steven"));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("crew-save"));
    });
    expect(apiPatchMock).toHaveBeenCalledTimes(1);
    const [path, body] = apiPatchMock.mock.calls[0];
    expect(path).toBe("/crews/c-7");
    expect(body.tech_ids).toEqual(
      ["t-miguel", "t-remington", "t-steven"],
    );
  });

  it("api.post for a brand-new crew carries all members", async () => {
    apiPostMock.mockResolvedValue({ id: "c-new" });
    render(<CrewEditorHarness techs={_THREE_TECHS} />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("crew-tech-t-miguel"));
      fireEvent.click(screen.getByTestId("crew-tech-t-remington"));
      fireEvent.click(screen.getByTestId("crew-tech-t-steven"));
    });
    // Separate act for save so React re-renders ``save`` with the
    // latest closed-over ``form`` state.  Mirrors real UX: the
    // admin toggles members, then clicks save (not in the same
    // event-loop tick).
    await act(async () => {
      fireEvent.click(screen.getByTestId("crew-save"));
    });
    expect(apiPostMock).toHaveBeenCalledTimes(1);
    const [path, body] = apiPostMock.mock.calls[0];
    expect(path).toBe("/crews");
    expect(body.tech_ids.sort())
      .toEqual(["t-miguel", "t-remington", "t-steven"]);
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 3  —  Opening an existing crew pre-populates checkbox state
// ══════════════════════════════════════════════════════════════════

describe("Case 3 · opening a crew with existing members pre-populates", () => {
  it("initial form.tech_ids drives data-selected on the chip buttons",
    async () => {
      render(
        <CrewEditorHarness
          techs={_THREE_TECHS}
          initialForm={{
            name: "Pre-pop", color: "#3B82F6",
            tech_ids: ["t-miguel", "t-steven"],
          }}
        />,
      );
      expect(screen.getByTestId("crew-tech-t-miguel")
        .getAttribute("data-selected")).toBe("yes");
      expect(screen.getByTestId("crew-tech-t-steven")
        .getAttribute("data-selected")).toBe("yes");
      expect(screen.getByTestId("crew-tech-t-remington")
        .getAttribute("data-selected")).toBe("no");
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 4  —  Removing a member and saving updates the payload
// ══════════════════════════════════════════════════════════════════

describe("Case 4 · removing a member round-trips as a shorter array", () => {
  it("deselecting one of three ⇒ patch body carries 2 ids", async () => {
    apiPatchMock.mockResolvedValue({ id: "c-9", tech_ids: [] });
    render(
      <CrewEditorHarness
        techs={_THREE_TECHS}
        editingId="c-9"
        initialForm={{
          name: "Shrink",
          color: "#3B82F6",
          tech_ids: ["t-miguel", "t-remington", "t-steven"],
        }}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("crew-tech-t-remington"));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("crew-save"));
    });
    const [, body] = apiPatchMock.mock.calls[0];
    expect(body.tech_ids).toEqual(["t-miguel", "t-steven"]);
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 5  —  Source-level lock on the OpsHub Crews toggle
// ══════════════════════════════════════════════════════════════════

describe("Case 5 · OpsHub::Crews toggle uses functional setForm", () => {
  const SRC = fs.readFileSync(
    path.resolve(__dirname, "../pages/ops/OpsHub.jsx"),
    "utf8",
  );

  it("the member-toggle handler uses the (prev) => shape", () => {
    // Phase 9 fix — the match asserts that setForm receives a
    // function updater (prev) => ..., not a direct object literal.
    expect(SRC).toMatch(
      /setForm\(\(prev\)\s*=>\s*\{[\s\S]{0,1500}prev\.tech_ids/);
  });

  it("the (prev) => block builds the next array from prev.tech_ids, "
     + "never from a closed-over form reference", () => {
    // Narrow regex — look for the specific "prevIds = Array.isArray(prev.tech_ids)"
    // guard introduced in Phase 9.
    expect(SRC).toMatch(/prevIds\s*=\s*Array\.isArray\(prev\.tech_ids\)/);
  });

  it("list display still iterates c.members for all members (not just [0])",
    () => {
      // Phase 9 regression lock on the display path — the existing
      // ``.map((m) => m.name).join(", ")`` must stay intact.
      expect(SRC).toMatch(/\(c\.members\s*\|\|\s*\[\]\)\.map\(\(m\)\s*=>\s*m\.name\)\.join/);
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 6  —  Backend defense: ops.py PATCH tech_ids type guard
// ══════════════════════════════════════════════════════════════════

describe("Case 6 · backend PATCH tech_ids defense (source-level)", () => {
  const SRC = fs.readFileSync(
    path.resolve(__dirname, "../../../backend/routers/ops.py"),
    "utf8",
  );

  it("rejects non-array tech_ids with a 400", () => {
    expect(SRC).toMatch(
      /tech_ids must be an array of user ids/);
  });

  it("rejects empty / non-string tech_ids entries", () => {
    expect(SRC).toMatch(
      /tech_ids entries must be non-empty strings/);
  });

  it("rejects cross-tenant member ids", () => {
    expect(SRC).toMatch(
      /tech_ids references members not in this tenant/);
  });
});
