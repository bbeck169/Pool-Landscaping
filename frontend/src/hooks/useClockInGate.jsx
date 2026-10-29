import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api";
import { useAuth } from "@/auth";

/**
 * Phase 56.3 · Feb-2026 · Clock-in gate for landscape technicians.
 *
 * ─── Who is "a landscaper"? ──────────────────────────────────────
 * ``db.users.role`` in this codebase never contains the string
 * ``landscaper`` — every seed user with ``email = landscaper@…``
 * has ``role = "technician"``.  The "landscaper" concept is
 * captured on ``users.department`` and appears in the wild as
 * ``landscaping`` (canonical), ``landscape_tech`` (seed shape),
 * ``landscaper`` (legacy), and ``both`` (cross-trained).  All four
 * are gated.  Pool-only techs, admins, managers, super_admins, and
 * customers bypass the gate.
 *
 * ─── Landscape dept set (matches the frontend gate only) ─────────
 * The backend's ``_require_landscaping`` gate additionally lets
 * admin / super_admin through — that's the CORRECT server-side
 * behaviour (admins may query anyone's status).  Client-side we
 * exclude admin/manager/super_admin so those users never see the
 * dialog on their own screens.
 */
const _LANDSCAPE_DEPTS = new Set([
  "landscaping", "landscape_tech", "landscaper", "both",
]);

function _isLandscapeTech(user) {
  const role = String(user?.role || "").toLowerCase();
  const dept = String(user?.department || "").toLowerCase();
  return role === "technician" && _LANDSCAPE_DEPTS.has(dept);
}


// ─── Shared cached status probe ─────────────────────────────────
// A tiny module-level cache so N ``<OnMyWayButton>`` instances that
// mount at the same time share ONE ``GET /timeclock/mine-status``
// round trip.  Keyed by ``user.id`` so a role-switch during a
// session (rare) invalidates automatically.  The cache holds an
// in-flight ``Promise`` between the first read and the response so
// racing callers de-dupe as well.
const _statusCache = new Map(); // user_id → { promise?, value?, error? }

function _fetchStatus(userId) {
  const cached = _statusCache.get(userId);
  if (cached?.value !== undefined) return Promise.resolve(cached.value);
  if (cached?.promise) return cached.promise;
  const p = api.get("/timeclock/mine-status")
    .then((s) => {
      const val = !!s?.clocked_in;
      _statusCache.set(userId, { value: val });
      return val;
    })
    .catch(() => {
      // Fail-open — the checklist opener does the same in
      // ``openJob``.  A 403 on a non-landscape role (shouldn't
      // happen because the caller short-circuits, but defensive)
      // or a transient network error must NEVER lock a tech out
      // of their buttons.
      _statusCache.set(userId, { value: true });
      return true;
    });
  _statusCache.set(userId, { promise: p });
  return p;
}

function _invalidateStatus(userId, nextValue) {
  _statusCache.set(userId, { value: !!nextValue });
}


/**
 * ``useClockInStatus`` — synchronous ``isClockedIn`` + ``isChecking``
 * for landscape techs.  Non-landscape users are always considered
 * "clocked in" so any ``disabled = !isClockedIn`` gate they render
 * is a no-op.
 */
export function useClockInStatus() {
  const { user } = useAuth() || {};
  const gated = _isLandscapeTech(user);
  const [isClockedIn, setIsClockedIn] = useState(!gated);
  const [isChecking, setIsChecking] = useState(false);

  useEffect(() => {
    if (!gated || !user?.id) return;
    let cancelled = false;
    setIsChecking(true);
    _fetchStatus(user.id).then((val) => {
      if (cancelled) return;
      setIsClockedIn(val);
      setIsChecking(false);
    });
    return () => {
      cancelled = true;
    };
  }, [gated, user?.id]);

  const refresh = useCallback(async () => {
    if (!gated || !user?.id) return true;
    // Force a fresh probe (drop cache).
    _statusCache.delete(user.id);
    setIsChecking(true);
    const val = await _fetchStatus(user.id);
    setIsClockedIn(val);
    setIsChecking(false);
    return val;
  }, [gated, user?.id]);

  return { isClockedIn, isChecking, isGated: gated && !isClockedIn, refresh };
}


/**
 * ``useClockInGate(user)`` — opener-level gate (imperative).
 *
 * Wraps a job-open action (checklist modal, navigate) with a
 * clock-in-required prompt for landscape techs.  Non-landscape
 * users take the fast path and never see the dialog.
 *
 * Usage (unchanged from Phase 56.3):
 *   const gate = useClockInGate(user);
 *   <button onClick={() => gate.openJob(jobId, () => setChecklist(jobId))}>
 *   <ClockInGateDialog gate={gate} />
 */
export function useClockInGate(user) {
  const navigate = useNavigate();
  const gated = _isLandscapeTech(user);
  const [pendingJob, setPendingJob] = useState(null); // {jobId, cb}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const openJob = useCallback(async (jobId, cb) => {
    // Ticket 1 · Feb-2026 — "landscape techs may VIEW routes while
    // off the clock".  ``cb`` now receives a ``{readOnly}`` object
    // so the opener can render the checklist modal in a view-only
    // mode when the tech is not clocked in.  Mutations inside the
    // modal pop the dialog via ``requestMutation`` below.
    //
    // Backward-compat: cb may be a zero-arg function from legacy
    // callers; the object is passed as the first arg and ignored
    // by callers that don't destructure it.
    if (!gated) {
      cb ? cb({ readOnly: false }) : navigate(`/jobs/${jobId}`);
      return;
    }
    try {
      const clockedIn = await _fetchStatus(user?.id);
      // Phase 56.3 kept the dialog here; Ticket 1 flips to view-only
      // so the tech can still inspect the job + the day's route
      // without being blocked.
      cb
        ? cb({ readOnly: !clockedIn })
        : (clockedIn
            ? navigate(`/jobs/${jobId}`)
            : setPendingJob({ jobId, cb: () => navigate(`/jobs/${jobId}`) }));
    } catch {
      cb ? cb({ readOnly: false }) : navigate(`/jobs/${jobId}`);
    }
  }, [gated, navigate, user?.id]);

  // Ticket 1 · Feb-2026 — explicit mutation gate.  Callers invoke
  // this when a user attempts to mutate inside a view-only
  // checklist modal; the dialog pops with the same "Clock in
  // required" copy as the pre-ticket flow.  On successful clock-
  // in, ``onProceed`` runs (e.g. to flip ``readOnly`` to false on
  // the already-open modal); on cancel, the modal stays view-only.
  const requestMutation = useCallback((jobId, onProceed) => {
    if (!gated) {
      // Shouldn't happen (non-landscape callers never render the
      // mutation-block path), but defensive — just run the proceed
      // callback since no gate applies.
      onProceed?.();
      return;
    }
    setPendingJob({ jobId, cb: onProceed || (() => {}) });
  }, [gated]);

  const clockInAndProceed = useCallback(async () => {
    if (!pendingJob) return;
    setBusy(true);
    setError("");
    try {
      // Best-effort GPS. ``POST /timeclock/punch`` accepts null
      // coords (``geo_denied`` flag) so denied permissions do not
      // block the punch.
      const coords = await new Promise((resolve) => {
        if (!navigator?.geolocation) return resolve({ denied: true });
        navigator.geolocation.getCurrentPosition(
          (pos) => resolve({
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy_m: pos.coords.accuracy,
            denied: false,
          }),
          () => resolve({ denied: true }),
          { enableHighAccuracy: false, timeout: 4000 },
        );
      });
      await api.post("/timeclock/punch", {
        punch_type: "in",
        source: "web",
        lat: coords.lat ?? null,
        lng: coords.lng ?? null,
        accuracy_m: coords.accuracy_m ?? null,
        geo_denied: !!coords.denied,
      });
      // Warm the shared status cache so ``<OnMyWayButton>`` and
      // any other gated affordance flip to enabled on the next
      // render without a second network round trip.
      if (user?.id) _invalidateStatus(user.id, true);
      const cb = pendingJob.cb;
      setPendingJob(null);
      cb?.();
    } catch (e) {
      setError(e?.message || "Failed to clock in. Please try again.");
    } finally {
      setBusy(false);
    }
  }, [pendingJob, user?.id]);

  const cancel = useCallback(() => {
    if (busy) return;
    setPendingJob(null);
    setError("");
  }, [busy]);

  return { openJob, requestMutation, pendingJob, clockInAndProceed, cancel, busy, error, gated };
}

/**
 * Renderer for the clock-in dialog. Consumers mount
 * ``<ClockInGateDialog gate={gate} />`` once inside their component
 * tree so the dialog surfaces when needed.
 *
 * Feb-2026 · Copy aligned with the task-spec strings verbatim:
 *   • Title : ``Clock in required``
 *   • Body  : ``You must clock in before starting this job``
 *   • CTA   : ``Clock In Now``
 *   • Cancel: ``Cancel``
 */
export function ClockInGateDialog({ gate }) {
  if (!gate?.pendingJob) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15, 23, 42, 0.55)" }}
      data-testid="clockin-gate-dialog"
    >
      <div
        className="rounded-2xl p-6 max-w-md w-full shadow-2xl"
        style={{ background: "#fff", border: "1px solid #E5E7EB" }}
      >
        <h3
          className="text-lg font-bold mb-2"
          style={{ color: "#0F172A" }}
          data-testid="clockin-gate-title"
        >
          Clock in required
        </h3>
        <p
          className="text-sm mb-4"
          style={{ color: "#334155" }}
          data-testid="clockin-gate-body"
        >
          You must clock in before starting this job
        </p>
        {gate.error ? (
          <div
            className="text-xs mb-3"
            style={{ color: "#B91C1C" }}
            data-testid="clockin-gate-error"
          >
            {gate.error}
          </div>
        ) : null}
        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={gate.cancel}
            disabled={gate.busy}
            className="px-3 py-1.5 rounded-md text-sm font-semibold"
            style={{
              background: "transparent",
              border: "1px solid #CBD5E1",
              color: "#0F172A",
            }}
            data-testid="clockin-gate-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={gate.clockInAndProceed}
            disabled={gate.busy}
            className="px-3 py-1.5 rounded-md text-sm font-bold"
            style={{ background: "#16A34A", color: "#fff", border: 0 }}
            data-testid="clockin-gate-confirm"
          >
            {gate.busy ? "Clocking in…" : "Clock In Now"}
          </button>
        </div>
      </div>
    </div>
  );
}


// ─── Test-only helper ───────────────────────────────────────────
// Exposed so unit-test files can reset the module-level cache
// between specs.  Not part of the public API.
export function __resetClockInStatusCacheForTests() {
  _statusCache.clear();
}
