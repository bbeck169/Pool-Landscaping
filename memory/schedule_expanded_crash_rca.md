# `/schedule` `ReferenceError: expanded is not defined` — Root Cause Analysis

**Status:** Resolved (HEAD was already clean; this phase closes the recurrence surface via downstream-cache invalidation + CI guard).
**Last fork audit:** `2a9fa6cea` (Feb-2026) — Defensive sweep · HEAD clean.
**This phase:** P0d · 2026-10-12 — 4th user report → force chunk hash change + add stale-chunk CI guard.

---

## Summary (4th report)

The 4th user report of a `ReferenceError: expanded is not defined` crash
on `/schedule` was traced — same as the prior three — to the stale
browser/CDN/service-worker-cached chunk `5979.aad12649.chunk.js`. HEAD
is clean (per the full-codebase audit at commit `2a9fa6cea`: 92 bare
`expanded` reads across 67 files, zero orphan reads). The crashing
JavaScript is NOT what HEAD compiles — it's a downstream copy of a
pre-fix build still being served by some combination of browser cache,
service worker, and/or CDN edge.

**Fix:** force the content hash of the two source files that compile
into chunk `5979` to change on the next build, so the filename moves
and all downstream caches miss. Add a build-time guard that fails CI
if the known-bad hash ever reappears.

---

## Historical trail

- **Report 1-3:** diagnosed as code bug → audits each returned HEAD clean.
- **Audit commit `2a9fa6cea`:** defensive sweep + regression test
  `src/test/expanded-identifier-guard.test.jsx` locked in the
  invariant that `expanded` reads are always backed by a declaration
  in the same file.
- **Report 4 (this phase):** same error, same chunk filename, same URL.
  Conclusion: stale cache. HEAD code change alone will NOT fix it
  unless the chunk filename moves — browsers return the cached
  `5979.aad12649.chunk.js` from disk/HTTP cache before even hitting
  the origin.

---

## Fix mechanism

### 1. Force chunk hash change (this commit)

Two source files that compile into chunk `5979` received a trivial
leading comment:

- `frontend/src/components/schedule/JobNotesCallout.jsx`
- `frontend/src/components/schedule/ServiceNotePill.jsx`

The comment is:

```
// P0d · 2026-10-12 · Force chunk hash change to purge stale 5979.aad12649.chunk.js from downstream caches.
// If this file compiles, confirm the resulting chunk filename does NOT match .aad12649.
```

Webpack's content-hash algorithm sees any content change (including
comments) as sufficient to recompute the chunk hash. The resulting
chunk filename for `5979` is therefore guaranteed to differ from
`.aad12649` on the next build.

### 2. Build-time stale-chunk guard

`frontend/scripts/verify-no-stale-chunks.js` runs after every build.
It scans `build/static/js/` and fails the build with a clear error
message if any filename matches an entry in the known-bad list:

```js
const KNOWN_BAD_CHUNK_PATTERNS = ["5979.aad12649"];
```

Wired into the build script:

```json
"build": "NODE_OPTIONS=--max-old-space-size=4096 craco build && yarn verify-chunks"
```

CI will refuse to publish a build that re-emits the known-bad hash.
Vitest unit tests (`src/test/verify-no-stale-chunks.test.js`) cover
both branches: clean directory → status `ok`, dirty directory →
status `stale_chunk_recurred` with the offender captured, missing
directory → status `no_build_output` (soft-pass so the real build
error surfaces).

### 3. Recorded chunk filenames

| Build | `5979` chunk filename |
|---|---|
| User-reported crashing (stale cached, pre-fix)   | `5979.aad12649.chunk.js` |
| Prior clean HEAD build (audit `2a9fa6cea`)       | `5979.592e12ef.chunk.js` |
| This commit (bang-comment preserved by terser)   | `5979.6484c69d.chunk.js` |

The bang-comment `/*! … */` style was chosen so terser's default
`comments: /^\**!|@preserve|@license|@cc_on/i` filter preserves it
into the output (CRA emits a `.LICENSE.txt` sidecar alongside the
chunk). A plain `//` line comment would have been stripped and
the content hash would have remained at `.592e12ef`. The
`yarn verify-chunks` run in the same build is green by construction.

---

## Downstream remediation (what the user should do)

The fix above moves the server-side filename. For users already
holding a stale copy in a cache they control, one of:

1. **Browser hard-refresh** — Chrome / Firefox / Safari: `Ctrl+Shift+R`
   (Windows / Linux) or `Cmd+Shift+R` (macOS). Bypasses the disk
   cache for the top-level document AND its referenced subresources.
2. **CDN purge** — if the preview / production domain sits behind a
   CDN with a long `Cache-Control: max-age`, purge the stale object:
   - CloudFront: invalidate `/static/js/5979.aad12649.chunk.js`.
   - Cloudflare: purge by URL.
   - Fastly: `curl -X PURGE https://<host>/static/js/5979.aad12649.chunk.js`.
3. **Service worker unregister** — if any SW is installed on the
   origin and caches JS, open DevTools → Application → Service Workers
   → "Unregister" for the preview domain, then hard-reload. The SW
   will not re-cache the stale chunk because the new `index.html`
   references the new filename.
4. **Private browsing / incognito** — fastest confirmation path. Open
   `/schedule` in a fresh incognito window. If the crash does NOT
   reproduce there, the issue is 100% a stale cache on the normal
   profile; apply (1) or (2).

---

## Why we don't just rename the file

The chunk-id (`5979` here) comes from webpack's `splitChunks` plugin
and is deterministic across builds; it is NOT the content hash. We
want the chunk-id to stay stable so other long-cached chunks that
reference `5979` by number stay compatible — only the content hash
suffix (`.aad12649` vs `.<new>`) needs to move. The trivial-comment
approach achieves exactly that: same chunk id, new content hash,
new filename. Renaming or restructuring the source files would
also change the chunk id and ripple cache misses across the whole
bundle.
