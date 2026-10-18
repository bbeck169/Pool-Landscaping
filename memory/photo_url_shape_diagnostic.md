# TD-76-aux · Photo URL Shape Diagnostic

**Run at:** 2026-10-18T10:41:41.697309+00:00
**MONGO_URL:** `mongodb://localhost:27017`
**DB:** `Pool_&_Landscaping_of_Vistancia`

**READ-ONLY.** No writes performed. Pure Phase B scoping data.

## Classification regexes

| Shape | Regex |
|---|---|
| `valid_http` | `^https?://` |
| `relative_api` | `^/api/` |
| `raw_s3_key` | `^(Photos|photos|Videos|videos|media|Media)/` |
| `raw_storage_path` | `^[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9._/-]+$` |
| `empty_or_null` | missing / `None` / `""` |
| `other` | everything else (sampled below) |

## `jobs.photos[]` (total subdocs: 13)

**URL shape counts:**

| Shape | Count |
|---|---|
| `valid_http` | 1 |
| `relative_api` | 0 |
| `raw_s3_key` | 0 |
| `raw_storage_path` | 0 |
| `empty_or_null` | 12 |
| `other` | 0 |

**Adjacent-field counts:**

| Adjacency | Count |
|---|---|
| `has_storage_path` | 0 |
| `has_thumb`        | 0 |
| `neither_storage_nor_thumb` | 13 |

**Top-5 tenants by problematic count:**

| Tenant | Total photos | Problematic (raw_s3_key + raw_storage_path + empty + other) |
|---|---|---|
| `affdfbfa-88b9-4baa-ae45-2ef78531b6e4` | 9 | 8 |
| `P44_TENANT_8a8868a6` | 2 | 2 |
| `P44_TENANT_48e5a932` | 1 | 1 |
| `P44_TB_4ed3a3ec` | 1 | 1 |

## `estimates.photos[]` (total subdocs: 0)

**URL shape counts:**

| Shape | Count |
|---|---|
| `valid_http` | 0 |
| `relative_api` | 0 |
| `raw_s3_key` | 0 |
| `raw_storage_path` | 0 |
| `empty_or_null` | 0 |
| `other` | 0 |

**Adjacent-field counts:**

| Adjacency | Count |
|---|---|
| `has_storage_path` | 0 |
| `has_thumb`        | 0 |
| `neither_storage_nor_thumb` | 0 |
