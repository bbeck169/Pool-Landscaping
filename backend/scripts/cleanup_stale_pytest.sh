#!/bin/sh
# Phase I1.7.e · Feb-2026 — Stale pytest watchdog.
#
# Kills ``python -m pytest`` / ``python -m pytest ...`` processes that
# have been running longer than STALE_MINUTES (default: 30). Ships with
# a preview-env cron entry (see ``/etc/cron.d/pytest-watchdog``) that
# invokes this every 5 minutes.
#
# Trigger context: on 8-Feb-2026 a leaked pytest process (PID 6591,
# ~1h20m runtime) saturated MongoDB with ~800 connections and tripped
# ``maxIncomingConnections``. Preview backend + mongod had to be
# restarted. This watchdog catches the same pattern within one cron
# tick (5 min), well under the 30-min saturation threshold observed.
#
# Sibling guardrails:
#   * ``pytest.ini`` — ``timeout = 120`` (per-test) +
#     ``session_timeout = 1200`` (full session).
#
# Usage:
#   $ backend/scripts/cleanup_stale_pytest.sh           # dry-run + kill
#   $ STALE_MINUTES=45 backend/scripts/cleanup_stale_pytest.sh
#   $ DRY_RUN=1 backend/scripts/cleanup_stale_pytest.sh   # log only
#
# Exit code is always 0 (never surface failures to cron).
set -u

STALE_MINUTES="${STALE_MINUTES:-30}"
DRY_RUN="${DRY_RUN:-0}"
LOG="${STALE_PYTEST_LOG:-/var/log/pytest-watchdog.log}"

log() {
    ts="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "[$ts] $*" >>"$LOG" 2>/dev/null || true
    # Also echo to stdout for cron mail (if configured).
    echo "[$ts] $*"
}

# Collect PIDs whose cmdline mentions ``pytest`` AND whose elapsed
# runtime exceeds STALE_MINUTES. ``ps -eo etimes`` returns runtime in
# whole seconds; multiply the threshold accordingly.
threshold_s=$(( STALE_MINUTES * 60 ))
killed=0
scanned=0

# ``-o pid,etimes,cmd`` — POSIX-safe. Skip header via ``tail -n +2``.
ps -eo pid,etimes,cmd 2>/dev/null | tail -n +2 | while IFS= read -r line; do
    # Trim leading whitespace so field splitting is deterministic.
    line=$(echo "$line" | sed 's/^[[:space:]]*//')
    pid=$(echo "$line" | awk '{print $1}')
    etimes=$(echo "$line" | awk '{print $2}')
    cmd=$(echo "$line" | cut -d' ' -f3-)

    # Only pytest procs. Match both ``python -m pytest`` and direct
    # ``pytest`` invocations. Exclude this watchdog itself.
    case "$cmd" in
        *"python -m pytest"*|*"python3 -m pytest"*|"pytest "*|"/root/.venv/bin/pytest"*|*"venv/bin/pytest"*)
            ;;
        *)
            continue
            ;;
    esac

    scanned=$((scanned + 1))

    # etimes may be blank / non-numeric on kernel-thread rows — skip.
    case "$etimes" in
        ''|*[!0-9]*) continue ;;
    esac

    if [ "$etimes" -lt "$threshold_s" ]; then
        continue
    fi

    if [ "$DRY_RUN" = "1" ]; then
        log "DRY_RUN would kill pid=$pid etimes=${etimes}s cmd=$cmd"
        continue
    fi

    log "killing stale pytest pid=$pid etimes=${etimes}s (>${threshold_s}s) cmd=$cmd"
    # SIGTERM first, then SIGKILL after a short grace window.
    kill -TERM "$pid" 2>/dev/null || true
    sleep 3
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
        log "SIGKILL sent pid=$pid"
    fi
    killed=$((killed + 1))
done

# NOTE: the ``while`` above runs in a subshell (pipe), so ``killed`` /
# ``scanned`` don't propagate. Recount for the summary log line.
final_scanned=$(ps -eo pid,cmd 2>/dev/null | grep -cE "python[3]? -m pytest|/venv/bin/pytest|/root/\.venv/bin/pytest" || true)
log "watchdog pass complete. stale_minutes=$STALE_MINUTES dry_run=$DRY_RUN active_pytest_procs=$final_scanned"

exit 0
