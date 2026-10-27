/**
 * Ticket QQ · Feb-2026 — Crew save surfaces silently-dropped members
 * (Option A, FE-only observability).
 *
 * Context:
 *   The BE (``routers/ops.py``) intentionally silently drops ``orphan``
 *   and ``soft_deleted`` ids from a crew's persisted ``tech_ids`` list
 *   under the ``TD-crew-silently-drop-orphan-members-and-backfill``
 *   posture (operator-reversed Ticket G's strict-reject). Response is
 *   2xx with the dropped ids absent from the returned ``tech_ids``.
 *
 * Pre-QQ bug: the FE showed a plain "Saved" success toast even when
 *   the server-persisted ``tech_ids`` was shorter than ``form.tech_ids``.
 *   Operator had no visibility that their selection was partially
 *   discarded.
 *
 * QQ fix (OpsHub.jsx::Crews.save): after a 2xx, diff the submitted
 *   ``form.tech_ids`` against the returned doc's ``tech_ids``; if any
 *   ids are missing, resolve them to display names via the loaded
 *   roster (``scopedTechs``) first, then the embedded crew-doc
 *   ``members`` join (``incomingMembers``), finally fall back to the
 *   first 8 chars of the id. Toast tone becomes ``warning`` with copy
 *   ``Saved, but these members couldn't be added: X, Y, Z``.
 *
 * Scope note (inherited from crews-multi-member-save.test.jsx):
 *   Mounting the full OpsHub page under vitest hangs the collection
 *   phase per the vitest config. This file uses the same lightweight
 *   harness strategy — reproduce the exact save handler contract
 *   against a mocked api client, plus a source-level regex lock on
 *   OpsHub.jsx so a refactor that drops the diff branch fails here.
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


afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});


// ─── Save handler harness ────────────────────────────────────────
//
// Mirrors the exact save-handler contract from
// ``OpsHub.jsx::Crews.save`` after the QQ Option-A ship. Keep the
// code path byte-identical to the source so a regression in the
// source regex-locked below also surfaces as a harness mismatch.

function CrewSaveHarness({
  editingId, editingTechIds, form, scopedTechs, incomingMembers,
  apiPatchResult, apiPostResult, onToast,
}) {
  const [toast, setToast] = React.useState(null);

  // Prime the mocked api result ONCE per render (vi.clearAllMocks
  // runs between tests so each test sets its own result).
  React.useEffect(() => {
    if (editingId) apiPatchMock.mockResolvedValue(apiPatchResult);
    else           apiPostMock.mockResolvedValue(apiPostResult);
  }, [editingId, apiPatchResult, apiPostResult]);

  const save = async () => {
    const { api } = await import("@/api");
    const _res = editingId
      ? await api.patch(`/crews/${editingId}`, form)
      : await api.post("/crews", form);
    const _submitted = Array.isArray(form.tech_ids) ? form.tech_ids : [];
    const _persisted = Array.isArray(_res?.tech_ids)
      ? _res.tech_ids : _submitted;
    // Mirror the source narrowing from the QQ-reopen ship: ghosts
    // that were pre-existing in the opened crew doc are the
    // pre-save unavailable-chips banner's problem, not the
    // post-save warning's.  Warn only on newly-added-this-session
    // ids that got dropped by the BE silent-drop filter.
    const _preExisting = new Set(
      editingId && Array.isArray(editingTechIds) ? editingTechIds : []);
    const _droppedIds = _submitted.filter(
      (x) => !_persisted.includes(x) && !_preExisting.has(x));
    if (_droppedIds.length > 0) {
      const _nameLookup = (id) => {
        const t = (scopedTechs || []).find((x) => x.id === id);
        if (t && t.name) return t.name;
        const m = (incomingMembers || []).find((x) => x.id === id);
        if (m && m.name) return m.name;
        return typeof id === "string" ? id.slice(0, 8) : String(id);
      };
      const _names = _droppedIds.map(_nameLookup).join(", ");
      const t = { tone: "warning",
        message: `Saved, but these members couldn't be added: ${_names}` };
      setToast(t); if (onToast) onToast(t);
    } else {
      const t = { tone: "success", message: "Saved" };
      setToast(t); if (onToast) onToast(t);
    }
  };

  return (
    <div data-testid="crew-save-harness">
      <div data-testid="toast-tone">{toast?.tone || ""}</div>
      <div data-testid="toast-message">{toast?.message || ""}</div>
      <button type="button" data-testid="crew-save" onClick={save}>
        Save
      </button>
    </div>
  );
}


// ══════════════════════════════════════════════════════════════════
//  Case 1  —  2xx with persisted ⊇ submitted  →  plain "Saved"
// ══════════════════════════════════════════════════════════════════

describe("QQ Case 1 · 2xx with no drops shows plain Saved toast", () => {
  it("PATCH response tech_ids equals submitted → tone=success, msg=Saved",
    async () => {
      const captured = [];
      render(
        <CrewSaveHarness
          editingId="c-7"
          form={{ name: "A", tech_ids: ["t-a", "t-b"] }}
          scopedTechs={[
            { id: "t-a", name: "Alice" },
            { id: "t-b", name: "Bob" },
          ]}
          incomingMembers={[]}
          apiPatchResult={{
            id: "c-7", name: "A", tech_ids: ["t-a", "t-b"],
          }}
          onToast={(t) => captured.push(t)}
        />,
      );
      await act(async () => {
        fireEvent.click(screen.getByTestId("crew-save"));
      });
      expect(screen.getByTestId("toast-tone").textContent).toBe("success");
      expect(screen.getByTestId("toast-message").textContent).toBe("Saved");
      expect(captured[0]).toEqual({ tone: "success", message: "Saved" });
    });

  it("POST response tech_ids equals submitted → tone=success, msg=Saved",
    async () => {
      render(
        <CrewSaveHarness
          editingId={null}
          form={{ name: "New", tech_ids: ["t-c"] }}
          scopedTechs={[{ id: "t-c", name: "Carol" }]}
          incomingMembers={[]}
          apiPostResult={{
            id: "c-new", name: "New", tech_ids: ["t-c"],
          }}
        />,
      );
      await act(async () => {
        fireEvent.click(screen.getByTestId("crew-save"));
      });
      expect(screen.getByTestId("toast-tone").textContent).toBe("success");
      expect(screen.getByTestId("toast-message").textContent).toBe("Saved");
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 2  —  2xx with one drop  →  warning toast + resolved name
// ══════════════════════════════════════════════════════════════════

describe("QQ Case 2 · 2xx with one dropped id surfaces warning", () => {
  it("name resolves via scopedTechs (picker roster)", async () => {
    render(
      <CrewSaveHarness
        editingId="c-9"
        form={{ name: "D", tech_ids: ["t-a", "t-ghost"] }}
        scopedTechs={[
          { id: "t-a",     name: "Alice" },
          { id: "t-ghost", name: "Ghost Member" },
        ]}
        incomingMembers={[]}
        apiPatchResult={{
          id: "c-9", name: "D", tech_ids: ["t-a"],   // t-ghost dropped
        }}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("crew-save"));
    });
    expect(screen.getByTestId("toast-tone").textContent).toBe("warning");
    expect(screen.getByTestId("toast-message").textContent).toBe(
      "Saved, but these members couldn't be added: Ghost Member");
  });

  it("name resolves via incomingMembers when the picker roster "
     + "doesn't include the dropped id (legacy drift path)", async () => {
    render(
      <CrewSaveHarness
        editingId="c-10"
        form={{ name: "L", tech_ids: ["t-a", "u-legacy"] }}
        scopedTechs={[{ id: "t-a", name: "Alice" }]}
        incomingMembers={[{ id: "u-legacy", name: "Legacy Admin" }]}
        apiPatchResult={{
          id: "c-10", name: "L", tech_ids: ["t-a"],
        }}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("crew-save"));
    });
    expect(screen.getByTestId("toast-tone").textContent).toBe("warning");
    expect(screen.getByTestId("toast-message").textContent).toBe(
      "Saved, but these members couldn't be added: Legacy Admin");
  });
});


// ══════════════════════════════════════════════════════════════════
//  Case 3  —  2xx with drop that resolves to NEITHER list  →  fallback
// ══════════════════════════════════════════════════════════════════

describe("QQ Case 3 · dropped id with no name falls back to first-8-chars",
  () => {
    it("neither scopedTechs nor incomingMembers has the id "
       + "→ toast shows the id's first 8 chars", async () => {
      render(
        <CrewSaveHarness
          editingId="c-11"
          form={{ name: "F",
            tech_ids: ["t-a", "orphan-abcdef12345678"] }}
          scopedTechs={[{ id: "t-a", name: "Alice" }]}
          incomingMembers={[]}
          apiPatchResult={{
            id: "c-11", name: "F", tech_ids: ["t-a"],
          }}
        />,
      );
      await act(async () => {
        fireEvent.click(screen.getByTestId("crew-save"));
      });
      expect(screen.getByTestId("toast-tone").textContent).toBe("warning");
      // ``"orphan-abcdef12345678".slice(0, 8)`` === "orphan-a".
      expect(screen.getByTestId("toast-message").textContent).toBe(
        "Saved, but these members couldn't be added: orphan-a");
    });

    it("multiple dropped ids are comma-joined in submission order",
      async () => {
        render(
          <CrewSaveHarness
            editingId="c-12"
            form={{ name: "M",
              tech_ids: ["t-a", "ghost-1", "ghost-2"] }}
            scopedTechs={[
              { id: "t-a",     name: "Alice" },
              { id: "ghost-1", name: "Ghost One" },
            ]}
            incomingMembers={[{ id: "ghost-2", name: "Ghost Two" }]}
            apiPatchResult={{
              id: "c-12", name: "M", tech_ids: ["t-a"],
            }}
          />,
        );
        await act(async () => {
          fireEvent.click(screen.getByTestId("crew-save"));
        });
        expect(screen.getByTestId("toast-message").textContent).toBe(
          "Saved, but these members couldn't be added: "
          + "Ghost One, Ghost Two");
      });
  });


// ══════════════════════════════════════════════════════════════════
//  Case 4  —  Source-level regex lock on OpsHub.jsx
//
//  Guards against a refactor that drops the diff branch or reverts
//  the save handler to the pre-QQ unconditional "Saved" toast.
// ══════════════════════════════════════════════════════════════════

describe("QQ Case 4 · OpsHub.jsx source regex lock", () => {
  const SRC = fs.readFileSync(
    path.resolve(__dirname, "../pages/ops/OpsHub.jsx"),
    "utf8",
  );

  it("save handler captures the api response into a local const", () => {
    // The pre-QQ shape was ``await api.patch(...)`` with no capture.
    // Lock the new shape: ``const _res = editing ? await api.patch...``
    expect(SRC).toMatch(
      /const\s+_res\s*=\s*editing[\s\S]{0,120}api\.patch[\s\S]{0,120}api\.post/);
  });

  it("save handler diffs submitted vs persisted tech_ids", () => {
    expect(SRC).toMatch(/_droppedIds\s*=\s*_submitted\.filter/);
  });

  it("save handler uses the exact dropped-members warning copy", () => {
    expect(SRC).toMatch(
      /Saved, but these members couldn't be added:/);
  });

  it("warning path emits tone=warning (not success)", () => {
    // The warning branch must set tone to "warning" so the toast
    // renders in the non-success tone.
    expect(SRC).toMatch(/tone:\s*"warning"[\s\S]{0,160}couldn't be added/);
  });

  it("name lookup prefers scopedTechs, then incomingMembers, then "
     + "slice(0, 8) fallback", () => {
    // Precedence lock: scopedTechs.find must come BEFORE
    // incomingMembers.find in the save handler. Slice between
    // unique markers of the Crews-component save handler so the
    // check isn't contaminated by other ``const save = async`` /
    // ``incomingMembers`` references elsewhere in OpsHub.jsx.
    const _startMarker = "Ticket QQ · Option A";
    const _endMarker   = "setToast({ tone: \"success\", message: \"Saved\" });";
    const _start = SRC.indexOf(_startMarker);
    const _end   = SRC.indexOf(_endMarker, _start);
    expect(_start).toBeGreaterThan(-1);
    expect(_end).toBeGreaterThan(_start);
    const _handler = SRC.substring(_start, _end);
    const _scopedIdx   = _handler.indexOf("scopedTechs");
    const _incomingIdx = _handler.indexOf("incomingMembers");
    const _sliceIdx    = _handler.indexOf("slice(0, 8)");
    expect(_scopedIdx).toBeGreaterThan(-1);
    expect(_incomingIdx).toBeGreaterThan(-1);
    expect(_sliceIdx).toBeGreaterThan(-1);
    expect(_scopedIdx).toBeLessThan(_incomingIdx);
    expect(_incomingIdx).toBeLessThan(_sliceIdx);
  });

  it("preserves the existing 400 error branch (foreign_tenant chips)",
    () => {
      // Lock on the error-detail consumption shape so the QQ ship
      // doesn't accidentally sever the TD-86 categorised 400 path.
      expect(SRC).toMatch(/e\?\.data\?\.detail/);
      expect(SRC).toMatch(/setBeErrors\(_errs\)/);
    });

  it("QQ-reopen · captures _preExisting from editing?.tech_ids", () => {
    // The reopen fix narrowed the warning to newly-added-this-session
    // ids only.  Lock on the pre-existing-ghost snapshot source.
    expect(SRC).toMatch(
      /_preExisting\s*=\s*new\s+Set\(\s*editing\s*&&\s*Array\.isArray\(editing\.tech_ids\)/);
  });

  it("QQ-reopen · _droppedIds filter excludes _preExisting ghosts",
    () => {
      // Lock on the narrowing predicate itself so a future refactor
      // that drops the ``!_preExisting.has(x)`` clause fails here
      // and re-widens the warning to pre-existing drift.
      expect(SRC).toMatch(
        /_droppedIds\s*=\s*_submitted\.filter\([\s\S]{0,80}!_preExisting\.has\(x\)/);
    });
});


// ══════════════════════════════════════════════════════════════════
//  Case 5  —  QQ-reopen · edit-mode pre-existing ghost does NOT warn
// ══════════════════════════════════════════════════════════════════

describe("QQ-reopen Case 5 · pre-existing ghost in edit-mode is silent",
  () => {
    it("submit matches editing.tech_ids, BE drops the ghost → plain Saved",
      async () => {
        render(
          <CrewSaveHarness
            editingId="c-X"
            // ``t-ghost`` is pre-existing in the opened crew doc —
            // the pre-save unavailable-chips banner owns surfacing
            // this to the operator; the post-save warning MUST NOT.
            editingTechIds={["t-live", "t-ghost"]}
            form={{ name: "X", tech_ids: ["t-live", "t-ghost"] }}
            scopedTechs={[{ id: "t-live", name: "Live Tech" }]}
            incomingMembers={[{ id: "t-ghost", name: "Soft-Deleted" }]}
            apiPatchResult={{
              id: "c-X", name: "X", tech_ids: ["t-live"],
            }}
          />,
        );
        await act(async () => {
          fireEvent.click(screen.getByTestId("crew-save"));
        });
        expect(screen.getByTestId("toast-tone").textContent).toBe("success");
        expect(screen.getByTestId("toast-message").textContent).toBe("Saved");
      });

    it("rename-only edit on a ghost-carrying crew → plain Saved", async () => {
      // Operator opens Edit, only touches the ``name`` field, hits
      // save.  Ghost was already in editing.tech_ids and still is
      // in form.tech_ids (TD-crew-edit-no-auto-remove seeds form
      // from the full stored list).  BE drops the ghost on save.
      // No warning must fire — the pre-save banner already surfaced
      // the ghost pre-save.
      render(
        <CrewSaveHarness
          editingId="c-X2"
          editingTechIds={["t-live-a", "t-live-b", "t-ghost-x"]}
          form={{ name: "renamed-crew",
                  tech_ids: ["t-live-a", "t-live-b", "t-ghost-x"] }}
          scopedTechs={[
            { id: "t-live-a", name: "Alice" },
            { id: "t-live-b", name: "Bob" },
          ]}
          incomingMembers={[{ id: "t-ghost-x", name: "Ghost X" }]}
          apiPatchResult={{
            id: "c-X2", name: "renamed-crew",
            tech_ids: ["t-live-a", "t-live-b"],
          }}
        />,
      );
      await act(async () => {
        fireEvent.click(screen.getByTestId("crew-save"));
      });
      expect(screen.getByTestId("toast-tone").textContent).toBe("success");
      expect(screen.getByTestId("toast-message").textContent).toBe("Saved");
    });
  });


// ══════════════════════════════════════════════════════════════════
//  Case 6  —  QQ-reopen · edit-mode newly-added-then-dropped DOES warn
// ══════════════════════════════════════════════════════════════════

describe("QQ-reopen Case 6 · newly-added-then-dropped in edit-mode warns",
  () => {
    it("operator adds a NEW member in-session, BE drops it → warn",
      async () => {
        render(
          <CrewSaveHarness
            editingId="c-Y"
            editingTechIds={["t-live"]}
            form={{ name: "Y",
                    tech_ids: ["t-live", "t-new-dropped"] }}
            scopedTechs={[
              { id: "t-live",        name: "Live Tech" },
              { id: "t-new-dropped", name: "New Addition" },
            ]}
            incomingMembers={[]}
            apiPatchResult={{
              id: "c-Y", name: "Y", tech_ids: ["t-live"],
            }}
          />,
        );
        await act(async () => {
          fireEvent.click(screen.getByTestId("crew-save"));
        });
        expect(screen.getByTestId("toast-tone").textContent).toBe("warning");
        expect(screen.getByTestId("toast-message").textContent).toBe(
          "Saved, but these members couldn't be added: New Addition");
      });
  });


// ══════════════════════════════════════════════════════════════════
//  Case 7  —  QQ-reopen · mixed drop warns ONLY for the new addition
// ══════════════════════════════════════════════════════════════════

describe("QQ-reopen Case 7 · mixed pre-existing-ghost + new-dropped",
  () => {
    it("warning names only the newly-added-this-session dropped id",
      async () => {
        // ``t-old-ghost`` is pre-existing (banner's problem).
        // ``t-new-dropped`` is session-added (warning's problem).
        // Only the latter should surface post-save.
        render(
          <CrewSaveHarness
            editingId="c-Z"
            editingTechIds={["t-live", "t-old-ghost"]}
            form={{ name: "Z",
                    tech_ids: ["t-live", "t-old-ghost",
                               "t-new-dropped"] }}
            scopedTechs={[
              { id: "t-live",        name: "Live Tech" },
              { id: "t-new-dropped", name: "New Dropped" },
            ]}
            incomingMembers={[{ id: "t-old-ghost", name: "Old Ghost" }]}
            apiPatchResult={{
              id: "c-Z", name: "Z", tech_ids: ["t-live"],
            }}
          />,
        );
        await act(async () => {
          fireEvent.click(screen.getByTestId("crew-save"));
        });
        expect(screen.getByTestId("toast-tone").textContent).toBe("warning");
        expect(screen.getByTestId("toast-message").textContent).toBe(
          "Saved, but these members couldn't be added: New Dropped");
        // Belt-+-braces: the pre-existing ghost's name must NOT
        // appear in the message.
        expect(screen.getByTestId("toast-message").textContent)
          .not.toMatch(/Old Ghost/);
      });
  });
