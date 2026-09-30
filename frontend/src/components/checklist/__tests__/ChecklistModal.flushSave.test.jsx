/**
 * Feb-2026 · Water-bodies autosave-wipe fix — payload-builder contract.
 *
 * The full ``<ChecklistModal />`` mounts a 900-LOC modal with dozens
 * of dependencies (Konva, timers, refs, api layer, sub-forms).
 * Rather than fight that surface, we export a pure helper
 * ``buildFlushSavePayload`` from ``ChecklistModal.jsx`` that
 * captures the exact patch shape ``flushSave`` sends to the backend.
 * These specs assert the helper's contract directly:
 *
 *   1. body[0].chemicals_used synced from cur.chemicals_added.
 *   2. body[0].readings synced from cur.chemical_readings.
 *   3. Explicit clear ([]) propagates on both channels so the FE
 *      always dual-writes clears.
 *   4. Non-first bodies (spa/multi-body) passed through untouched.
 *   5. Empty / absent ``cur.water_bodies`` omits the key entirely
 *      (no crash on the length guard).
 *   6. Non-array top-level values (defensive) preserve body[0].
 */
import { describe, it, expect } from "vitest";
import {
  buildFlushSavePayload,
} from "@/components/checklist/ChecklistModal";


const _CHEMS = [
  { id: "c1", name: "Muriatic acid", amount: "1", unit: "cup" },
  { id: "c2", name: "Chlorine tabs", amount: "3", unit: "tabs" },
];
const _READINGS = [
  { key: "ph", name: "pH", value: 7.4 },
  { key: "fc", name: "Free Cl", value: 3.0 },
];

const _basePoolBody = (overrides = {}) => ({
  id: "b-pool",
  type: "pool",
  sequence: 0,
  label: "Pool",
  readings: [],
  chemicals_used: [],
  media: [],
  notes: "",
  ...overrides,
});

const _baseCur = (overrides = {}) => ({
  chemical_readings: _READINGS,
  chemicals_added: _CHEMS,
  checklist_items: [],
  notes: "",
  internal_notes: "",
  customer_notes: "",
  photos: [],
  wizard_step: 1,
  water_bodies: [_basePoolBody()],
  ...overrides,
});


describe("buildFlushSavePayload — body[0] sync from legacy top-level", () => {
  it("syncs body[0].chemicals_used from cur.chemicals_added", () => {
    const cur = _baseCur();
    const payload = buildFlushSavePayload(cur);
    expect(payload.water_bodies[0].chemicals_used).toEqual(_CHEMS);
    // Top-level still carries the same fresh list.
    expect(payload.chemicals_added).toEqual(_CHEMS);
  });

  it("syncs body[0].readings from cur.chemical_readings", () => {
    const cur = _baseCur();
    const payload = buildFlushSavePayload(cur);
    expect(payload.water_bodies[0].readings).toEqual(_READINGS);
    expect(payload.chemical_readings).toEqual(_READINGS);
  });

  it("body[0] is a CLONE — not a shared reference to the input", () => {
    // A shared reference would leak later mutations back into
    // ``reportRef.current`` and could trigger cascading re-renders.
    const cur = _baseCur();
    const payload = buildFlushSavePayload(cur);
    expect(payload.water_bodies[0]).not.toBe(cur.water_bodies[0]);
  });
});


describe("buildFlushSavePayload — explicit-clear semantics", () => {
  it("empty cur.chemicals_added propagates as empty body[0].chemicals_used", () => {
    // The FE is the ONLY channel that can carry an explicit clear
    // through to the backend — deliberate wipes MUST dual-write [].
    const cur = _baseCur({
      chemicals_added: [],
      water_bodies: [_basePoolBody({ chemicals_used: _CHEMS })],
    });
    const payload = buildFlushSavePayload(cur);
    expect(payload.chemicals_added).toEqual([]);
    expect(payload.water_bodies[0].chemicals_used).toEqual([]);
  });

  it("empty cur.chemical_readings propagates as empty body[0].readings", () => {
    const cur = _baseCur({
      chemical_readings: [],
      water_bodies: [_basePoolBody({ readings: _READINGS })],
    });
    const payload = buildFlushSavePayload(cur);
    expect(payload.chemical_readings).toEqual([]);
    expect(payload.water_bodies[0].readings).toEqual([]);
  });
});


describe("buildFlushSavePayload — multi-body preservation", () => {
  it("non-first bodies (spa) are passed through untouched", () => {
    // Multi-body edits currently ride ``water_bodies`` directly
    // and aren't dual-written to the legacy top-level. body[1..]
    // MUST NOT be mutated by the body[0]-only sync.
    const spa = {
      id: "b-spa", type: "spa", sequence: 1, label: "Spa",
      readings: [{ key: "ph", name: "pH", value: 6.8 }],
      chemicals_used: [{ id: "sp1", name: "Spa shock", amount: "1", unit: "oz" }],
      media: [], notes: "",
    };
    const cur = _baseCur({ water_bodies: [_basePoolBody(), spa] });
    const payload = buildFlushSavePayload(cur);
    // body[0] synced from top-level, body[1] identical to input.
    expect(payload.water_bodies).toHaveLength(2);
    expect(payload.water_bodies[1].readings).toEqual(spa.readings);
    expect(payload.water_bodies[1].chemicals_used).toEqual(spa.chemicals_used);
  });
});


describe("buildFlushSavePayload — length + shape guards", () => {
  it("omits water_bodies key when cur.water_bodies is empty", () => {
    const cur = _baseCur({ water_bodies: [] });
    const payload = buildFlushSavePayload(cur);
    expect(payload).not.toHaveProperty("water_bodies");
    // Legacy top-level still populated.
    expect(payload.chemicals_added).toEqual(_CHEMS);
  });

  it("omits water_bodies key when cur.water_bodies is undefined", () => {
    const cur = _baseCur();
    delete cur.water_bodies;
    const payload = buildFlushSavePayload(cur);
    expect(payload).not.toHaveProperty("water_bodies");
  });

  it("omits water_bodies key when cur.water_bodies is null (legacy shape)", () => {
    const cur = _baseCur({ water_bodies: null });
    const payload = buildFlushSavePayload(cur);
    expect(payload).not.toHaveProperty("water_bodies");
  });

  it("preserves body[0].chemicals_used when cur.chemicals_added is non-array", () => {
    // Defensive fallback: a legacy caller might pass ``null`` on the
    // legacy top-level.  The sync MUST NOT overwrite the body's
    // list with a garbage top-level shape.
    const cur = _baseCur({
      chemicals_added: null,
      water_bodies: [_basePoolBody({ chemicals_used: _CHEMS })],
    });
    const payload = buildFlushSavePayload(cur);
    expect(payload.water_bodies[0].chemicals_used).toEqual(_CHEMS);
  });

  it("preserves body[0].readings when cur.chemical_readings is non-array", () => {
    const cur = _baseCur({
      chemical_readings: null,
      water_bodies: [_basePoolBody({ readings: _READINGS })],
    });
    const payload = buildFlushSavePayload(cur);
    expect(payload.water_bodies[0].readings).toEqual(_READINGS);
  });
});


describe("buildFlushSavePayload — non-water-body fields", () => {
  it("passes through checklist_items, notes, photos, wizard_step, internal/customer notes", () => {
    const cur = _baseCur({
      checklist_items: [{ id: "i1", done: true }],
      notes: "n",
      internal_notes: "in",
      customer_notes: "cn",
      photos: ["p1"],
      wizard_step: 3,
    });
    const payload = buildFlushSavePayload(cur);
    expect(payload.checklist_items).toEqual([{ id: "i1", done: true }]);
    expect(payload.notes).toBe("n");
    expect(payload.internal_notes).toBe("in");
    expect(payload.customer_notes).toBe("cn");
    expect(payload.photos).toEqual(["p1"]);
    expect(payload.wizard_step).toBe(3);
  });

  it("defaults internal_notes / customer_notes / photos when missing on cur", () => {
    const cur = _baseCur();
    delete cur.internal_notes;
    delete cur.customer_notes;
    delete cur.photos;
    delete cur.wizard_step;
    const payload = buildFlushSavePayload(cur);
    expect(payload.internal_notes).toBe("");
    expect(payload.customer_notes).toBe("");
    expect(payload.photos).toEqual([]);
    expect(payload.wizard_step).toBe(1);
  });
});
