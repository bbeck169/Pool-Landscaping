# Phase K59.a — Mobile Upload Error Stringifier

**Ship date:** Feb 2026
**Scope:** Client-side cosmetic hotfix for the `[object Object]` red
banner on the mobile Job Checklist → Visit Media section.
**Status:** 🟢 SHIPPED — K59.a only (client-side stringifier + testid
rename).

---

## Field report (context)

Users on the mobile Job Checklist → Visit Media section saw a red
error banner rendering the literal string `[object Object]` with a
dismiss × on the right.  Diagnosis (K59 7-point report) traced the
bug to `mobile/src/api/serviceReportMedia.ts:101` (pre-K59.a):

```typescript
try { msg = JSON.parse(xhr.responseText).detail || msg; }
```

FastAPI + Pydantic-v2 emit `response.detail` in **three** shapes:

1. **String** — explicit `HTTPException(400, "…")` sites.  Works.
2. **`list[dict]`** — Pydantic auto-generated 422 validation errors,
   each item shaped as `{type, loc, msg, input, url}`.  Feeding this
   array to `new Error(x)` yielded `Error.message = "[object Object]"`
   → rendered verbatim in `<Text>{err}</Text>`.  **This was the bug.**
3. **`dict`** — business-rule raises like
   `HTTPException(422, {"detail": ..., "message": ..., "missing_labels": [...]})`
   used elsewhere in the codebase.  Also yielded `[object Object]`
   if fed through the same path.

## What changed

### 1. New pure helper — `mobile/src/api/serviceReportMediaErrors.ts`

`stringifyDetail(detail: unknown): string` — flattens all three
FastAPI shapes into a readable string:

* **String** input → returned as-is (capped at 400 chars).
* **Array** input → each item mapped to `"loc.path: msg"` (or
  `JSON.stringify(item)` when no `msg` present), items joined with
  `"; "`.
* **Object** input → prefers `.message` > `.msg` > `.detail` >
  `.error`.  If a `missing_labels` / `missing_fields` array is also
  present, appended as `"…: label1, label2, …"`.  Falls back to
  `JSON.stringify(detail)` if no known key.
* **Primitive / null / undefined** → `String(x ?? "")` with the
  empty-string fallback.

All paths capped at 400 chars so a pathological Pydantic dump can't
wreck the fixed-height banner layout.

**Regression contract**: no input path may ever produce the literal
`"[object Object]"` substring in its return value.

Extracted to a sibling module (not inline in `serviceReportMedia.ts`)
so it can be unit-tested without loading the wider `@/src/api` chain
(which pulls AsyncStorage + SecureStore and is not Jest-friendly in
isolation).

### 2. Consumer wired — `mobile/src/api/serviceReportMedia.ts:110-125`

Replaced the pre-K59.a line 101 fallthrough with:

```typescript
try {
  const parsed = JSON.parse(xhr.responseText);
  const flat = _stringifyDetail(parsed?.detail);
  if (flat) msg = flat;
} catch { /* non-JSON body — keep the generic status-code msg */ }
```

`stringifyDetail` also re-exported from `serviceReportMedia.ts` for
backward-compat with any consumer that expects it on this module.

### 3. Testid rename — `mobile/src/components/checklist/ServiceReportMediaUploader.tsx:247-254`

The banner's testid was `svc-report-video-duration-error` — dated
back to when this box only surfaced the client-side "video too long"
message, but it now doubles as the generic upload error surface.
Renamed to `svc-report-upload-error`.  Legacy testid retained via
`accessibilityLabel="svc-report-video-duration-error"` so tests
still gate-checking on the old id keep working (RN Testing Library
resolves both via query selectors).

### 4. Tests — `mobile/__tests__/k59a-stringifyDetail.test.ts`

15 Jest cases:

* String pass-through + 400-char clip.
* Pydantic-v2 array shape → `"body.file: Field required"`.
* Multi-error array → joined with `"; "`.
* Array with no `msg` → falls back to `JSON.stringify` (never
  `[object Object]`).
* Dict shape → `.message` extraction + `missing_labels` append.
* Dict key priority: `.message` > `.msg` > `.error` > `.detail`.
* Dict with no known key → `JSON.stringify` fallback (never
  `[object Object]`).
* Null / undefined → empty string.
* Numbers / booleans → `String()` form.
* **REGRESSION guard** — explicit check that a Pydantic-v2 422
  payload never yields `"[object Object]"`.

## Revert safety

Two-line revert: restore the original `try { msg = JSON.parse(...).detail || msg; } catch { /* ignore */ }`
line, revert the testid string, and delete
`mobile/src/api/serviceReportMediaErrors.ts`.  No downstream code
depends on `stringifyDetail` beyond the internal call site + the
test suite.

## Deferred / follow-ups (out of scope for K59.a)

* **K59.b (P1)** — Real underlying 422 investigation.  Once K59.a
  lands and the banner shows the actual error, we'll have real
  reproduction data.  Most likely candidates from the K59 diagnosis:
  Expo `ImagePicker` handing back a URI whose stream is unreadable
  (Android permission-scoped URIs), or a mismatched multipart
  content-type on RN's `FormData`.  Not shipped blind — needs one
  round of production data with K59.a in place.
* **K59.c (P2)** — Permission-denial affordance.  Wire
  `Linking.openSettings()` into the "Permission needed" alert.
  Deferrable — users hitting the `[object Object]` bug are past the
  picker permission gate.

## No backend touch

Backend endpoints (`POST /api/service-reports/{id}/media`) return
correctly-shaped responses.  The bug was entirely in the client's
error-surface path.  Server behaviour unchanged.
