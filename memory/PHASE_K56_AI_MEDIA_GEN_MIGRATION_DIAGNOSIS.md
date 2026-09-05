# Phase K56 · Feb-2026 — AI Employees media-gen migration to Emergent DIAGNOSIS

**Status**: Diagnosis only. No code changes. Awaiting user green light on
migration plan.

**⚠ CRITICAL FINDING UP FRONT**:

1. **The AI Employees feature does NOT itself generate images or videos.**
   Personas (Casey, Emmie, Buddy, Vizzy, Dexter, Soshie, Scouty, Commet,
   Skedra, Billy) carry STATIC seeded ``avatar_url`` values pointing to
   ``/avatars/personas/{key}.jpg`` — files shipped under
   ``frontend/public/avatars/personas/``.  See
   ``backend/routers/ai_employees.py:47-125`` (persona table) and
   ``backend/services/migrations/persona_avatar_backfill.py`` (idempotent
   backfill of those URLs).  There is no per-persona image gen.

2. **Image generation IS wired to Emergent already** — via
   ``EmergentFallbackProvider`` in ``backend/services/media_provider.py``
   (line 256).  It uses ``LlmChat(...).with_model("google", "nano-banana-2")``
   through the Emergent Universal LLM Key.  Currently it's the FALLBACK;
   SuperCool is the primary.

3. **There is no video generation anywhere in the codebase today.**  Grep
   for ``generate_video`` / ``sora`` / ``runway`` / ``pika`` / ``luma`` /
   ``text_to_video`` returns zero hits.  If the user wants AI-generated
   video, that's net-new work — not a migration.

The 5-item report per user brief follows.

---

## 1 · AI Employees feature — files that touch image or video generation

| File | Uses image gen? | Uses video gen? | Notes |
|---|---|---|---|
| ``backend/routers/ai_employees.py`` | ❌ (static ``avatar_url``) | ❌ | Persona CRUD only.  No media gen. |
| ``backend/services/ai_employee_tools.py`` | ❌ | ❌ | Tool router — no media |
| ``backend/services/migrations/persona_avatar_backfill.py`` | ❌ (writes static URL strings) | ❌ | Idempotent backfill |
| ``backend/migrations/task_p24_backfill_ai_employee_avatars.py`` | ❌ | ❌ | Same, older path |
| ``backend/migrations/task_jj_dedupe_ai_employees.py`` | ❌ | ❌ | Dedupe utility |
| ``frontend/src/pages/aiEmployees/*`` | N/A (path doesn't exist as ai-employees dir) | N/A | AI Employees UI lives elsewhere — see `App.js` |
| Persona avatar images: ``frontend/public/avatars/personas/{casey,emmie,buddy,vizzy,dexter,soshie,scouty,commet,skedra,billy}.jpg`` | STATIC ASSETS | N/A | 10 files, shipped in repo |

**Consumers of image generation that touch AI Employees adjacently:**

| File | Role |
|---|---|
| ``backend/services/soshie/ai_image_gen.py`` | Soshie is one of the 10 seeded AI Employees.  Her AUTONOMOUS marketing-post feature uses ``pick_provider(tenant_id).generate(...)`` to produce a brand image per post. |
| ``backend/routers/media_gen.py`` | ``/api/media/image/generate``, ``/edit``, ``/search``, ``/remove-background`` — Content Studio's image workflow.  Used by the marketing UI regardless of which AI Employee kicks it off. |

## 2 · Current providers

### Image generation
The adapter pattern is already there:

| Provider class | File:Line | Model | Env vars | Live/mocked | Storage |
|---|---|---|---|---|---|
| ``SupercoolProvider`` (primary) | ``services/media_provider.py:173`` | SuperCool MCP (``image_generate`` / ``image_search`` / ``remove_image_background`` tools) | ``SUPERCOOL_MCP_URL`` | Live for tenants with an MCP-OAuth connection (per-tenant, checked at ``services/media_provider.py:161 _tenant_supercool_connected``) | ``/app/backend/uploads/generated/`` + ``db.generated_media`` |
| ``EmergentFallbackProvider`` (fallback) | ``services/media_provider.py:256`` | ``google/nano-banana-2`` via ``emergentintegrations.llm.chat.LlmChat`` | ``EMERGENT_LLM_KEY`` | Live (already using the Emergent Universal LLM Key) | Same |

Router: ``pick_provider(tenant_id)`` at ``services/media_provider.py:316`` — checks ``_tenant_supercool_connected``, returns SuperCool if connected else Emergent.

### Video generation
**NOT WIRED.**  No callers, no provider, no router.  Zero references
found in a full backend grep for ``generate_video`` / ``video_gen`` /
``text_to_video`` / ``sora`` / ``runway`` / ``pika`` / ``luma``.  This
means K56 has a **video scope decision** to make (see §5).

## 3 · Emergent equivalents available in this repo

### Image gen — YES, ALREADY WIRED

* **Model**: ``google/nano-banana-2`` via
  ``LlmChat(...).with_model("google", "nano-banana-2")``.
* **Env**: ``EMERGENT_LLM_KEY``.
* **Client**: ``emergentintegrations.llm.chat`` (already installed —
  see ``backend/requirements.txt`` for the package).
* **Aspect ratios / sizes**: nano-banana-2 supports arbitrary aspect
  ratios via prompt hinting (``instagram → 1024x1024``, ``tiktok →
  1024x1536``, ``facebook / gbp → 1536x1024`` per
  ``services/soshie/ai_image_gen.py`` header).  Not a strict parameter,
  passed as prompt context.
* **Quality tiers**: nano-banana-2 is a single-tier model.  No premium
  vs standard toggle.
* **Return shape**: nano-banana returns a data-URI or hosted URL in the
  text response.  ``EmergentFallbackProvider.generate()`` at
  ``services/media_provider.py:296-306`` parses both cases and yields
  ``{provider, tool_used, image_urls[], raw}``.

### Alternative image models via Emergent LLM Key

Per Emergent integrations docs, the Emergent Universal Key also supports:
- ``openai/gpt-image-1`` — larger, higher-quality but more expensive.
- ``google/nano-banana`` (v1) — older.

K56 recommendation: stay on ``nano-banana-2`` (current fallback impl),
add ``gpt-image-1`` as a per-tenant "premium quality" tier if user wants
it later.

### Video gen — NEEDS DECISION

Per Emergent integration docs, the Emergent Universal Key supports
**Sora 2 video generation**.  It is NOT currently used in the codebase.
Wiring Sora 2 = net-new module (not a migration) — new provider class,
new router endpoint, new frontend surface.

## 4 · Migration plan draft

### Adapter pattern (already exists — extend, don't rewrite)

The current adapter is at ``services/media_provider.py``:

```py
async def pick_provider(tenant_id: str) -> Provider:
    if await _tenant_supercool_connected(tenant_id):
        return SupercoolProvider()
    return EmergentFallbackProvider()
```

**Post-K55 (SuperCool removed) + K56**: simplify to a single-provider
return.  Optionally introduce the feature flag for rollback:

```py
async def pick_provider(tenant_id: str) -> Provider:
    provider = os.environ.get("AI_MEDIA_PROVIDER", "emergent").lower()
    if provider == "legacy":
        # kept for one release cycle so we can flip back fast if
        # Emergent output quality is lower than expected
        from services.media_provider_legacy import SupercoolProvider
        return SupercoolProvider()
    return EmergentFallbackProvider()
```

Only if user wants the feature flag; simplest path is delete-SuperCool
in K55 + let ``pick_provider`` return Emergent unconditionally in K56.

### Same public interface for callers

Both ``SupercoolProvider`` and ``EmergentFallbackProvider`` already
implement the same 3-method surface:
- ``generate(*, tenant_id, prompt, aspect_ratio=None, image_url=None, num_images=1)``
- ``search(*, tenant_id, query, source=None)``  ← Emergent errors ``no_search_support``
- ``remove_background(*, tenant_id, image_url)``  ← Emergent errors ``no_bg_removal_support``

**Gap on the Emergent fallback**: ``search`` and ``remove_background``
raise ``ProviderError``.  Router (``media_gen.py:215, 236``) will
surface those as 502s.

Options:
- **Option 4A (recommended)**: Wire ``search`` to a stock-image API
  (Unsplash Free tier for MVP, or Pexels API — both have free
  developer keys).  Non-Emergent add-on; keeps the endpoint usable.
- **Option 4B**: Hide the "Search Stock" button in the UI when no
  provider supports it (post-K55, Emergent is only provider → button
  hidden).  Least code, but UX regression for users who were using it.
- **Option 4C**: Wire ``remove_background`` to
  ``https://api.remove.bg`` (external, needs key) or a self-hosted
  ``rembg`` container.  Non-Emergent add-on.

Recommendation: ship K56 with Option 4B (hide unsupported affordances)
+ a follow-up K56.1 to add Unsplash search via a small standalone
integration.

### Env var deprecation

Remove after Prod redeploy of K55:
- ``SUPERCOOL_MCP_URL``
- ``SUPERCOOL_URL``

Rename (K55/K56 combined):
- ``SUPERCOOL_DAILY_IMAGE_LIMIT`` → ``AI_MEDIA_DAILY_IMAGE_LIMIT``
  (provider-agnostic).  Keep the old name as a fallback read for one
  release cycle.

New (optional feature flag):
- ``AI_MEDIA_PROVIDER=emergent|legacy`` (default ``emergent``).  If not
  shipped, ``pick_provider`` returns Emergent unconditionally.

### Storage preserve

Existing outputs live under ``/app/backend/uploads/generated/`` +
``db.generated_media``.  **Preserved as-is** — this is code migration,
not data purge, per the K55 principle.

### Prompt / parameter mapping

| Concept | SuperCool (deprecated) | Emergent nano-banana-2 |
|---|---|---|
| Prompt | ``prompt`` argument | Same |
| Aspect ratio | Explicit tool arg | Passed as prompt hint (``"...1024x1536..."``) |
| Reference image | ``image_url`` (URL only) | ``ImageContent(image_base64=...)`` — reference image is fetched, base64-encoded, and attached |
| Quality tier | Multiple SC tools | Single tier |
| Number of images | ``num_images`` | Always 1; caller loops if more needed |

``EmergentFallbackProvider.generate`` already handles the aspect-ratio
hint and reference-image download+b64 — no caller changes needed.

### Rollback safety

If shipped without the flag, rollback = revert commit.  With the flag,
rollback = flip Prod env ``AI_MEDIA_PROVIDER=legacy`` (requires
retaining the SuperCool provider code — contradicts K55 removal).

**Recommendation**: NO feature flag.  K55 removes SuperCool.  K56
simplifies ``pick_provider`` to Emergent-only.  If quality regresses,
we ship a K56 hotfix — the fix is small (nano-banana-2 → gpt-image-1
in the ``.with_model`` call) and no legacy code is retained.

## 5 · Video-specific scope decision (user's brief called this out)

**The codebase has NO video generation today.**  So there is nothing to
migrate for video.

Options for the user's brief:

- **Option 5A**: Ship K56 as IMAGE-ONLY migration.  Add a follow-up
  K56.2 to introduce AI-generated video via Sora 2 through the Emergent
  Universal Key as a NEW feature.  Cleanest scope split.
- **Option 5B**: Bundle K56.2 (Sora 2 wiring) into K56 — introduce a
  ``VideoProvider`` class, ``/api/media/video/generate`` endpoint, and
  a Content Studio surface.  Larger scope, higher risk.
- **Option 5C**: Explicitly disable ``/api/media/video/*`` — but the
  route doesn't exist, so this is a no-op.  Just document "video gen
  is not shipped yet" in the memory doc.

**Recommendation**: Option 5A.  K56 is image-only migration.  File
K56.2 as a separate future ticket for Sora 2 video gen when the user
wants it.

---

## Files inspected (not changed)

* ``backend/routers/ai_employees.py``
* ``backend/services/ai_employee_tools.py``
* ``backend/services/media_provider.py``  (adapter pattern)
* ``backend/services/soshie/ai_image_gen.py``
* ``backend/routers/media_gen.py``
* ``backend/routers/ai_ops.py``  (older AI-employee seed path; no media)
* ``backend/services/migrations/persona_avatar_backfill.py``
* ``backend/migrations/task_p24_backfill_ai_employee_avatars.py``
* ``frontend/public/avatars/personas/`` (10 static JPGs, shipped)

## Files NOT changed

None.  Diagnosis-only pass.
