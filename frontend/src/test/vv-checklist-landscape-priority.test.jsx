/**
 * Ticket VV · Feb-2026 — FE checklist resolver flips to
 * LANDSCAPE PRIORITY to mirror the BE
 * (``backend/routers/jobs.py::_derive_checklist_kind`` L560-566,
 * already landscape-first) and the TD-69 sibling resolver
 * (``frontend/src/lib/portalServiceType.js::resolveServiceType``).
 *
 * Pre-VV bug: a job whose ``service_type`` / ``title`` / ``job_type``
 * concatenation contained BOTH a pool-ish token (e.g. "pool",
 * "chem") AND a landscape-ish token (e.g. "lawn", "mow",
 * "landscap", "garden", "trim", "blow", "cleanup") was resolved to
 * "pool" on the FE and "landscape" on the BE — drift.  Scope: only
 * jobs with ``checklist_kind`` null (BE stamps non-null on insert).
 *
 * This file is the regression lock on the VV flip.
 */
import { describe, it, expect } from "vitest";
import { getChecklistType } from "@/lib/checklistType";


describe("VV · getChecklistType landscape-priority flip", () => {

  // ── (a) THE OPERATOR'S BUG ─────────────────────────────────────
  it("(a) 'Pool View Estates Lawn Service' (both keywords, no "
     + "checklist_kind) → 'landscaping' — landscape wins", () => {
    expect(getChecklistType({
      title: "Pool View Estates Lawn Service",
      service_type: null, job_type: null, checklist_kind: null,
    })).toBe("landscaping");
  });

  // ── (b) mixed signal across fields ────────────────────────────
  it("(b) service_type='Pool Maintenance' + title='mow and trim' "
     + "(no checklist_kind) → 'landscaping' — mixed-signal lock",
    () => {
      expect(getChecklistType({
        service_type: "Pool Maintenance",
        title: "mow and trim",
        checklist_kind: null,
      })).toBe("landscaping");
    });

  // ── (c) pool-only regression lock ─────────────────────────────
  it("(c) pool-only title ('Weekly Pool Cleaning') with no "
     + "landscape keyword → 'pool' — pool branch intact", () => {
    expect(getChecklistType({
      title: "Weekly Pool Cleaning",
      service_type: null, job_type: null, checklist_kind: null,
    })).toBe("pool");
  });

  // ── (d) landscape-only regression lock ────────────────────────
  it("(d) landscape-only title ('Weekly Mowing') → 'landscaping'",
    () => {
      expect(getChecklistType({
        title: "Weekly Mowing",
        service_type: null, job_type: null, checklist_kind: null,
      })).toBe("landscaping");
    });

  // ── (e) override wins over landscape keywords ─────────────────
  it("(e) checklist_kind='pool' overrides a landscape-keyword'd "
     + "title → 'pool'", () => {
    expect(getChecklistType({
      title: "Weekly Mowing",
      checklist_kind: "pool",
    })).toBe("pool");
  });

  // ── (f) override wins over pool keywords ──────────────────────
  it("(f) checklist_kind='landscape' overrides a pool-keyword'd "
     + "title → 'landscaping'", () => {
    expect(getChecklistType({
      title: "Weekly Pool Cleaning",
      checklist_kind: "landscape",
    })).toBe("landscaping");
    // Also accept the ``"landscaping"`` variant (BE stamps
    // ``"landscape"``; some legacy writes stamp ``"landscaping"``).
    expect(getChecklistType({
      title: "Weekly Pool Cleaning",
      checklist_kind: "landscaping",
    })).toBe("landscaping");
  });

  // ── (g) tech-department tie-breaker ───────────────────────────
  it("(g) no keywords, technician_department='landscaping' → "
     + "'landscaping' — dept tie-breaker intact", () => {
    expect(getChecklistType({
      title: "Scheduled visit",   // no landscape / pool keyword
      service_type: null, job_type: null,
      technician_department: "landscaping",
      checklist_kind: null,
    })).toBe("landscaping");
  });

  // ── (h) generic fallback ──────────────────────────────────────
  it("(h) no keywords, no dept → 'generic' — Phase P36.1 fallback "
     + "intact", () => {
    expect(getChecklistType({
      title: "Scheduled visit",
      service_type: null, job_type: null,
      technician_department: null,
      checklist_kind: null,
    })).toBe("generic");
  });

  // ── (i) null-safety ───────────────────────────────────────────
  it("(i) null job → 'generic' (null-safety lock)", () => {
    expect(getChecklistType(null)).toBe("generic");
    expect(getChecklistType(undefined)).toBe("generic");
  });
});
