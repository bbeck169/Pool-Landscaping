# Feb-2026 · K71 stable-id keys + duplicate-row guard

Retire the array-index React-key anti-pattern in
`components/quotes/K71LineItemsEditor.jsx` and add a defensive
de-dup filter so an optimistic add / delete / undo race can never
render two rows for the same underlying line item.

## Touched files

| File | Change | LOC delta |
| ---- | ------ | --------- |
| `frontend/src/components/quotes/K71LineItemsEditor.jsx` | New `_lineKey` / `_mintUid` / `_ensureUid` / `_normalize` helpers; every `setLocalItems` boundary funnels through `_normalize`; render keys on desktop `<tr>` + mobile `<MobileCard>` switched to `_lineKey(li)`; fresh Add-line drafts get a client-minted `_uid` at insertion time | +64 / −4 |
| `frontend/src/test/k71-line-items-stable-id-keys.test.jsx` (NEW) | 5 Vitest cases locking the stable-key + de-dup contract | +250 |

Parent state owner in `pages/quotes/QuoteInvoiceDetail.jsx` was
**not** touched — the existing `onLinesUpdated` handler PUTs the
full `next` array and calls `load()`, which is a full-replace
merge (never an append). K71 reconciles via its `[doc.line_items]`
effect that funnels through `_normalize`, so an optimistic entry
carrying a `_uid` gets replaced in-place by its server-`id`-tagged
counterpart on the next reload — no downstream merge changes
needed.

## Line-item schema audit

Backend Line Item shape carries a stable `id` (see
`backend/routers/quotes.py:684` — `existing_by_id = {li.get("id"):
li for li in existing_lines if li.get("id")}`). Frontend adopts the
same field. Fallback chain used by `_lineKey`:

```
li.id  ??  li._id  ??  li._uid  ??  li.uid  ??  null
```

* `id` — server-canonical (present on every persisted row).
* `_id` — Mongo-style alias emitted by some list endpoints.
* `_uid` — client-only, minted by `_mintUid()` on the fresh
  Add-line draft; retained through the save round-trip until the
  parent reload replaces the row with its `id`-tagged copy.
* `uid` — additional legacy alias, kept for safety.

`_mintUid()` prefers `crypto.randomUUID()` when available and
falls back to `_uid-<Date.now()>-<random-base36>` for the small
number of legacy jsdom/older-node harnesses that still lack the
Web Crypto API.

## De-dup filter contract

`_normalize(list)` is the single choke-point that guards every
state-boundary. It:

1. Skips falsy entries (defensive against a stray `null` in the
   incoming `line_items` array — the existing codebase already
   uses this shape in one downstream renderer).
2. Runs each row through `_ensureUid`, attaching a client-only
   `_uid` when no id is present.
3. Filters subsequent occurrences of the same stable id, so a
   race between an optimistic add and a server-confirmed reload
   NEVER produces two rows with the same `key=`. Rows without any
   id are kept (they aren't dedup-comparable), but `_ensureUid`
   makes that path unreachable in practice.

Every `setLocalItems` call in the file was updated to funnel
through `_normalize`:

* `useState(() => _normalize(doc.line_items || []))` — initial
  hydration.
* `useEffect([doc.line_items])` sync — parent reload merge.
* `saveLine` — optimistic edit commit.
* `cancelLine` — discard fresh-draft path.
* `handleAddLine` — new draft insertion (empty payload already
  carries a fresh `_uid` from `_mintUid()`).
* `handleDelete` — soft-remove.
* `handleUndo` — restore after 5s undo window.

## Optimistic add / delete / undo audit

Walked through the three flows to confirm the merge is
replace-in-place, not append:

* **Add-line**: `handleAddLine` appends an empty draft carrying a
  fresh `_uid`; `saveLine` swaps `next[idx] = updatedLine` (the
  spread inside `EditableRow.commit` preserves the `_uid`);
  parent `onLinesUpdated(next)` PUTs the whole array and calls
  `load()`; parent's `doc` re-renders with the server line
  carrying an `id` (no `_uid`); K71's effect calls
  `setLocalItems(_normalize(doc.line_items))` — full replace.
  The `_uid`-keyed optimistic row is DROPPED, replaced by the
  `id`-keyed server row. No append, no duplicate.
* **Delete**: `handleDelete` runs `filter((_, i) => i !== idx)`
  through `_normalize`, then schedules the parent PUT via
  `setTimeout(5000)`. During the window the row does not appear
  in local state; if `handleUndo` fires first, `splice` restores
  the exact stored `line` object (same stable id) at the same
  index — the `_normalize` on the restored array collapses the
  row if the parent has already re-emitted the server copy during
  the window.
* **Undo**: as above — `_normalize(restored)` guarantees a single
  row per stable id even in the pathological "parent already
  reloaded during the undo window" race.

## Testids stability

All existing `data-testid` values kept their index-based scheme
(`k71-row-<i>`, `k71-card-<i>`, `k71-edit-btn-<i>`, `k71-input-*-<i>`,
`k71-card-edit-btn-<i>`, `k71-card-delete-btn-<i>`, …) so the
4300+ existing suite continues to pass unchanged. Only the React
`key=` prop switched to a stable identifier.

## Test coverage

`test/k71-line-items-stable-id-keys.test.jsx` — 5 assertions:

1. **De-dup on initial load** — input array carrying two entries
   with the same `id` renders exactly one `<tr>` and one `<li>`.
2. **De-dup on re-sync** — parent transitions from one line to a
   duplicated pair; K71 re-normalizes and stays at one row.
3. **Optimistic add → server confirm** — full end-to-end flow;
   the optimistic `next` shipped to `onLinesUpdated` carries a
   `_uid`; after the parent's reload the row is replaced by its
   `id`-tagged copy; DOM has exactly two rows (existing + fresh),
   never a lingering optimistic duplicate.
4. **Delete → Undo restores once** — assert exactly one Alpha row
   post-undo, no accidental duplicate.
5. **Null-id inputs get a client-minted `_uid`** — legacy-shaped
   payload (no `id`, no `_uid`) still renders without React key
   warnings. Assertion wraps `console.error` to catch the
   "Each child in a list should have a unique 'key' prop" message.

## Mobile Expo parity (out of scope · flagged)

`app/mobile/` line-item editors were **not** touched in this
dispatch. If they carry the same array-index key anti-pattern,
that follow-up belongs on the `e1_expo_frontend_dev` delegation.
Flagging here so it isn't lost.

## Runtime health

* `curl /` → 200
* `curl /api/openapi.json` → 200, **paths = 1734** (unchanged —
  frontend-only change)
* Frontend hot-reload picked up the JSX changes; no supervisor
  restart required.

## Full-suite status

```
Test Files  570 passed | 1 skipped (571)
     Tests  4305 passed | 34 skipped (4339)
Exit code   0
```

Baseline pre-dispatch: 4300. Delta: **+5** (new
`k71-line-items-stable-id-keys.test.jsx`). No regressions in the
touched K71 suite (`k71-line-items-editor.test.jsx` 18 tests +
`k71-line-items-responsive-cards.test.jsx` 5 tests +
`pb2-line-item-overrides.test.jsx` 5 tests all still green).
