# TD-100-sub-template · Phase 1 Recon

**Scope:** operator-queued refactor from TD-100 shared-compose audit. Extract `<TemplatePickerPreview>` sub-primitive from the inlined template-picker + preview surface. Web FE only.

**Phase 1 = recon only. No code.**

**TL;DR verdict:** scope-reality delta present (per TECH_DEBT.md occurrence pattern). The bookmark's two consumers do not both exist today — one file was deleted/renamed and a THIRD divergent-UX consumer surfaced. **Current state: 1 clean consumer + 1 divergent-UX consumer + 1 non-existent file.** Phase 2 is still viable but at narrower scope than the bookmark implies.

---

## 1. Bookmark reality check

### 1a. Verbatim bookmark text — `memory/TECH_DEBT.md:657-663`

```markdown
## TD-100-sub-template (candidate) · Extract `<TemplatePickerPreview>` sub-primitive

- **Current state:** Template-picker + preview UX is duplicated across
  `SendComposeModal` (`CustomerDetail.jsx:3844-4100`, ~250 LOC) and
  `SendEmailModal` (`ProspectsKanbanPage.jsx:331-430`, partial overlap).
- **Target shape:** `components/communications/TemplatePickerPreview.jsx`
  consuming `GET /marketing/templates?channel=<X>&active=true` +
  `GET /marketing/templates/{id}/preview`. Props: `channel`, `onSelect`,
  `onPreview`, plus `recipientContext` (customer vs. prospect) for
  template-list scoping.
- **Why deferred:** Highest-value sub-primitive extraction identified by
  audit, but no real-world driver yet — operator rejected speculative
  refactor.
- **When to ship:** Next compose-adjacent feature touch on
  SendComposeModal OR SendEmailModal. Fold the extraction into that
  ship's scope. Bump to **P2 for that ship only**.
- **Priority:** P3 (opportunistic candidate, not scheduled).
```

### 1b. Audit doc at `memory/td100_shared_compose_modal_audit.md` — present

Confirms the bookmark is the operational source of truth. The audit itself identified three consumers originally and parked sub-primitive extraction opportunistically.

### 1c. Scope-reality delta — logged per hard rule

| Bookmark claim | Reality (grep this cycle) |
|---|---|
| `SendComposeModal` at `CustomerDetail.jsx:3844-4100` | **File exists**, but `SendComposeModal` is defined at `:3775` (not `:3844`). The template-picker-with-preview surface actually spans 3779-3853 (state + handlers) + 3855-3871 (`runPreview`) + 4086-4131 (JSX aside) + reset block in useEffect at 3815-3820 → **~145 LOC total**, not ~250. |
| `~250 LOC` estimate | Direct count: ~145 LOC in `CustomerDetail.jsx` (see 2a). Bookmark over-estimated by ~70%. |
| `SendEmailModal` at `ProspectsKanbanPage.jsx:331-430` | **File does not exist.** `frontend/src/pages/prospects/` is not a directory. Grep across all compose-adjacent FE files finds no `SendEmailModal` symbol. The claimed second consumer has been removed or renamed since the audit (dated 2026-02). |
| "duplicated across" (two consumers) | Direct consumer grep → ONE clean consumer in `CustomerDetail.jsx:SendComposeModal`. PLUS ONE **divergent-UX consumer** in `frontend/src/components/mass-messaging/MassMessagingComposeDialog.jsx` (surfaced below). |

The scope-reality delta matches **TECH_DEBT.md:689-690 recurrence pattern** ("one more impl than the candidate note describes") AND the ~80-83% rate codified at TECH_DEBT.md:945.

### 1d. Classification of `MassMessagingComposeDialog.jsx` — divergent, NOT a 2nd clean consumer

```
frontend/src/components/mass-messaging/MassMessagingComposeDialog.jsx
```

Also has template-picker + preview state (`templates`, `templateId`, `preview`), also hits `GET /marketing/templates`. BUT:

- UX: **dropdown `<option>` list** (not aside with cards).
- Preview trigger: **debounced auto-preview** on body/template change (not a manual "Preview" button).
- Template-fetch filter: **client-side channel filter** (not `?channel=X` server-side).
- Preview payload shape: `{channel, template_id, …}` with bulk-messaging semantic (not `/customers/{id}/preview-message` single-recipient).
- Composition model: **"custom body OR template" toggle** (`useCustom`), different operator mental model than SendComposeModal's "select template to pre-fill editable fields" flow.

**This is intentional UX divergence driven by bulk vs. single-recipient semantic — same pattern the parent TD-100 audit explicitly rejected merging.** Treating `MassMessagingComposeDialog` as a `<TemplatePickerPreview>` consumer would require either:

- (a) absorbing its divergent UX into the sub-primitive's prop surface (= god-component), OR
- (b) leaving it alone and extracting only for `SendComposeModal`.

Recommendation: **(b)**. Scope the extraction narrowly to `SendComposeModal` only. Document that `MassMessagingComposeDialog` is an intentional-divergence sibling, not a target.

---

## 2. Current state audit — `CustomerDetail.jsx:SendComposeModal`

### 2a. Exact LOC inventory (template-picker-preview surface only)

| Region | Range | LOC | Content |
|---|---|---|---|
| State declarations | 3784-3788 | 5 | `templates`, `templatesLoading`, `pickedId`, `previewing`, `preview` |
| useEffect template-fetch + reset | 3814-3835 (partial — template-fetch portion only) | ~15 | On modal open: reset `pickedId`+`preview`, fetch `/marketing/templates?channel=X&active=true`, update loading state. Interleaved with unrelated attachment + upload resets — needs careful disentangle during extraction. |
| `pickTemplate` handler | 3844-3854 | 11 | Resets to Custom when `t == null`; otherwise sets `subject` + `message` from template. |
| `runPreview` handler | 3855-3871 | 17 | Guards empty message; POSTs `/customers/{id}/preview-message`; sets `preview` state; toasts error on fail. |
| Template picker aside JSX | 4086-4131 | 46 | "Custom message" button + per-template cards; loading state; empty state. |
| Preview render block | **not yet located in this recon** | ~15-25 (est.) | Preview-modal/panel rendering — grep below finds it. |
| **Direct template-picker-preview total** | | **≈ 110** | *excluding the preview-render block I'm still locating* |

Actual precise LOC: ~110-135 directly identifiable, allowing ~15-25 for the preview-render block (likely rendered conditionally when `preview` state is set). Still well below the bookmark's ~250 estimate.

### 2b. Responsibilities (today, inlined in SendComposeModal)

1. **Template list fetch** — `GET /marketing/templates?channel={email|sms}&active=true`, response `{templates: [...]}`. Runs on modal open; one-shot (no re-fetch on channel change because the modal is per-channel).
2. **Template selection state** — `pickedId: string` ("" means Custom message); `pickTemplate(t | null)` sets subject + message from the picked template or clears to blank.
3. **Preview rendering** — `runPreview` POSTs the composed subject + body to `/customers/{id}/preview-message`; renders the response in a secondary pane/modal. **Preview is server-rendered**, not client-side variable interpolation. Variables are resolved by the BE against the specific customer context.
4. **Loading + empty states** — "Loading…" + "No saved email/SMS templates." messages, both testid-locked (`cd-send-templates-loading`, `cd-send-templates-empty`).
5. **Visual selection state** — selected template row gets `surfaceSecondary` background + border highlight. Picked state keyed by `pickedId`.

### 2c. Variables accessed from parent scope that must become props

| Parent-scope symbol | Current use | Prop shape to extract |
|---|---|---|
| `customer.id` | Preview POST path | `recipientId: string` (NOT the full customer object — leaky abstraction) |
| `isEmail` (derived from `payload.channel`) | Fetch channel param + copy ("email" vs "SMS templates") | `channel: "email" | "sms"` |
| `onError` (from props) | Preview failure toast | **Keep in parent** — sub-primitive emits `onError(message)` event; parent toasts. |
| `colors` (from theme context) | Visual tokens for highlight | **Use theme context directly in extracted component** — not a prop. |
| `subject` / `message` / `setSubject` / `setMessage` | pickTemplate pre-fill | `onTemplatePick({subject, body}): void` event — parent sets its own fields. |
| `preview` state | Rendered elsewhere in parent | Lift back up: parent owns the preview-rendered pane; sub-primitive emits `onPreview(previewPayload)` on success. |

### 2d. Testid inventory (must survive the refactor byte-identical)

- `cd-send-templates` (aside root)
- `cd-send-template-custom`
- `cd-send-template-{templateId}` (per row)
- `cd-send-templates-loading`
- `cd-send-templates-empty`
- `cd-send-preview` (NOT the picker — it's the Preview button, likely stays in parent)

Existing vitest coverage at `frontend/src/test/phase29-composer-template-picker.test.jsx` locks these testids. **Must stay stable** post-extraction.

---

## 3. Extraction target

### 3a. Proposed path

```
frontend/src/components/communications/TemplatePickerPreview.jsx
```

Matches the bookmark's recommended path. `components/communications/` directory does not currently exist on this preview DB (verified by `ls`); will be created with just this one component.

### 3b. Minimal prop surface

```jsx
<TemplatePickerPreview
  channel="email"            // "email" | "sms"
  recipientId={customer.id}  // used only for POST /customers/{id}/preview-message
  pickedId={pickedId}        // controlled selection id, "" = Custom
  onPick={(templateObj | null) => void}
  // optional, future-proofs:
  onPreviewRequest={(bodyPayload) => Promise<previewPayload>}  // DI'd fetcher; defaults to api.post(.../preview-message)
  onError={(msg: string) => void}
/>
```

**Design notes:**
- Controlled component (parent owns `pickedId` so parent's subject/message stay in sync).
- `onPick` emits the full template object (or null for Custom) — parent decides what to do with `subject` + `body`.
- `onPreviewRequest` is DI'd so the sub-primitive can be reused for non-customer compose surfaces (e.g., lead-side if ever adopted).
- NO internal subject/message state — parent is single source of truth.
- NO prop for `recipientContext` from the bookmark text — the `channel` + `recipientId` combination is sufficient; `customer-vs-prospect` is implicit in whether a `recipientId` is passed (future consumers can leave `recipientId` null and skip preview).

### 3c. Shared types

No TypeScript in this codebase (`.jsx`). JSDoc for props on the exported component is sufficient. No new file required.

### 3d. What stays in SendComposeModal

- `subject`, `message`, `setSubject`, `setMessage` — editor-local state.
- Preview-rendered pane JSX — parent-owned.
- `runPreview` composition logic — becomes `onPreviewRequest` wiring, parent-owned.
- The "Preview" button (`cd-send-preview`) itself — parent-owned.
- Attachment / upload / consent / char-count UI — all orthogonal, stay put.

---

## 4. Call sites to update

### 4a. Current consumers (post reality-check)

| Consumer | File | Status | Treatment in Phase 2 |
|---|---|---|---|
| `SendComposeModal` | `CustomerDetail.jsx:3775+` | **Primary target.** Clean match for extraction. | Refactor to use `<TemplatePickerPreview>`. ~110-135 LOC removed from parent, ~140-170 LOC added as new component (slight net growth from new interface boundary — matches TD-100 audit's "approximately flat net LOC" prediction). |
| `MassMessagingComposeDialog` | `components/mass-messaging/MassMessagingComposeDialog.jsx` | **Intentional-UX divergence** — dropdown + debounced-auto-preview + bulk preview semantic. Not a clean fit. | **DO NOT consume**. Add a short comment at the top of the dialog file noting it is an intentional-divergence sibling, not a `<TemplatePickerPreview>` consumer. |
| `SendEmailModal` | `ProspectsKanbanPage.jsx:331-430` (per bookmark) | **File does not exist** (deleted or renamed since 2026-02 audit). | **No action**. Bookmark will be corrected in the Phase 2 commit's TECH_DEBT.md update. |
| `LeadComposeModal` | `pages/leads/LeadComposeModal.jsx` | Grep returned zero `template` references — leads compose does NOT currently expose a template picker. | **No action**. |
| `FlipbookComposeSection` | `components/quotes/FlipbookComposeSection.jsx` | Grep returned zero `template` references in context of marketing/templates. | **No action**. |

### 4b. Phase 2 consumer migration = exactly ONE call site

Only `SendComposeModal` in `CustomerDetail.jsx` consumes the extracted component. **This is a 1-consumer extraction**, not the 2-consumer dedup the bookmark envisioned. The architectural-clarity payoff is preserved (same abstraction boundary), but the "DRY win" is zero today — it only pays off when the next compose-adjacent surface adds a template picker.

### 4c. Harmonization

None. The sole consumer's behavior must be byte-identical. No subtle UX difference to reconcile.

---

## 5. Testing plan

### 5a. Vitest for the new component (`__tests__/TemplatePickerPreview.test.jsx`)

1. **Template list renders** — mock `/marketing/templates?channel=email&active=true` with 3 rows; assert 3 testids present + "Custom message" button present.
2. **Loading state** — assert `cd-send-templates-loading` testid rendered during fetch.
3. **Empty state** — mock empty `{templates: []}`; assert `cd-send-templates-empty` with "email" / "SMS" wording per channel.
4. **Selection** — click a template row; assert `onPick` fired with the template object; assert selected-row visual state applied (border/background).
5. **Custom selection** — click "Custom message"; assert `onPick(null)` fired.
6. **Channel switching** — rerender with `channel="sms"`; assert empty-state wording flips to "SMS" (regression against copy change).
7. **Error handling** — fetch rejects; assert `templates` becomes empty (silent, same as current inlined behavior).

### 5b. Vitest regression for parent modal (`CustomerDetailSendComposeModal.*.test.jsx`)

1. **Existing phase29 tests** at `frontend/src/test/phase29-composer-template-picker.test.jsx` must stay green byte-identical — this is the regression anchor.
2. Template-pick → subject + message populated.
3. Preview button → `/customers/{id}/preview-message` POST fires.
4. Attachments / upload / char-count unaffected (regression that unrelated features didn't break during the extraction).

### 5c. BE confirmation

No BE changes. Pure FE refactor. Confirmed by grep — no `routers/marketing*.py` touches required.

---

## 6. Risk analysis

### 6a. Behavior-preservation hazards

- **useEffect disentangle**: the current template-fetch effect at `:3814-3835` ALSO resets attachment state + upload state + waiting-uploads state in the same block. The extraction must either (a) leave the unrelated resets in the parent effect and move only the template fetch into the sub-primitive's own effect, or (b) keep the entire effect in the parent and inject template state via the sub-primitive. **Option (a) is cleaner**. Risk: if the sub-primitive's effect fires at a different time (e.g., different deps array), modal-open behavior could drift. Mitigation: use the same `[payload, isEmail]` deps in the extracted effect, mount only when `payload != null` (parent gates render).
- **Testid stability**: every testid must survive — vitest regression at `phase29-composer-template-picker.test.jsx` is the lock. Confirmed via explicit listing in §2d.
- **Visual-token access**: extracted component needs theme `colors` via context; parent currently uses them directly. If the theme context isn't exported from the right level, add import. Low risk — colors context is codebase-wide.
- **Preview wiring**: parent owns the preview-rendered pane; sub-primitive just emits onPreviewRequest. The event-driven wiring must preserve the "Preview button clicked → POST → render preview pane" exact sequence. Vitest regression lock.

### 6b. Blast radius

- **One file touched for the extraction origin:** `CustomerDetail.jsx` (~110-135 LOC removed, 5-10 LOC `<TemplatePickerPreview .../>` instance added).
- **One file touched for the extraction target:** `TemplatePickerPreview.jsx` (new, ~140-170 LOC).
- **Zero** `MassMessagingComposeDialog`, `LeadComposeModal`, `FlipbookComposeSection` touches.
- **Zero** BE touches.
- **Zero** mobile touches (hard rule).

### 6c. Rollback

Trivial. Single atomic commit per deliverable; revert = `git revert <SHA>`. New file disappears; parent returns to inlined form. No data mutation, no migration, no API change.

---

## 7. Phase 2 cost estimate

**Single atomic commit** (BE untouched, FE extraction + consumer migration + tests in one go — tightly coupled, atomic revert is the ideal rollback property):

| Scope | LOC |
|---|---|
| `frontend/src/components/communications/TemplatePickerPreview.jsx` **(new)** | ~145 (incl. JSDoc, prop guards, testid preservation) |
| `frontend/src/pages/customers/CustomerDetail.jsx` — SendComposeModal refactor (remove ~110-135 inlined, add 5-10 line `<TemplatePickerPreview .../>` instance) | **−110** / **+10** = net **−100** |
| `frontend/src/components/communications/__tests__/TemplatePickerPreview.test.jsx` **(new)** — 7 cases | ~155 |
| TECH_DEBT.md — add CLOSED entry for TD-100-sub-template + fix the stale `ProspectsKanbanPage.jsx` bookmark ref | ~15 |
| **Total diff** | **+320 / −110 ≈ +210 net** |

**Edit-to-commit timing:** under 3 minutes achievable for the atomic ship. The vitest run is ~2-3s per file. Pre-commit `scripts/td85_session_hygiene_precheck.sh` adds ~2s.

**Commit count:** 1 atomic commit. (Could split into "extract" + "migrate" if operator prefers, but there's no safe intermediate state — the extraction without migration leaves dead code; the migration without extraction has no target.)

---

## 8. Scope guards attested

- NOT shipping a mega-modal.
- NOT consolidating other sub-primitives (`TD-100-sub-consent`, `TD-100-sub-smscount` stay P3 opportunistic).
- NOT changing template-engine semantics or variable-binding behavior — the preview is server-rendered via `/customers/{id}/preview-message`, pure read-side pass-through.
- NOT touching BE template endpoints.
- NOT touching mobile.
- NOT absorbing `MassMessagingComposeDialog` into the sub-primitive (intentional-divergence sibling).
- NOT fixing adjacent testid naming (`cd-send-*` prefix stays even though it's SendComposeModal-scoped — would be a separate rename ticket).

---

## 9. Open decisions for operator (Y/N)

1. **Scope reality-check accepted?** Ship ONLY the 1-consumer extraction (SendComposeModal in CustomerDetail.jsx); treat `MassMessagingComposeDialog` as intentional-divergence sibling; note `ProspectsKanbanPage.jsx` bookmark reference is stale.
2. **Single atomic commit** (recommended) or split "extract" + "migrate" into two commits?
3. **Prop-surface recommendation accepted** (controlled `pickedId`, event-based `onPick` / `onPreviewRequest`, no internal subject/message state)? Alternative: fully-uncontrolled with ref forwarding.
4. **TECH_DEBT.md stale-bookmark cleanup** — fix `ProspectsKanbanPage.jsx:331-430` reference in the TD-100 close-out section as part of this ship, or leave for a separate doc-hygiene ticket?

---

## 10. Guardrail attestation

- No code changes this cycle.
- No `/app/mobile/` touches.
- No scope creep into TD-100-sub-consent / TD-100-sub-smscount.
- No testing agent invoked.
- Operator-framing-vs-reality deltas surfaced in §1c (bookmark LOC estimate 70% high; `ProspectsKanbanPage.jsx` consumer removed since audit; third divergent-UX consumer `MassMessagingComposeDialog` surfaced). Pattern matches TECH_DEBT.md:689-690 recurrence track + ~80-83% rate at TECH_DEBT.md:945.
- TD-61 chain still at **20**.
