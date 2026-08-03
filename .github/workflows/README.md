# CI workflows

## `ci.yml` — Phase 32 (Feb 2026)

Runs three jobs in parallel on every pull request and every push to `main`:

| Job            | What it runs                                                                                          | Local equivalent                                                             |
| -------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `backend`      | `pytest -c backend/pytest.ini -m "not live and not destructive and not legacy_iteration"` on Python 3.11 | `cd backend && pytest -m "not live and not destructive and not legacy_iteration"` |
| `frontend-web` | `yarn vitest run --reporter=basic` on Node 20.19                                                      | `cd frontend && yarn vitest run --reporter=basic`                            |
| `mobile`       | `yarn test --ci --forceExit` (jest-expo preset) on Node 20.19                                         | `cd mobile && yarn test --ci --forceExit`                                    |

### Design notes

- **Test-gating only.** No deploy / publish / EAS Build step — enforced by `frontend/src/test/phase32-ci-config.test.jsx`.
- **Concurrency**: `ci-${{ github.ref }}` with `cancel-in-progress: true` — superseded runs on the same branch/PR get cancelled.
- **Fail independent**: jobs don't cancel each other; each reports its own status.
- **Caching**: `~/.cache/pip` for backend; `yarn` cache (via `actions/setup-node@v4`) for both Node jobs. Keeps typical runs under ~5 min.
- **Legacy markers** (`live`, `destructive`, `legacy_iteration`) are all excluded — those are opt-in only, as declared in `backend/pytest.ini`.
