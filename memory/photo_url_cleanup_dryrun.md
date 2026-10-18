# TD-76-ph2d · Preview DB dead-photo cleanup — DRY RUN

**Run at:** 2026-10-18T21:00:55.759342+00:00
**MONGO_URL:** `mongodb://localhost:27017`
**DB:** `Pool_&_Landscaping_of_Vistancia`

**DRY RUN.** Zero writes performed.
**Pass `--apply` to physically remove the rows.**

## `jobs.photos[]` — 12 dead subdocs across 11 parent docs

**Per-tenant breakdown (top 10):**

| Tenant | Dead photos |
|---|---|
| `affdfbfa-88b9-4baa-ae45-2ef78531b6e4` | 8 |
| `P44_TENANT_8a8868a6` | 2 |
| `P44_TENANT_48e5a932` | 1 |
| `P44_TB_4ed3a3ec` | 1 |

**Sample dead photo_ids:**

```
- tenant=affdfbfa-88b9-4baa-ae45-2ef78531b6e4  doc_id=ab88fb26-cf98-4934-8db6-ed422b72ec3d  photo_id=b2a25830-28a5-4c3b-8d57-34285314f248
- tenant=affdfbfa-88b9-4baa-ae45-2ef78531b6e4  doc_id=86d1d202-4009-400e-b424-f25c8d131098  photo_id=f769d184-543a-481c-8c51-9aad5d0a035e
- tenant=affdfbfa-88b9-4baa-ae45-2ef78531b6e4  doc_id=6e335a35-cb53-4496-8c23-c5b6f3ad2b76  photo_id=38c46f24-6845-4eb0-b19b-52876af78932
- tenant=affdfbfa-88b9-4baa-ae45-2ef78531b6e4  doc_id=77667317-dab9-412d-8eb0-12efbf944842  photo_id=9f7dd57f-38ec-4772-b5b6-4306aa48000f
- tenant=affdfbfa-88b9-4baa-ae45-2ef78531b6e4  doc_id=08af77d0-38d7-4307-81b2-f121a758547d  photo_id=d85a0599-7689-48c0-900c-160169534592
- tenant=affdfbfa-88b9-4baa-ae45-2ef78531b6e4  doc_id=seed-opt-1  photo_id=ad625005-8e2e-4a92-9555-fbefaf7d28af
```

## `estimates.photos[]` — 0 dead subdocs across 0 parent docs

## Next action

Re-run with `--apply` to physically remove the dead rows.
`$pull` filter: `url` empty/missing AND `storage_path` empty/missing AND `thumb` empty/missing.