# Feature: AI Write Button on Tech Check-In Composer (Mobile)

## Summary
Added a ✨ AI Write button to the Check-In composer note section. Uses Pattern A (preferred): creates a draft check-in on first AI Write press, calls `POST /api/checkins/{id}/ai-description`, prefills note, and reuses the draft on final Submit.

## Pattern Choice: A (Draft-on-demand)
**Rationale**: Pattern A avoids the UX friction of Pattern B (requiring the user to manually fill everything before seeing AI Write). With Pattern A:
1. User adds GPS + ≥1 photo (required for draft creation)
2. Taps AI Write → draft created + AI endpoint called → note prefilled
3. User reviews, optionally edits, then taps Submit → reuses draft id + calls `/submit-public`

**Tradeoff**: One extra API round-trip (draft create) before the AI call, but this is transparent to the user and only happens once.

## Files Touched

| File | Changes |
|------|---------|
| `app/job/[id]/checkin.tsx` | Added `draftCheckinId`, `aiState`, `preAiValue` state; `ensureDraft()` helper; `handleAiWrite()` handler; modified `handleSubmit()` to reuse draft; added AI Write button in note section header; added AI button styles |
| `__tests__/ai-write-checkin-mobile.test.ts` | **NEW** — 26 test cases |

## TestID Map

| Element | testID | State |
|---------|--------|-------|
| AI Write / Undo AI button | `checkin-ai-write-btn` | `accessibilityState.selected = true` when in undo mode |
| Button icon (sparkle/spinner/undo) | `checkin-ai-write-btn-icon` | Changes based on aiState |

## Two-State Button Behavior

| State | Icon | Label | Action |
|-------|------|-------|--------|
| `write` | ✨ sparkle emoji | "AI Write" | Creates draft (if needed) → calls AI endpoint → prefills note |
| `busy` | ActivityIndicator spinner | "AI Write" | Button disabled during request |
| `undo` | arrow-undo Ionicon | "Undo AI" | Restores `preAiValue` → resets to write state |

## API Contract

### AI Description Endpoint
```
POST /api/checkins/{checkin_id}/ai-description
Body: {} (empty — backend defaults to tone: neutral_factual)
Success 200: { description: string, model: string, generated_at: string }
429: { detail: { code: "rate_limit_exceeded", retry_after_seconds: number } }
500: { detail: string }
```

### Error Handling
| Error | Toast copy |
|-------|-----------|
| 429 rate limit | "AI Write rate limit reached. Try again in {N} minutes." where N = ceil(retry_after_seconds/60), default 60 |
| 500 / network error | "AI Write failed. Please write manually." |
| Empty description | "AI Write failed. Please write manually." |

### Draft Lifecycle
1. `ensureDraft()` checks if `draftCheckinId` exists; if so, returns it
2. If not, validates GPS + ≥1 uploaded photo, then `POST /api/checkins` to create draft
3. Stores `draftCheckinId` for reuse
4. `handleSubmit()` checks `draftCheckinId`:
   - If exists: `PATCH /api/checkins/{id}` with final note/photos/GPS, then `POST /checkins/{id}/submit-public`
   - If not: `POST /api/checkins` (create fresh), then `POST /checkins/{id}/submit-public`

## Coupling with Backend
- Backend contract per `/app/memory/FEATURE_AI_CHECKIN_DESCRIPTION.md`
- `POST /api/checkins/{id}/ai-description` requires the check-in to exist first (hence Pattern A)
- Backend returns `{ description, model, generated_at }` on success
- Backend returns 429 with `retry_after_seconds` on rate limit
