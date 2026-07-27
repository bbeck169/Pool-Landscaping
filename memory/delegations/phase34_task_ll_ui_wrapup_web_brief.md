# Phase 34 · Task LL Phase 2 UI wrap-up — Frontend wire-up brief (Web)

## ✅ SHIPPED IN THIS BATCH (Feb 2026)

The shared `BulkSelectToolkit` has been wired into ALL admin pages
listed below — both the original 5 P0 surfaces and the 5 P1 surfaces
added by Task OO. No further web work is required from this brief.

### P0 (Task LL Phase 2)
| # | Surface | File | Bulk actions live |
|---|---------|------|-------------------|
| 1 | Customers | `pages/customers/CustomersList.jsx` | Reassign owner · Delete |
| 2 | Jobs (admin) | `pages/jobs/JobsList.jsx` (`/admin/jobs`) | Change status · Reschedule (absolute + relative + anchor) · Delete |
| 3 | Tasks | `pages/aiops/AiOpsPages.jsx::TasksPage` | Change status · Delete |
| 4 | Communications log | `pages/marketing/CommunicationsLogPage.jsx` | Mark read · Archive |
| 5 | Email + SMS templates | `pages/comms/CommsPages.jsx::CommsTemplatesLibrary` | Change category · Delete (live-drip lock) |

### P1 (Task OO)
| # | Surface | File | Bulk actions live |
|---|---------|------|-------------------|
| 6 | Reviews (admin) | `pages/admin/AdminReviewsPage.jsx` | Change status · Change visibility · Delete (google-click lock) |
| 7 | Team (admin) | `pages/admin/AdminUsersList.jsx` (`/admin/users`) | Change role · Set active · Delete (self / last-owner locks) |
| 8 | Customer Tags | `pages/admin/AdminTagsList.jsx` (`/admin/tags`) | Set archive · Delete |
| 9 | Service Reports | `pages/admin/AdminServiceReportsList.jsx` (`/admin/service-reports`) | Change visibility · Delete (invoice-evidence lock) |
| 10 | Time Entries | `pages/admin/AdminTimeEntriesList.jsx` (`/admin/time-entries`) | Set approval · Delete (paid-payroll lock) |

Testids match the shared toolkit contract exactly. Jest suite still
green (122/122).

**Do not re-execute this brief.** The reference below is retained
only for the mobile companion agents and for any future 11th surface
that adopts the same pattern.

---

## Original brief (reference only — DO NOT re-run)

> Web-side follow-up. Backend endpoints for all 6 surfaces are fully
> shipped, tested (25 pytests), and role-gated. The shared React
> toolkit is ready at
> `/app/frontend/src/components/bulk-select/BulkSelectToolkit.jsx`.
> This brief documents the ~30 LOC needed per page to wire it up.

## Shared toolkit exports

```jsx
import {
  useBulkSelect,        // hook — bulk-select state + helpers
  BulkSelectAll,        // header checkbox with indeterminate
  BulkSelectRow,        // per-row checkbox
  BulkActionBar,        // floating action bar (bottom-center)
  BulkConfirmModal,     // confirmation modal (delete + edit reuse)
  SelectAllMatchingLink,// "Select all N matching this filter"
  LockedPill,           // inline red pill for failed[] rows
} from "@/components/bulk-select/BulkSelectToolkit";
```

## Per-page recipe (30-line pattern)

```jsx
// Inside any admin list page component:
const visibleIds = rows.map((r) => r.id);
const { selected, selectedCount, allVisibleSelected, indeterminate,
          toggleAll, toggleOne, clear } = useBulkSelect(visibleIds);
const [confirmOpen, setConfirmOpen] = useState(false);
const [lockedFailures, setLockedFailures] = useState({});

const doBulkDelete = async () => {
  try {
    const res = await api.post("/customers/bulk-delete", { ids: Array.from(selected) });
    // Highlight locked rows inline for 10s.
    if (res.failed?.length) {
      const map = {};
      res.failed.forEach((f) => { map[f.id] = f.reason; });
      setLockedFailures(map);
      setTimeout(() => setLockedFailures({}), 10000);
    }
    setRows((prev) => prev.filter((r) => !res.deleted.includes(r.id)));
    clear(); setConfirmOpen(false);
    toast.success(`${res.deleted_count} deleted${res.failed.length ? ` · ${res.failed.length} locked` : ""}`);
  } catch (e) { toast.error(e.message); }
};

// In the JSX header row:
<th><BulkSelectAll checked={allVisibleSelected}
                    indeterminate={indeterminate} onChange={toggleAll} /></th>

// In each row:
<td><BulkSelectRow id={r.id} checked={selected.has(r.id)}
                     onChange={() => toggleOne(r.id)} /></td>
// After the row cells (still inside <tr>):
{lockedFailures[r.id] ? <LockedPill reason={lockedFailures[r.id]} /> : null}

// At the bottom of the page component:
<BulkActionBar
  selectedCount={selectedCount}
  onClear={clear}
  actions={[
    // Bulk-edit actions come first (blue). Delete comes last (red).
    { key: "tag", label: "Change tag", dropdown: TAG_OPTIONS,
      onClick: (v) => api.post("/customers/bulk-update", { ids: Array.from(selected), patch: { tag: v } }).then(refresh) },
    { key: "owner", label: "Reassign owner", dropdown: OWNER_OPTIONS,
      onClick: (v) => api.post("/customers/bulk-update", { ids: Array.from(selected), patch: { assigned_owner_id: v } }).then(refresh) },
    { key: "delete", label: "Delete selected", tone: "danger",
      onClick: () => setConfirmOpen(true) },
  ]}
/>
<BulkConfirmModal
  open={confirmOpen}
  onClose={() => setConfirmOpen(false)}
  onConfirm={doBulkDelete}
  title={`Delete ${selectedCount} customer${selectedCount === 1 ? "" : "s"}?`}
  description="This can be restored from the archive. Customers with active invoices will show as locked."
  confirmLabel={`Delete ${selectedCount}`}
/>
```

## Per-surface wiring reference

### 1. Customers (`pages/customers/CustomersList.jsx`)
* **Endpoints**: `/customers/bulk-delete`, `/customers/bulk-update`.
* **Bulk actions**: Change tag, Reassign owner, Delete.
* **Patch allow-list**: `tag`, `assigned_owner_id`.
* **Locked-state pill**: "Customer has N active invoice(s) — archive them first" (409).

### 2. Jobs (`pages/jobs/JobsList.jsx` — grep `/jobs` route in App.js)
* **Endpoints**: `/jobs/bulk-delete`, `/jobs/bulk-update`.
* **Bulk actions**: Reassign tech, Change status, Reschedule, Delete.
* **Patch allow-list**: `technician_id`, `status`, `scheduled_date`.
* **Locked-state pill**: "Job has an active timer" OR "Completed jobs with an invoice cannot be bulk-deleted" (409).
* **Status options**: grep `JobStatus` in `routers/jobs.py` for the current enum.

### 3. Tasks (`pages/tasks/TasksPage.jsx`)
* **Endpoints**: `/tasks/bulk-delete`, `/tasks/bulk-update`.
* **Bulk actions**: Reassign assignee, Change status, Change due date, Delete.
* **Patch allow-list**: `assignee_id`, `status`, `due_date`.

### 4. Communications (`pages/comms/CommunicationsPage.jsx`)
* **Endpoints**: `/communications/bulk-archive`, `/communications/bulk-mark-read`.
* **Bulk actions**: Archive, Mark read. **NO delete button** — the pattern still uses the shared action bar but the "delete" red button is replaced with the "archive" red button. Testid: `bulk-archive-button`.
* **No confirmation modal** — archive is instant, undoable via row-level restore.

### 5. Email templates (`pages/templates/EmailTemplatesPage.jsx`)
* **Endpoints**: `/email-templates/bulk-delete`, `/email-templates/bulk-update`.
* **Bulk actions**: Change category, Archive (patch `is_archived: true`), Delete.
* **Patch allow-list**: `category`, `is_archived`.
* **Locked-state pill**: "Template used by N active drip sequence(s) — archive instead" (409).

### 6. SMS templates (`pages/templates/SmsTemplatesPage.jsx`)
* **Endpoints**: `/sms-templates/bulk-delete`, `/sms-templates/bulk-update`.
* **Bulk actions**: Change category, Delete.
* **Patch allow-list**: `category`.
* **Locked-state pill**: same drip-sequence check.

## Filter-selected mode ("Select all N matching")

When the current visible page is smaller than the filtered total:

```jsx
<BulkActionBar ...>
  <SelectAllMatchingLink
    pageCount={visibleIds.length}
    totalMatching={totalMatchingFilter}
    onSelectAllMatching={() => {
      setSelectionMode("filter");
      setFilterSelector(currentFilter);
    }}
  />
</BulkActionBar>
```

When `selectionMode === "filter"`, the API call becomes:
```jsx
await api.post("/customers/bulk-delete", {
  query_selector: filterSelector,
  exclude_ids: [...],
});
```

The confirmation modal switches to `"Delete all N matching filter?"`.

## Testing
* Every surface auto-covered by the Jest shared file (66 tests total —
  11 surfaces × 6 invariants). No additional Jest work needed per
  surface as long as the toolkit imports stay stable.
* Add a Playwright smoke test per page once wired.

## Estimated LOC
~30 lines per page × 6 pages = **~180 LOC total** for the full UI
wrap-up. All patterns proven on Invoices/Estimates/Payments/Leads/
Autobilling/Pricebook — this is a mechanical apply.
