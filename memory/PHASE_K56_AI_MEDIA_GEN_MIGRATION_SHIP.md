# Phase K56 · AI Media-Gen Migration — Ship Report

**Date:** Feb 2026
**Status:** ✅ Shipped to preview · pending main-agent tester dispatch
**Blocker resolved:** P0 · Emergent image gen returned HTTP 502
`emergent_call_failed` (invalid model `nano-banana-2`) after K55.b
promoted `EmergentFallbackProvider` to the sole provider.

---

## Emergent image-gen model discovery — receipts

Discovery was completed in this order per the ship instruction:

1. **integration_playbook_expert_v2** → returned
   `GEMINI_IMAGE_GENERATION_PLAYBOOK`, which enumerates the accepted
   image-gen model ids for `LlmChat.with_model("gemini", …)`:
   - `gemini-3.1-flash-image-preview` (default · Nano Banana)
   - `gemini-3-pro-image-preview` (higher quality)
2. **Live probe** — a python one-shot from inside the backend pod
   (using the seeded `EMERGENT_LLM_KEY`) confirmed
   `("gemini", "gemini-3.1-flash-image-preview")` returns a real
   base64 JPEG (~71 KB) via
   `chat.send_message_multimodal_response(msg)`. `("google", …)`
   was rejected outright — the pre-K56 wiring was doubly wrong
   (bad provider **and** bad model id).

Chosen default: **`gemini-3.1-flash-image-preview`**. Env-overridable
via `EMERGENT_IMAGE_MODEL` so ops can flip on rename/deprecation
without a code deploy.

---

## Code changes

### Backend

- `backend/services/media_provider.py`
  - New module constants: `EMERGENT_IMAGE_PROVIDER = "gemini"`,
    `EMERGENT_IMAGE_MODEL_DEFAULT = "gemini-3.1-flash-image-preview"`,
    plus `_emergent_image_model()` helper that reads
    `EMERGENT_IMAGE_MODEL` at call time (hot-reload friendly, matches
    the pattern in `_daily_limit`).
  - `EmergentFallbackProvider.generate` rewritten to
    - use `.with_model("gemini", <model>)` instead of
      `.with_model("google", "nano-banana-2")`
    - call `.with_params(modalities=["image", "text"])` (was missing)
    - pull the response via `send_message_multimodal_response` and
      transcode each returned image dict (`mime_type` + base64 `data`)
      into a `data:<mime>;base64,<b64>` URI so the persist layer
      contract (`image_urls: List[str]`) is unchanged.
    - fall back to the old text-scan path only when the images list
      is empty (safety net for any future model that returns URIs
      inline).
    - `tool_used` now reports the actual model id, so historical
      library rows record which model produced them.
  - Reference-image path still works: fetch → base64 → `ImageContent`.

- `backend/routers/media_gen.py`
  - Env-var rename with **dual-read fallback**:
    canonical `AI_MEDIA_DAILY_IMAGE_LIMIT` wins → legacy
    `SUPERCOOL_DAILY_IMAGE_LIMIT` honoured (one release cycle) →
    default 100.
  - Emits a one-shot `WARN` at first legacy-read:
    `[k56] SUPERCOOL_DAILY_IMAGE_LIMIT is deprecated; migrate to AI_MEDIA_DAILY_IMAGE_LIMIT`.
  - Docstring updated to mark `/search` and `/remove-background` as
    "Emergent provider does not support" (Emergent provider still
    raises `ProviderError` on these — matches the K55.b behaviour;
    router untouched).

- `backend/.env` — added `EMERGENT_IMAGE_MODEL` and
  `AI_MEDIA_DAILY_IMAGE_LIMIT` (legacy line preserved intact).
- `backend/.env.example` — replaced the duplicated legacy block
  with a documented canonical + legacy block including the K56
  hardcut deprecation note. `EMERGENT_IMAGE_MODEL` documented with
  the validated model ids.

### Frontend

- **New** `frontend/src/config/featureFlags.js` — first feature-flag
  registry in the web codebase (grep confirmed no prior pattern).
  Exposes `FEATURE_FLAGS` (frozen) + `isFeatureEnabled(name)` helper.
  Wires two K56.1-forward flags **both defaulting `false`**:
  - `FEATURE_STOCK_SEARCH`  → gates any future `/media/image/search` UI
  - `FEATURE_REMOVE_BG`     → gates any future `/media/image/remove-background` UI
  K56.1 just flips the flags on and wires the Unsplash + remove.bg
  backends — no UI reship needed.
- `frontend/src/pages/marketing/ContentStudioPage.jsx` — inline
  comments updated from "nano-banana-2 fallback" to the actual
  `gemini-3.1-flash-image-preview` provider name. No UI removal
  needed (Content Studio has never rendered stock-search / remove-bg
  CTAs — verified by grep). Mobile parity (`mobile/app/marketing/
  content-studio.tsx`) also verified clean.

### Tests

- `backend/tests/test_k56_media_provider.py` — **9 tests, all pass**
  1. `generate()` calls `with_model("gemini", <default>)` +
     `with_params(modalities=["image","text"])` and returns a
     `data:image/png;base64,…` URI from the images list.
  2. `EMERGENT_IMAGE_MODEL` env override wins over the default.
  3. Empty images list + no data URI in text → `ProviderError`
     `emergent_no_image_in_response`.
  4. Missing `EMERGENT_LLM_KEY` → `ProviderError`
     `emergent_key_missing` (no proxy call attempted).
  5. `search()` → `ProviderError` (unsupported).
  6. `remove_background()` → `ProviderError` (unsupported).
  7. `_daily_limit` → canonical env wins over legacy.
  8. `_daily_limit` → legacy env still honoured when canonical unset.
  9. `_daily_limit` → default 100 when both unset.

- `frontend/src/test/phase-k56-feature-flags.test.js` — **4 tests,
  all pass**
  - Both flags default OFF.
  - Unknown flag returns `false`.
  - `FEATURE_FLAGS` object is frozen (guards runtime mutation).

- Adjacent regression pass: `tests/test_soshie_ai_image_gen.py`
  (7 tests) — all still green.

### End-to-end curl smoke

```
POST https://<preview>/api/media/image/generate
Authorization: Bearer <super_admin JWT>
Content-Type: application/json
{ "prompt": "A pristine backyard swimming pool at sunset with palm trees",
  "aspect_ratio": "1:1", "surface": "marketing" }

→ HTTP 200
   provider  = emergent_fallback
   tool_used = gemini-3.1-flash-image-preview
   image_id  = 343916b5995149049bc625b89592e6ae
   url       = /api/objects/poolcrm/global/generated/media/…jpg
   quota     = { used: 1, limit: 100 }
GET  /api/objects/…  →  HTTP 200 · 965,635 bytes · image/jpeg
```

The pre-K56 baseline was HTTP 502 `emergent_call_failed`.

---

## Deferred (explicitly out of K56 scope)

- **K56.1** — wire Unsplash Free + remove.bg backends and flip
  `FEATURE_STOCK_SEARCH` / `FEATURE_REMOVE_BG` on.
- **K56.2** — Sora 2 video-gen integration.
- **K56.hardcut** — remove the `SUPERCOOL_DAILY_IMAGE_LIMIT`
  dual-read fallback + startup WARN after one release cycle.
- **K55.c** — env cleanup + docs deprecation (was blocked on K56;
  now unblocked).
