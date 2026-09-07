# Phase K80.a — Add + Delete Line-Item Affordances on `K71LineItemsEditor`

**Ship date**: Feb-2026  
**Scope**: Frontend only, ~2–3 hr as scoped. K80.b (server-side status
gate on `PUT /quotes/{id}`) and K79 (grouped customer-facing lines) are
deliberately queued behind this.

## Problem

The K71 inline line-items editor supported edit-in-place only. There
was no way for staff to **add** a new line to a saved estimate/quote,
and no way to **delete** an existing line from a saved doc through the
K71 surface. Adding/deleting was only reachable on invoices via the
separate `InvoiceEditModal`, but never on quotes/estimates — a hard
feature gap surfaced during the K80 recon.

## What ships

### 1. `+ Add line` button (`k71-add-line-btn`)

- Rendered under the line-items table when `canEdit === true`.
- Appends an empty scaffolded line (`qty=1`, `unit_price=0`, empty
  description + category ids) and enters inline-edit mode on the new
  row immediately (`editIndex` set to the new row).
- **Cancel on a new (never-saved) line discards it entirely** — the
  scaffold row does not linger. Existing-row Cancel behaviour is
  unchanged.
- Disabled (with tooltip) while any row is currently in edit mode OR
  while a pending delete is in its undo window. This keeps state
  reasoning simple: only one uncommitted local change at a time.

### 2. Trash icon per row (`k71-delete-btn-{idx}`)

- Rendered in the rightmost column alongside the pencil, when
  `canEdit === true`.
- On click: the row is removed from the visible table **locally**, a
  dark undo toast (`k71-undo-toast`) mounts with an "Undo" button
  (`k71-undo-btn`), and a 5-second timer starts.
- If **Undo** is clicked within the window: the timer is cleared and
  the row is spliced back into `localItems` at its original index.
  `onLinesUpdated` is never called.
- If the timer elapses: `onLinesUpdated` fires with the current
  `localItemsRef.current` (the deleted row absent, any adds/edits from
  the window included). Parent then triggers its usual reload.
- Only **one** pending delete at a time. Trash buttons on other rows
  are disabled during the window; Add-line is disabled during the
  window.

### 3. Category-required validation reused

- Adding a line then clicking Save without a Service + Income category
  reuses the exact same K71 validation as edit-in-place: inline error
  banners appear on both pickers, and `onLinesUpdated` is not called.
- Added lines that are Cancelled/Undone never round-trip to the
  server, so validation is not evaluated against transient state.

### 4. Discoverability fix on `QuoteInvoiceDetail.jsx`

- The `Edit invoice` button that opens `InvoiceEditModal` is now
  **hidden on draft invoices** — K71 inline add/edit/delete covers
  that case fully. Kept visible on `sent`, `paid`, `void`, and
  `cancelled` where the modal's typed-confirm / warning UX matters.
- Relabelled to **`Edit invoice (advanced)`** with a tooltip so users
  understand it's the fuller surface (line-items + discount +
  doc-level fields, with confirmation guards). Same
  `qd-edit-invoice` test id preserved for existing coverage.

## What is NOT touched (deliberate)

- **Backend**: zero backend changes. `PUT /api/quotes/{id}` continues
  to accept the full array replacement. The frontend sends whatever
  the user has locally on save. Server-side status gating for PUT is
  **K80.b** — separate phase, security hardening.
- **34 Hygiene B skips**: untouched. Zero new quarantines.
- **I1.5 / I1.7.a / I1.7.b code**: untouched.
- **`InvoiceEditModal.jsx`**: untouched — still the fuller editor for
  non-draft invoices.

## Files changed

| File | Nature |
|---|---|
| `frontend/src/components/quotes/K71LineItemsEditor.jsx` | Rewritten with local state (localItems, editIndex, newLineIndex, pendingDelete) + Add/Delete/Undo UX. Header comment updated. |
| `frontend/src/pages/quotes/QuoteInvoiceDetail.jsx` | Gated the `Edit invoice` button behind non-draft statuses and relabelled to `Edit invoice (advanced)` with a tooltip. |
| `frontend/src/test/k71-line-items-editor.test.jsx` | +11 K80.a tests covering visibility, add flow, cancel discards new line, delete-with-undo toast, undo restoration, timeout commit. |

## Tests

`yarn vitest run` → **477 test files pass, 1 skipped (Hygiene B quarantine file), 3758 tests pass, 34 skipped (Hygiene B skips untouched)**.

K71 test file scope: **18 tests pass** (7 baseline + 11 new K80.a).

New K80.a cases:

1. `k71-add-line-btn` renders when canEdit=true.
2. `k71-add-line-btn` hidden when canEdit=false.
3. `k71-delete-btn-{idx}` renders per row when canEdit=true.
4. `k71-delete-btn-{idx}` hidden per row when canEdit=false.
5. Clicking Add appends an empty row + enters edit mode on it.
6. Cancel on a NEW line removes it entirely from the table.
7. Add + Save without categories → inline validation errors, no
   `onLinesUpdated` call.
8. Trash click hides the row + shows undo toast + no commit yet.
9. Undo within window restores the row + cancels the pending commit
   (verified by advancing fake timers past 5s: still no commit).
10. Timeout elapsing commits `onLinesUpdated` with the deleted row
    excluded from the array.

## Screenshots

- `/tmp/k80a_1_baseline.png` — draft quote with new `+ Add line` button
  under the line-items table and red trash icon alongside the pencil.
- `/tmp/k80a_2_undo_toast.png` — dark undo toast anchored below the
  table ("Line item removed." + "Undo"), Add-line correctly dimmed
  during the pending window.

## Design invariants preserved

- No hardcoded hex regressions (delete uses `#DC2626` matching the K71
  error convention already in the file; undo toast uses `#1F2937`
  slate + `#F9FAFB` on-surface — new but bounded to the toast).
- No theme regressions.
- No emoji.
- Same table headers and column widths (rightmost column widened 12 → 20
  to fit both pencil and trash side-by-side; verified visually).
- The K71 gap banner, legacy badge, and long-description muted line
  render exactly as before.

## Next in queue

- **K79**: grouped customer-facing line items by `service_category_id`
  (portal + PDF surfaces).
- **K80.b**: close the server-side security gap. `PUT /api/quotes/{id}`
  currently accepts `line_items` on ANY status (draft/sent/accepted/paid/
  converted). Mirror the `PATCH /api/quotes/{id}` gates (terminal blocks
  outright; sent requires confirmation; paid requires typed invoice
  number OR relocate inline K71 saves to PATCH). Product decision needed
  on whether `sent` estimates should be editable at all — frontend and
  backend currently disagree.
- **I1.7.c**: AI BYO providers + Maps + Calendars.
