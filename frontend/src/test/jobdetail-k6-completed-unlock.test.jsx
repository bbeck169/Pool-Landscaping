/**
 * Phase K6 · Feb-2026 — Completed Job Unlock (Web) contract lock.
 *
 * The runtime JobDetail component depends on ``useAuth`` +
 * ``useParams`` + ``api`` with a complex bootstrap; the sibling
 * suites already cover the render path.  Here we lock the K6
 * unlock semantics via source inspection so:
 *   1. The K6 role set is present.
 *   2. The K6 banner renders only when
 *      ``canEditCompleted === true`` AND
 *      ``job.status === "completed"``.
 *   3. Customer / non-K6 role short-circuits ``canEditCompleted``.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobDetail.jsx"),
  "utf8",
);


describe("JobDetail · K6 completed-job unlock contract", () => {
  it("declares the K6_UNLOCK_ROLES set with the exact seven roles "
     + "(six staff + employee forward-compat)", () => {
    // Set literal — order-insensitive.
    expect(SRC).toMatch(/const\s+K6_UNLOCK_ROLES\s*=\s*new\s+Set\(/);
    for (const role of ["super_admin", "admin", "manager",
                                     "tech", "technician", "owner",
                                     // CLOSED-JOB-EDIT-UNLOCK · Feb-2026
                                     "employee"]) {
      expect(SRC).toMatch(
        new RegExp(`"${role}"`),
      );
    }
  });

  it("derives ``canEditCompleted`` from role + job.status only", () => {
    // The gate expression MUST include:
    //   1. ``!isCustomer``            → portal role short-circuit.
    //   2. K6_UNLOCK_ROLES.has(...)   → K6 whitelist.
    //   3. job?.status === "completed" → gate ONLY on completed jobs.
    expect(SRC).toMatch(/const\s+canEditCompleted\s*=/);
    expect(SRC).toMatch(/!isCustomer/);
    expect(SRC).toMatch(/K6_UNLOCK_ROLES\.has\(\s*user\?\.role\s*\|\|\s*""\s*\)/);
    expect(SRC).toMatch(
      /job\?\.status\s*===\s*"completed"/,
    );
  });

  it("renders the ``Editing after completion — this will be logged`` banner behind canEditCompleted", () => {
    // The banner block is gated ``canEditCompleted ? (<div … />) : null``
    // and carries the K6 testid.
    expect(SRC).toMatch(
      /\{\s*canEditCompleted\s*\?\s*\(\s*[\r\n]?\s*<div/,
    );
    expect(SRC).toMatch(
      /data-testid="jd-k6-edit-after-completion-banner"/,
    );
    expect(SRC).toMatch(
      /Editing after completion — this will be logged/,
    );
    // Banner mentions that priced fields on paid invoices are locked
    // — parity with the server-side 409 the operator would hit if
    // they tried anyway.
    expect(SRC).toMatch(/priced fields are blocked/);
    expect(SRC).toMatch(/Communication Timeline/);
  });

  it("Portal (customer) role is short-circuited by !isCustomer", () => {
    // The gate uses ``!isCustomer`` as the FIRST clause so a portal
    // user CAN'T flip ``canEditCompleted`` true even if a future
    // refactor accidentally adds "customer" to K6_UNLOCK_ROLES.
    const gate = SRC.slice(
      SRC.indexOf("const canEditCompleted"),
      SRC.indexOf("const canEditCompleted") + 400,
    );
    expect(gate).toMatch(/!isCustomer/);
    // The gate MUST NOT include ``"customer"`` in the role set — a
    // regression guard against a future accidental permission grant.
    expect(gate).not.toMatch(/"customer"/);
  });

  it("does NOT disable the JobBeforeAfterPhotos upload for K6 roles on a completed job", () => {
    // The photo component's ``readOnly`` prop is bound to
    // ``isCustomer`` only — K6 roles land there with readOnly=false
    // regardless of ``job.status``.  Regression guard.
    expect(SRC).toMatch(
      /<JobBeforeAfterPhotos[^>]*readOnly=\{isCustomer\}/,
    );
    // A regression that adds ``|| job.status === "completed"`` would
    // silently disable upload for admin/manager/tech on a completed
    // job — fail loudly if it lands.
    expect(SRC).not.toMatch(
      /readOnly=\{isCustomer\s*\|\|\s*job[?.]?\.?status\s*===\s*"completed"/,
    );
  });
});
