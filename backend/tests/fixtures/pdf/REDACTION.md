# Task H · Phase H.1 · Fixture provenance + redaction log

Every real PDF fixture in this directory was redacted from a raw
source (unrelated customer PII) via ``_redact_and_split.py`` — the
post-redaction SHAs below are the exact bytes committed to the
repo.  Pre-redaction SHAs are recorded for provenance ONLY — the
raw PDFs are NEVER committed.

## Raw-source pre-redaction SHA-256 (never committed)

| SHA-256 | Bytes | File |
|---|---|---|
| `1b63bf6424d4be34851c9dafb3c5da35863b65a6b0595951d99b0029ad88da29` | 221,877 | `invoice_batch_17_digital.pdf` (raw) |
| `56dadb5c2d0c6de307604b5606007f71b18def3a7bd7b3a61fd6fb073226e67a` | 109,587 | `estimate_single_11item_scanned.pdf` (raw) |
| `3f65e64acd26e2fa39f55f7692675967df6c21d4d568480b3422f6830c205c34` | 106,970 | `payment_receipt_single_digital.pdf` (raw) |

## Committed post-redaction SHA-256

| SHA-256 | Bytes | File |
|---|---|---|
| `b577a4d0a99b251efb6e1fc0ea8e15f9a69f85be040d61a2dff88693eb24a11a` | 213,194 | `invoice_batch_17_digital.pdf` |
| `47d3bd88ed803f59a15ae9581155ba1636600e1f6ccb5c4515bcc6e10c274b8b` | 94,883 | `invoice_single_1item_digital.pdf` |
| `4f50d59411fbd0b1ee72ee5fc5a44ab502b0915e4f04c1f869b8600726faf7ec` | 94,889 | `invoice_single_multiline_digital.pdf` |
| `e14257fc82f8f8d867dbb96289c7951571d622aef2cf61f624f57dcc3d0a559a` | 108,676 | `estimate_single_11item_scanned.pdf` |
| `d64484fa6df791383ec2f65cb227e464d0487d803e71ba063512ac0b5d48c668` | 105,661 | `payment_receipt_single_digital.pdf` |

## Redaction targets (all `search_for` verified post-write)

**Diane Lloyd batch + splits:**
- `Diane Lloyd` → `Test Customer A`
- `20271 N 51st Dr` → `123 Test Ln A`
- `Glendale AZ 85308` → `Testville AZ 00001`

**Srikant Mikkilineni estimate:**
- `Srikant Mikkilineni` → `Test Customer B`
- `30773 North 129Th Avenue` → `123 Test Ln B`
- `30773 North 129th Avenue` → `123 Test Ln B`

**Eric Torkelson payment receipt:**
- `Eric Torkelson` → `Test Customer C`
- `Brian Beckman` → `Ops Operator`  (audit-line operator; H.1 extractor must NEVER surface this as customer_name — see the operator-line disambiguation test case)

## Preserved (tenant business branding — NOT redacted)

- `Pool & Landscaping of Vistancia LLC`
- `24654 N. Lake Pleasant Pkwy Ste. 103-508`
- `Peoria AZ 85383` — tenant ZIP; note that Srikant's real
  address shared this ZIP.  Only the *street* was redacted for
  Srikant so the tenant brand identifier survives.
- `602-887-4400`
- `www.plofv.com`

## How to reproduce

```
python backend/tests/fixtures/pdf/_redact_and_split.py
```

The script is idempotent — running it against the same source
URLs + a clean ``/tmp/h1-pdfs/`` will produce the SAME committed
SHAs verbatim.  If any target string is missing from the raw
source (e.g. upstream URL updated), the script HALTS with a
clear error instead of writing a possibly-unredacted file.

## Run log (last execution)

    [split] src=invoice_batch_17_digital.pdf range=(1, 2) → _tmp_invoice_single_1item.pdf
    [split] src=invoice_batch_17_digital.pdf range=(3, 4) → _tmp_invoice_single_multiline.pdf
    ─── PRE-REDACTION SOURCE PROVENANCE ───
      1b63bf6424d4be34851c9dafb3c5da35863b65a6b0595951d99b0029ad88da29    221877  invoice_batch_17_digital.pdf
      56dadb5c2d0c6de307604b5606007f71b18def3a7bd7b3a61fd6fb073226e67a    109587  estimate_single_11item_scanned.pdf
      3f65e64acd26e2fa39f55f7692675967df6c21d4d568480b3422f6830c205c34    106970  payment_receipt_single_digital.pdf
    
    ─── REDACTION PASS ───
    [redact] file=invoice_batch_17_digital.pdf pre_sha=1b63bf6424d4be34851c9dafb3c5da35863b65a6b0595951d99b0029ad88da29 pre_bytes=221877
    [redact] file=invoice_batch_17_digital.pdf page=1 target='Diane Lloyd' rect=(16.6, 191.1, 70.9, 202.9)
    [redact] file=invoice_batch_17_digital.pdf page=1 target='20271 N 51st Dr' rect=(16.6, 202.8, 77.5, 212.8)
    [redact] file=invoice_batch_17_digital.pdf page=1 target='Glendale AZ 85308' rect=(16.6, 212.7, 91.9, 222.7)
    [redact] file=invoice_batch_17_digital.pdf post_sha=b577a4d0a99b251efb6e1fc0ea8e15f9a69f85be040d61a2dff88693eb24a11a post_bytes=213194 redact_ops=382
    [redact] file=invoice_single_1item_digital.pdf pre_sha=02f792e6a6490cdc696ae75053a874ee77632da3dce725e1ddb2cd5b963fc500 pre_bytes=94523
    [redact] file=invoice_single_1item_digital.pdf page=1 target='Diane Lloyd' rect=(16.6, 191.1, 70.9, 202.9)
    [redact] file=invoice_single_1item_digital.pdf page=1 target='20271 N 51st Dr' rect=(16.6, 202.8, 77.5, 212.8)
    [redact] file=invoice_single_1item_digital.pdf page=1 target='Glendale AZ 85308' rect=(16.6, 212.7, 91.9, 222.7)
    [redact] file=invoice_single_1item_digital.pdf post_sha=47d3bd88ed803f59a15ae9581155ba1636600e1f6ccb5c4515bcc6e10c274b8b post_bytes=94883 redact_ops=8
    [redact] file=invoice_single_multiline_digital.pdf pre_sha=53ab19d52e919fe69b25fb65daa92bb40d47c5f541d6a6c7db57c1ae9f78551c pre_bytes=94522
    [redact] file=invoice_single_multiline_digital.pdf page=1 target='Diane Lloyd' rect=(16.6, 191.1, 70.9, 202.9)
    [redact] file=invoice_single_multiline_digital.pdf page=1 target='20271 N 51st Dr' rect=(16.6, 202.8, 77.5, 212.8)
    [redact] file=invoice_single_multiline_digital.pdf page=1 target='Glendale AZ 85308' rect=(16.6, 212.7, 91.9, 222.7)
    [redact] file=invoice_single_multiline_digital.pdf post_sha=4f50d59411fbd0b1ee72ee5fc5a44ab502b0915e4f04c1f869b8600726faf7ec post_bytes=94889 redact_ops=8
    [redact] file=estimate_single_11item_scanned.pdf pre_sha=56dadb5c2d0c6de307604b5606007f71b18def3a7bd7b3a61fd6fb073226e67a pre_bytes=109587
    [redact] file=estimate_single_11item_scanned.pdf page=1 target='Srikant Mikkilineni' rect=(16.6, 191.1, 100.0, 202.9)
    [redact] file=estimate_single_11item_scanned.pdf page=1 target='30773 North 129Th Avenue' rect=(16.6, 202.8, 121.0, 212.8)
    [redact] file=estimate_single_11item_scanned.pdf page=1 target='30773 North 129Th Avenue' rect=(77.2, 277.1, 163.7, 285.3)
    [redact] file=estimate_single_11item_scanned.pdf page=1 target='30773 North 129th Avenue' rect=(16.6, 202.8, 121.0, 212.8)
    [redact] file=estimate_single_11item_scanned.pdf page=1 target='30773 North 129th Avenue' rect=(77.2, 277.1, 163.7, 285.3)
    [redact] file=estimate_single_11item_scanned.pdf page=2 target='Srikant Mikkilineni' rect=(53.2, 601.6, 130.1, 612.5)
    [redact] file=estimate_single_11item_scanned.pdf page=2 target='Srikant Mikkilineni' rect=(504.4, 632.6, 574.9, 642.6)
    [redact] file=estimate_single_11item_scanned.pdf page=2 target='30773 North 129Th Avenue' rect=(53.2, 612.4, 169.8, 623.3)
    [redact] file=estimate_single_11item_scanned.pdf page=2 target='30773 North 129th Avenue' rect=(53.2, 612.4, 169.8, 623.3)
    [redact] file=estimate_single_11item_scanned.pdf post_sha=e14257fc82f8f8d867dbb96289c7951571d622aef2cf61f624f57dcc3d0a559a post_bytes=108676 redact_ops=9
    [redact] file=payment_receipt_single_digital.pdf pre_sha=3f65e64acd26e2fa39f55f7692675967df6c21d4d568480b3422f6830c205c34 pre_bytes=106970
    [redact] file=payment_receipt_single_digital.pdf page=1 target='Eric Torkelson' rect=(358.8, 254.3, 426.6, 266.4)
    [redact] file=payment_receipt_single_digital.pdf page=1 target='Eric Torkelson' rect=(436.1, 318.7, 503.9, 330.8)
    [redact] file=payment_receipt_single_digital.pdf page=1 target='Brian Beckman' rect=(358.8, 318.7, 429.6, 330.8)
    [redact] file=payment_receipt_single_digital.pdf post_sha=d64484fa6df791383ec2f65cb227e464d0487d803e71ba063512ac0b5d48c668 post_bytes=105661 redact_ops=3
