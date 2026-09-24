/**
 * Task M+P · Feb-2026 — Tech-visible Reopen (Web) contract lock.
 *
 * Mirrors the JobDetail contract-test convention (source-inspection
 * + a logic-mirror for the visibility matrix) established by
 * ``jobdetail-k6-completed-unlock.test.jsx``,
 * ``jobdetail-new-scheduled-job.test.jsx`` and
 * ``task-l-jobdetail-sr-photos.test.jsx``. Mounting the full 900-line
 * JobDetail component with its 20+ dependency stubs would be
 * disproportionate for the size of the delta — instead we:
 *
 *   1. Assert the JobDetail source contains the exact ``canReopen``
 *      / ``isAssignedTech`` / ``onReopen`` expressions we shipped
 *      in Commit 4.  Any drift breaks these assertions and forces
 *      the logic-mirror below to be re-synced.
 *
 *   2. Re-implement the ``canReopen`` expression as an in-test
 *      pure function (``evalCanReopen``) and enumerate all six
 *      role/status permutations from the Task M+P plan.
 *
 *   3. Assert the ChecklistModal + PoolChecklistWizard auto-unlock
 *      derivation still keys off ``report.submitted_at`` — the P
 *      leg of Task M+P depends on the SR clear (Commit 1) auto-
 *      propagating without any changes in either component.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const JOB_DETAIL_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobDetail.jsx"),
  "utf8",
);
const CHECKLIST_MODAL_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/checklist/ChecklistModal.jsx"),
  "utf8",
);
const POOL_WIZARD_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/checklist/PoolChecklistWizard.jsx"),
  "utf8",
);

// ────────────────────────────────────────────────────────────────
// Logic-mirror.  This function MUST stay in lock-step with the
// ``canReopen`` expression inside JobDetail.jsx — the source-lock
// test in the "canReopen source lock" describe block below enforces
// the mirror.  If a future refactor changes the expression, both
// this function AND the source-lock regex have to move together.
// ────────────────────────────────────────────────────────────────
function evalCanReopen({ isAdmin, isAssignedTech, status }) {
  return (
    (isAdmin && ["completed", "cancelled"].includes(status))
    || (isAssignedTech && status === "completed")
  );
}

describe("JobDetail · Task M+P Reopen — canReopen visibility matrix", () => {
  it("case 1 · admin + completed → visible", () => {
    expect(
      evalCanReopen({ isAdmin: true, isAssignedTech: false, status: "completed" }),
    ).toBe(true);
  });

  it("case 2 · admin + cancelled → visible", () => {
    expect(
      evalCanReopen({ isAdmin: true, isAssignedTech: false, status: "cancelled" }),
    ).toBe(true);
  });

  it("case 3 · admin + active → hidden (nothing to reopen)", () => {
    expect(
      evalCanReopen({ isAdmin: true, isAssignedTech: false, status: "active" }),
    ).toBe(false);
  });

  it("case 4 · assigned tech + completed → visible", () => {
    expect(
      evalCanReopen({ isAdmin: false, isAssignedTech: true, status: "completed" }),
    ).toBe(true);
  });

  it("case 5 · assigned tech + cancelled → hidden (E2 keeps cancelled admin-only)", () => {
    expect(
      evalCanReopen({ isAdmin: false, isAssignedTech: true, status: "cancelled" }),
    ).toBe(false);
  });

  it("case 6 · unassigned tech + completed → hidden", () => {
    expect(
      evalCanReopen({ isAdmin: false, isAssignedTech: false, status: "completed" }),
    ).toBe(false);
  });

  it("case 6b · non-staff (customer) + completed → hidden (no isAdmin, no isAssignedTech)", () => {
    // Belt-and-suspenders — a customer session with a "completed"
    // job payload MUST NOT surface the button.  isAssignedTech is
    // gated on ``isTech`` in JobDetail, so ``isAdmin=false`` +
    // ``isAssignedTech=false`` is the effective input.
    expect(
      evalCanReopen({ isAdmin: false, isAssignedTech: false, status: "completed" }),
    ).toBe(false);
  });
});

describe("JobDetail · Task M+P Reopen — canReopen source lock", () => {
  it("declares canReopen with the exact expression shipped in Commit 4", () => {
    // The regex captures the logic-mirror above verbatim — any
    // change to the JSX expression that isn't reflected in
    // ``evalCanReopen`` fails here first.
    expect(JOB_DETAIL_SRC).toMatch(/const\s+canReopen\s*=/);
    expect(JOB_DETAIL_SRC).toMatch(
      /isAdmin\s*&&\s*\[\s*["']completed["']\s*,\s*["']cancelled["']\s*\]\.includes\(\s*job\?\.status\s*\)/,
    );
    expect(JOB_DETAIL_SRC).toMatch(
      /isAssignedTech\s*&&\s*job\?\.status\s*===\s*["']completed["']/,
    );
  });

  it("derives isAssignedTech from job.technician_id + user.(technician_id||id)", () => {
    // Client-side heuristic — must gate on ``isTech`` first
    // (customers/admins never satisfy the assigned-tech branch).
    expect(JOB_DETAIL_SRC).toMatch(/const\s+isAssignedTech\s*=/);
    expect(JOB_DETAIL_SRC).toMatch(/isTech[\s\S]{0,80}job\?\.technician_id/);
    expect(JOB_DETAIL_SRC).toMatch(
      /job\.technician_id\s*===\s*\(\s*user\?\.technician_id\s*\|\|\s*user\?\.id\s*\)/,
    );
  });
});

describe("JobDetail · Task M+P Reopen — jd-reopen button contract", () => {
  it("preserves data-testid=\"jd-reopen\" verbatim (Commit 2 pytest keys off this)", () => {
    expect(JOB_DETAIL_SRC).toMatch(/testid=["']jd-reopen["']/);
  });

  it("renders the button ONLY when canReopen is truthy", () => {
    // The JSX site must be ``{canReopen ? (<Button ... testid="jd-reopen" ...>) : null}``.
    expect(JOB_DETAIL_SRC).toMatch(
      /\{\s*canReopen\s*\?\s*\(\s*<Button[^>]*testid=["']jd-reopen["']/,
    );
  });

  it("is HOISTED out of the isAdmin branch (regression guard on the Commit 4 move)", () => {
    // Before Commit 4 the reopen button lived inside
    // ``{isAdmin ? ( ... ["completed", "cancelled"].includes(job.status) ...) : null}``.
    // Guard the hoist by asserting the OLD shape (button
    // gated on ``["completed","cancelled"].includes(job.status)``
    // WITHOUT a canReopen wrapper) is gone.
    expect(JOB_DETAIL_SRC).not.toMatch(
      /\[\s*"completed"\s*,\s*"cancelled"\s*\]\.includes\(\s*job\.status\s*\)\s*\?\s*\(\s*<Button[^>]*testid=["']jd-reopen["']/,
    );
  });

  it("wires disabled={reopening} on the button (optimistic in-flight lock)", () => {
    expect(JOB_DETAIL_SRC).toMatch(
      /<Button[^>]*onClick=\{onReopen\}[^>]*disabled=\{reopening\}[^>]*testid=["']jd-reopen["']/,
    );
  });

  it("shows a distinct label while reopening is true", () => {
    // "Reopening…" copy → visual acknowledgement of the in-flight
    // POST while ``reopening`` is true; the ternary flips back to
    // "Reopen" on resolve/reject.
    expect(JOB_DETAIL_SRC).toMatch(
      /reopening\s*\?\s*["']Reopening…["']\s*:\s*["']Reopen["']/,
    );
  });
});

describe("JobDetail · Task M+P Reopen — onReopen error toast matrix", () => {
  it("case 7 · 403 → 'You aren\\'t authorized to reopen this job.'", () => {
    expect(JOB_DETAIL_SRC).toMatch(
      /if\s*\(\s*status\s*===\s*403\s*\)[\s\S]{0,140}You\s+aren't\s+authorized\s+to\s+reopen\s+this\s+job\./,
    );
  });

  it("case 8 · 409 → 'Cannot reopen — job is not in a reopenable state.'", () => {
    expect(JOB_DETAIL_SRC).toMatch(
      /status\s*===\s*409[\s\S]{0,140}Cannot\s+reopen\s+—\s+job\s+is\s+not\s+in\s+a\s+reopenable\s+state\./,
    );
  });

  it("case 9 · 400 → server serverMsg wins, fallback 'This job can\\'t be reopened right now.'", () => {
    // 400 branch must consult ``serverMsg`` first — that mirror
    // of ``err.data.detail`` / ``err.message`` is what surfaces
    // the backend's C1 message "Only completed jobs can be
    // reopened" verbatim.  The fallback string only fires when
    // the server returns 400 without a body.
    expect(JOB_DETAIL_SRC).toMatch(
      /status\s*===\s*400[\s\S]{0,200}toastMsg\s*=\s*serverMsg\s*\|\|\s*["']This job can't be reopened right now\.["']/,
    );
  });

  it("case 9b · server-provided detail.message precedence (Task J pattern)", () => {
    // Regression guard on the ``serverMsg`` resolution order —
    // ``err.data.detail.detail`` / ``.msg`` / ``.message`` is
    // consulted before ``err.message``.  Guarantees that a
    // backend-authored precondition string (e.g. C1) surfaces
    // verbatim rather than the FastAPI shape fallback.
    expect(JOB_DETAIL_SRC).toMatch(
      /const\s+serverMsg\s*=/,
    );
    expect(JOB_DETAIL_SRC).toMatch(
      /detail\.detail\s*\|\|\s*detail\.msg\s*\|\|\s*detail\.message/,
    );
  });

  it("case 10 · 500+/network → 'Something went wrong. Please try again.'", () => {
    // ``!status`` covers the network / timeout branch where
    // api.js threw an ``Error`` without a status field.  Both
    // cases funnel to the same generic toast.
    expect(JOB_DETAIL_SRC).toMatch(
      /!status\s*\|\|\s*status\s*>=\s*500[\s\S]{0,140}Something\s+went\s+wrong\.\s+Please\s+try\s+again\./,
    );
  });
});

describe("JobDetail · Task M+P Reopen — optimistic disable + success refetch", () => {
  it("case 11a · onReopen early-returns when reopening is already true", () => {
    // Reentrancy guard — prevents a double-click racing the
    // idempotency envelope on the backend.
    expect(JOB_DETAIL_SRC).toMatch(
      /const\s+onReopen\s*=\s*async\s*\(\s*\)\s*=>\s*\{\s*[\r\n]?\s*if\s*\(\s*reopening\s*\)\s*return\s*;/,
    );
  });

  it("case 11b · onReopen sets reopening=true BEFORE the POST", () => {
    // Order matters — the button must disable BEFORE api.post is
    // in-flight, not after.  Any regression that lifts
    // ``setReopening(true)`` below the POST breaks the
    // optimistic UI contract.
    const body = JOB_DETAIL_SRC.slice(
      JOB_DETAIL_SRC.indexOf("const onReopen"),
      JOB_DETAIL_SRC.indexOf("const onReopen") + 1200,
    );
    const setTrueIdx = body.indexOf("setReopening(true)");
    const postIdx = body.indexOf("api.post(`/jobs/");
    expect(setTrueIdx).toBeGreaterThan(-1);
    expect(postIdx).toBeGreaterThan(-1);
    expect(setTrueIdx).toBeLessThan(postIdx);
  });

  it("case 11c · onReopen resets reopening=false in a finally block", () => {
    // ``finally`` ensures re-enable on BOTH the success + error
    // paths.  A try/catch without finally would leak the disabled
    // state on unhandled exceptions.
    expect(JOB_DETAIL_SRC).toMatch(
      /finally\s*\{\s*[\r\n]?\s*setReopening\(false\)\s*;\s*[\r\n]?\s*\}/,
    );
  });

  it("case 12 · onReopen success path calls load() to refetch job + detail", () => {
    // ``load()`` fires both ``GET /jobs/{id}`` and
    // ``GET /jobs/{id}/detail`` — the SR ``submitted_at`` clear
    // from Commit 1 propagates via the second call.  Regression
    // guard: the try-block MUST await api.post + await load()
    // (in that order) before the success toast lands.
    const body = JOB_DETAIL_SRC.slice(
      JOB_DETAIL_SRC.indexOf("const onReopen"),
      JOB_DETAIL_SRC.indexOf("const onReopen") + 1200,
    );
    const postIdx = body.indexOf("api.post(`/jobs/");
    const loadIdx = body.indexOf("await load()");
    expect(postIdx).toBeGreaterThan(-1);
    expect(loadIdx).toBeGreaterThan(postIdx);
  });

  it("case 12b · onReopen surfaces a success toast on 200", () => {
    // Same shape used by every other JobDetail action —
    // ``setToast({ tone: "success", message: "…" })``.
    expect(JOB_DETAIL_SRC).toMatch(
      /setToast\(\{\s*tone:\s*["']success["']\s*,\s*message:\s*["']Job reopened["']\s*\}\)/,
    );
  });
});

describe("ChecklistModal / PoolChecklistWizard · Task M+P — auto-unlock derivation", () => {
  it("case 13a · ChecklistModal derives locked from report.submitted_at only", () => {
    // The P leg of Task M+P depends on this exact derivation
    // staying intact — after Commit 1 clears ``submitted_at``
    // on the tech's SR, this expression flips to false on the
    // next fetch and the checklist auto-unlocks with zero
    // component-level changes.
    expect(CHECKLIST_MODAL_SRC).toMatch(
      /const\s+locked\s*=\s*!!report\.submitted_at\s*;/,
    );
  });

  it("case 13b · PoolChecklistWizard receives locked as a prop (no local override)", () => {
    // The wizard MUST NOT compute its own ``locked`` — the
    // parent ChecklistModal owns the derivation so a single
    // source of truth (``report.submitted_at``) drives both
    // paths.  A regression that shadows the prop with a local
    // computation breaks Task M+P auto-unlock.
    expect(POOL_WIZARD_SRC).toMatch(
      /function\s+PoolChecklistWizard\([\s\S]{0,400}locked\s*,/,
    );
    // Regression guard — no ``const locked =`` shadowing the
    // prop inside the wizard body.
    expect(POOL_WIZARD_SRC).not.toMatch(
      /const\s+locked\s*=\s*!!report/,
    );
  });
});
