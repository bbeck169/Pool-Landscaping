# Feature — Customer Equipment Library (canonical resource)

**Phase**: Feb-2026  
**Scope**: Web (backend + frontend). Mobile parity delegated separately.

## Summary

Introduces a proper `customer_equipment` resource: one document per
installed equipment unit at a customer's site, carrying
`equipment_type` + `brand` + `model` + `serial_number` + `install_date`
+ `notes`. Photos are stored on **S3 via `/api/files/upload`** and joined
into the equipment record by `linked_entity_type='customer_equipment'`.

The legacy `customer_equipment_photos` collection and
`/customers/{id}/equipment-photos` routes remain **untouched** for
back-compat. Historical base64 blobs are **not** migrated in this phase
— deferred to Phase-3 S3 cutover.

## Schema delta

Collection: `customer_equipment` (new).

```json
{
  "id": "<uuid>",
  "tenant_id": "<tenant>",
  "customer_id": "<customer>",
  "equipment_type": "Filter Pump",   // enum EQUIPMENT_TYPES
  "brand": "Pentair",                // Optional[str], max 200 chars
  "model": "IntelliFlo",             // Optional[str], max 200 chars
  "serial_number": "SN-12345",       // Optional[str], max 200 chars
  "install_date": "2024-04-11",      // Optional ISO date (YYYY-MM-DD)
  "notes": "…",                       // Optional, max 2000 chars
  "created_by_user_id": "<user>",
  "created_by_name": "<display>",
  "created_at": "<iso8601>",
  "updated_at": "<iso8601>",
  "is_deleted": false,
  "deleted_at": null
}
```

Soft-delete: `is_deleted=True` + `deleted_at` timestamp. Deleted units
disappear from listings and 404 on direct GET.

## Endpoints

All routes prefixed `/api/customer-equipment`:

| Method | Path                                | RBAC              |
|-------:|-------------------------------------|-------------------|
| POST   | `/customer-equipment`               | admin / tech      |
| GET    | `/customer-equipment?customer_id=X` | admin / tech (customer 403) |
| GET    | `/customer-equipment/{id}`          | admin / tech      |
| PATCH  | `/customer-equipment/{id}`          | admin / tech      |
| DELETE | `/customer-equipment/{id}`          | admin / tech      |

OpenAPI paths delta: **+2** (1741 → 1743). `GET/POST` share
`/customer-equipment` and `GET/PATCH/DELETE` share `/customer-equipment/{equipment_id}`.

## Photo pipeline (S3, no base64)

Photos upload via the existing `/api/files/upload` endpoint with:

- `purpose='customer_equipment'`
- `linked_entity_type='customer_equipment'`
- `linked_entity_id=<equipment_id>`

Every equipment `GET` response includes:

```json
"photos": [
  {
    "id": "<file_id>",
    "filename": "<original>",
    "content_type": "image/png",
    "size": 1234,
    "url": "/api/files/<file_id>/download"
  }
]
```

The `url` requires a bearer token — customers are out of scope in v1,
so tech-scoped downloads are sufficient.

## Auth boundaries

- **admin / super_admin / technician** → create / edit / delete / read.
- **customer** → 403 on every read + write. (v1 does not expose the
  equipment library on the customer portal.)
- Tenant isolation via `get_current_tenant`; cross-tenant reads 404.

## Frontend testid map

| Element | testid |
|--------|--------|
| Root component | `customer-equipment-library` |
| Empty state | `equipment-empty` |
| Loading state | `equipment-loading` |
| Error state | `equipment-error` |
| List container | `equipment-list` |
| Add Equipment button | `equipment-add-btn` |
| Add / Edit modal | `equipment-form-modal` |
| Modal close | `equipment-form-close` |
| Modal cancel | `equipment-form-cancel` |
| Modal submit | `equipment-form-submit` |
| Modal error | `equipment-form-error` |
| Type select | `equipment-type-select` |
| Brand input | `equipment-brand-input` |
| Model input | `equipment-model-input` |
| Serial input | `equipment-serial-input` |
| Install date input | `equipment-install-date-input` |
| Notes input | `equipment-notes-input` |
| Card (per unit) | `equipment-card-<id>` |
| Card type header | `equipment-card-type-<id>` |
| Card field block | `equipment-card-fields-<id>` |
| Card notes | `equipment-card-notes-<id>` |
| Card edit button | `equipment-card-edit-<id>` |
| Card delete button | `equipment-card-delete-<id>` |
| Photo add / upload | `equipment-photo-upload-<id>` |
| Hidden file input | `equipment-photo-input-<id>` |
| Photo thumb | `equipment-photo-thumb-<i>` |
| Photo thumb delete | `equipment-photo-thumb-<i>-delete` |
| Photo error banner | `equipment-photo-error-<id>` |

## Coupling notes for mobile parity dispatch

- Mobile client (`/app/mobile/`) currently reads from
  `/customers/{id}/equipment-photos` (legacy). It is **not** affected
  by this phase — both endpoints coexist.
- To land parity, the Expo dev agent should:
  1. Add a new "Equipment (units)" screen that hits
     `GET /api/customer-equipment?customer_id=…`.
  2. Reuse the mobile `/files/upload` wrapper for photo capture with
     the `customer_equipment` linkage keys above.
  3. Preserve the existing legacy photo grid until the Phase-3 S3
     cutover retires it.
- **Guardrail**: main agent must not modify `/app/mobile/`. Mobile
  work is delegated to `e1_expo_frontend_dev`.

## Deferred (explicitly out of scope)

- Historical base64 photo migration (Phase-3 S3 cutover owns).
- Customer portal read-access (v1 skipped).
- Removing / hiding the legacy `/customers/{id}/equipment-photos`
  routes.
- Mobile parity screen (delegated to the Expo dev agent).

## Test coverage

- Backend: `backend/tests/test_customer_equipment_library.py`
  - Admin create with all fields
  - Tech create + patch (auth widened past admin-only)
  - Customer 403 on write and read
  - Invalid `equipment_type` rejected
  - List returns created units
  - Soft delete hides from list + 404 on direct GET
  - Unknown id → 404
  - Photo joined via `/api/files/upload` (skipped when S3 unconfigured)
- Frontend (Vitest): `frontend/src/test/customer-equipment-library.test.jsx`
  - Empty state
  - Admin add flow via modal (testid map + POST body assertion)
  - Card renders brand/model/serial/install_date fields
  - Customer role: no Add / Edit / Delete / photo-upload controls
  - Tech photo upload → `uploadFile` invoked with `customer_equipment`
    linkage metadata
