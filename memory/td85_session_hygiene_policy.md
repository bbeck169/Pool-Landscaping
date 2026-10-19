# TD-85 · Expo pod session-hygiene precheck · policy + tooling

**Date:** 2026-02-18
**Ship:** `td85 · session-hygiene precheck script + policy`

---

## Problem

The TD-61 standing discipline requires:

> _"Session hygiene: `git status --short | wc -l == 0` precheck before committing."_

On the Expo pod this is **permanently unreachable**: `git status --short` returns about **1,900 dirty paths** on every single invocation, from a mix of:

1. **Parallel-session artifacts** — the Expo specialist runs Jest/Metro in `/app/mobile/*` which rewrites a published artefact (`mobile/artifacts/offline-mode-verification.txt`) and regenerates typegen output (`mobile/.expo/types/router.d.ts`) on every run.
2. **Transient tool caches** — `__pycache__/`, `*.pyc`, `.ruff_cache/`, `.pytest_cache/`, `.mypy_cache/`, `mobile/.metro-cache/`.
3. **Platform-published env templates** — `backend/.env.example`, `frontend/.env.example`, `mobile/.env.example` are published by the platform at pod boot; they are untracked but never agent-authored.
4. **Yarn + Node build output** — `.yarn-integrity`, `frontend/build/`, `node_modules/`.

None of this is agent-authored drift. The `--only -- <paths>` discipline on commits is what actually protects commit atomicity; the `wc -l == 0` precheck was effectively a no-op guideline that was being skipped silently every cycle.

## Fix

Ship a **narrower precheck** that excludes the known-noise paths and reports a "material drift" count — the subset of `git status` that is NOT in the noise allowlist. Material drift = 0 means session hygiene is clean (nothing agent-authored is uncommitted).

### Script

- `scripts/td85_session_hygiene_precheck.sh` — bash, exits 0 if material drift is 0, exits 1 otherwise. On exit 1, prints the material-drift paths so the operator / agent can decide whether to stash, commit, or revert them.

### Noise allowlist (locked in the script)

```
__pycache__/, *.pyc              # Python bytecode caches
.ruff_cache/, .pytest_cache/, .mypy_cache/
mobile/.expo/                    # Expo CLI typegen output
mobile/.metro-cache/             # Metro bundler cache
backend/.env.example             # Platform-published env templates
frontend/.env.example
mobile/.env.example
mobile/artifacts/offline-mode-verification.txt   # Jest artefact
.yarn-integrity                  # Yarn integrity file
frontend/build/, node_modules/   # Node build output
```

### Policy

- Agent-side atomic commits continue to use `git commit --only -- <paths>`. **This is the load-bearing guard.** The precheck is a defensive sanity check, not a gate.
- Before an atomic ship, agent SHOULD run the TD-85 precheck. If it exits 1, review the material-drift list and decide:
  - Material drift IS the ship → proceed with `--only --` naming those paths.
  - Material drift is OUT of ship → `git stash push -- <paths>` before committing.
- The TD-61 session-hygiene bullet in process docs is replaced by this policy. The old literal `wc -l == 0` guideline is retired as unmeetable on the Expo pod.

### Usage

```
./scripts/td85_session_hygiene_precheck.sh \
  || { echo "material drift — stash before committing"; exit 1; }
```

The script is executable + idempotent + fast (~30 ms on preview). No DB touch, no network calls.

### Validation

Running the precheck on the pod with only the TD-85 ship pending:

```
[td85-precheck] raw status rows:      1904
[td85-precheck] material-drift rows:  1

[td85-precheck] MATERIAL DRIFT present — review before committing:
  scripts/td85_session_hygiene_precheck.sh
```

Correctly surfaces the single agent-authored change (this script itself) while ignoring the 1,903 noise rows. After this commit lands, the precheck is expected to return `material-drift rows: 0` with no `MATERIAL DRIFT present` warning.

## Status

**TD-85 CLOSED.** Script shipped, policy doc shipped, TECH_DEBT.md entry updated to point at this doc.
