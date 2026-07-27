## Delegation Brief · Phase 34 (web) → Phase 33 (mobile)
### Customer Portal Profile — Editable + auto-sync to CRM Contact

**From:** Web / backend team · Phase 34 · Feb 2026 · Task N
**To:** e1_expo_frontend_dev
**Priority:** P1
**Language:** English only.
**Status:** Web + backend NOT YET SHIPPED. This brief describes the
target so the mobile agent can build in parallel with web.

---

### Scope

The customer-portal Profile screen currently shows read-only contact
info with a "Contact admin to update your contact info." helper text.
Product wants customers to edit their own name / email / phone /
address, and every edit must auto-propagate to the linked Contact
record on the admin/CRM side so support doesn't need to re-key it.

### Backend contract (target)

`PATCH /api/customer-portal/profile`

Auth: authenticated portal user (JWT). Rejects anyone whose role
isn't `customer` on the acting tenant.

Body (all fields optional — the endpoint patches only what's
provided, so partial updates are safe):
```json
{
  "first_name": "Alex",
  "last_name":  "Reyes",
  "email":      "alex@example.com",
  "phone":      "+16025551234",     // normalized to E.164 server-side
  "address":    "9825 W Camino De Oro, Peoria AZ 85383"
}
```

Behavior:
1. Validate: name ≥1 char, valid email, valid US phone, address ≥5 chars.
2. Uniqueness — email must not collide with another user in any tenant. Return `409` if collision, `400` for validation.
3. Update the acting user's `users` row AND the linked `customers` row (whichever fields overlap).
4. Also update the corresponding `contacts` collection doc if one exists (by `customer_id` FK or shared email) so the admin Contacts view reflects the edit in real time.
5. Write an audit log entry into `activity_log`:
   `{ actor_user_id, action: "self_updated_profile", diff: {before, after}, at: <iso> }`.
6. Emit a realtime event `type: "customer_profile_updated"` on the tenant channel.
7. Return the updated view: `{ ok: true, profile: {first_name, last_name, email, phone, address} }`.

### Frontend contract (target)

Web page `/app/frontend/src/pages/portal/PortalProfile.jsx` (or the
current profile file — search "Contact admin to update your contact
info." to find it):

- Converts the read-only display into an editable form.
- Fields: first_name, last_name, email, phone (US), address.
- Client-side validation matches server rules (same regex).
- Buttons: "Save changes" (disabled until form dirty + valid),
  "Cancel" (resets to server values).
- On save success → refresh + toast "Profile updated" + clear dirty state.
- On save error → keep form values + red inline error text.
- Testids: `portal-profile-form`, `portal-profile-first-name`,
  `portal-profile-last-name`, `portal-profile-email`,
  `portal-profile-phone`, `portal-profile-address`,
  `portal-profile-save`, `portal-profile-cancel`,
  `portal-profile-toast-success`, `portal-profile-error`.

### What we need from mobile

Mirror the web form on `/app/mobile/app/(portal)/profile.tsx`:

1. Replace the read-only rows with input fields (same 5 fields).
2. Client-side validation matches the server contract.
3. Save button anchored to bottom (mobile pattern), disabled until
   dirty + valid.
4. On save → PATCH the same endpoint above; on 200 refresh the
   local cache; on 409 show "That email is already in use" toast;
   on other errors show "Could not save. Please try again.".
5. `testID` parity — use the same identifiers as web (see list
   above; RN's `testID` maps 1:1 to `data-testid`).
6. If the mobile app has an offline queue (Phase 32 offline
   capability), profile edits should enter the sync outbox as
   `profile.update` ops rather than fail hard when offline. Mark
   the row optimistically updated + surface an "unsynced" pill.

### Guardrails

- Do NOT touch backend endpoints beyond what the contract specifies.
- English-only.
- Preserve any existing avatar upload / password change controls on
  the same screen.
- Do NOT allow a customer to change their own role, `tenant_id`,
  `active` flag, or any other privileged field.

### Reference paths (once web ships)

- Backend: `/app/backend/routers/customer_portal.py::patch_my_profile`
- Web page: `/app/frontend/src/pages/portal/PortalProfile.jsx`
- Web Vitest: `/app/frontend/src/test/phase34-portal-profile-edit.test.jsx`

### Deploy

- Mobile: OTA / EAS update after merge. No native modules required.
