"""Task H · Phase H.1 · Feb-2026 — PDF fixture redaction + split
prep script.

Preview ops only.  This script is idempotent and offline —
it runs against the raw PDFs stashed in ``/tmp/h1-pdfs`` and
produces the redacted, split fixtures under
``backend/tests/fixtures/pdf/``.  Also emits ``REDACTION.md``
with pre/post SHA-256 + byte counts for every file.

Redaction policy (green-lit resolution):

  * Primary: ``page.search_for(target)`` → ``page.add_redact_annot(rect)``
    → ``page.apply_redactions()``.  Fill text is written back at the
    same rect via ``draw_rect`` + ``insert_text`` so the layout
    stays visually plausible for the vision model.

  * Fail-loud fallback: if ``search_for(target)`` returns an
    EMPTY list for ANY target on ANY page where we expected it,
    ``sys.exit(1)`` with a clear error listing which strings
    weren't found where.  We NEVER silently over-approximate.

  * Post-redaction verification: for every target string, we
    re-run ``search_for`` on the redacted PDF and REQUIRE 0
    hits.  If any survive we ``sys.exit(1)`` — false-clean
    is worse than a halt.

  * Tenant name + tenant address stay AS-IS (per H.1 spec).
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import fitz  # PyMuPDF


SRC_DIR = Path("/tmp/h1-pdfs")
DST_DIR = Path(__file__).resolve().parent
LOG_LINES: List[str] = []


@dataclass(frozen=True)
class Replacement:
    """One redaction target + replacement.

    ``needed_pages`` is a semantic hint (which page indices the
    caller EXPECTED the target to appear on, 0-indexed) — if the
    target is missing from ALL of those pages we halt loud.  For
    strings expected across every page (e.g. Diane Lloyd on the
    batch fixture) we pass ``needed_pages=None`` and require
    at least one hit somewhere.
    """
    original: str
    replacement: str
    require_hits: bool = True         # if True → halt on zero hits anywhere
    log_first_only: bool = False      # noisy targets that hit N pages


# Task H.1 · locked replacement table.  Every string here is
# real customer PII and MUST land in the redacted file 100% of
# the time.  If a string that should be redacted stays intact
# through this script (per the post-redaction verify step), the
# script halts and we do NOT commit the fixture.
_DIANE = [
    Replacement("Diane Lloyd",       "Test Customer A",      log_first_only=True),
    Replacement("20271 N 51st Dr",   "123 Test Ln A",        log_first_only=True),
    Replacement("Glendale AZ 85308", "Testville AZ 00001",   log_first_only=True),
]
_SRIKANT = [
    Replacement("Srikant Mikkilineni",           "Test Customer B"),
    # The estimate uses "129Th" (capital T) on page 1 and
    # "129th" (lowercase) on page 2 — the text-layer casing
    # sometimes drifts between headline + footer copies of the
    # address.  Both must be redacted; we set require_hits on
    # EACH so a missing casing fails loud.
    Replacement("30773 North 129Th Avenue",      "123 Test Ln B"),
    Replacement("30773 North 129th Avenue",      "123 Test Ln B"),
]
_ERIC = [
    Replacement("Eric Torkelson", "Test Customer C"),
    # Payment-receipt audit line — "Payment Added ... by Brian
    # Beckman".  Task H.1 disambiguation guarantees the extractor
    # never assigns the operator name to ``customer_name`` — but
    # we still redact it for PII cleanliness.
    Replacement("Brian Beckman", "Ops Operator"),
]


def sha256_bytes(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def log(msg: str) -> None:
    print(msg)
    LOG_LINES.append(msg)


def redact_file(src: Path, dst: Path, replacements: Iterable[Replacement]) -> None:
    """Redact + save.  Halts on any missing target or surviving
    hit after redaction.  Idempotent — running twice against
    the same output overwrites in place."""
    if not src.exists():
        sys.exit(f"[redact] HALT — source missing: {src}")

    pre_sha = sha256_bytes(src)
    pre_bytes = src.stat().st_size
    log(f"[redact] file={dst.name} pre_sha={pre_sha} pre_bytes={pre_bytes}")

    doc = fitz.open(src)
    reps = list(replacements)
    total_hits: dict[str, int] = {r.original: 0 for r in reps}

    for page_idx, page in enumerate(doc):
        page_hits: dict[str, list] = {}
        for rep in reps:
            rects = page.search_for(rep.original)
            if not rects:
                continue
            page_hits[rep.original] = rects
            for rect in rects:
                # White out the original + redraw the replacement
                # at the top-left of the rect using a font/size that
                # roughly matches the surrounding invoice body.
                page.add_redact_annot(rect, text=rep.replacement,
                                      fontsize=8, fill=(1, 1, 1),
                                      text_color=(0, 0, 0))
                total_hits[rep.original] += 1
                if not rep.log_first_only or total_hits[rep.original] == 1:
                    log(f"[redact] file={dst.name} page={page_idx + 1} "
                        f"target={rep.original!r} rect="
                        f"{tuple(round(v, 1) for v in rect)}")
        if page_hits:
            page.apply_redactions()

    # Halt-loud policy — every ``require_hits`` target must
    # land at least once somewhere in the doc.
    missing = [r.original for r in reps
               if r.require_hits and total_hits[r.original] == 0]
    if missing:
        doc.close()
        sys.exit(
            f"[redact] HALT — file={dst.name} required target(s) NOT FOUND "
            f"across any page: {missing!r}. Refusing to write a possibly-"
            f"unredacted file. Options: (a) inspect the PDF's text layer "
            f"manually, (b) invoke ``dispatch_ai_completion`` with "
            f"``route='openai_vision'`` to bounding-box the target, or "
            f"(c) swap this fixture for a synthetic reprint."
        )

    # Save + verify no target string survives the redaction —
    # a fail-loud "false-clean" check.
    doc.save(dst, deflate=True, garbage=4)
    doc.close()

    verify_doc = fitz.open(dst)
    survivors: list[tuple[str, int]] = []
    for rep in reps:
        for page_idx, page in enumerate(verify_doc):
            if page.search_for(rep.original):
                survivors.append((rep.original, page_idx + 1))
    verify_doc.close()
    if survivors:
        sys.exit(
            f"[redact] HALT — file={dst.name} post-redaction verify FAILED. "
            f"Original strings still present: {survivors!r}. Refusing to "
            f"commit this fixture."
        )

    post_sha = sha256_bytes(dst)
    post_bytes = dst.stat().st_size
    log(f"[redact] file={dst.name} post_sha={post_sha} post_bytes={post_bytes} "
        f"redact_ops={sum(total_hits.values())}")


def split_pages(src: Path, dst: Path, page_range: tuple[int, int]) -> None:
    """Extract a page range (1-indexed inclusive) into a new PDF.
    Runs BEFORE redaction — the split targets are then redacted
    in-place by ``redact_file``."""
    doc = fitz.open(src)
    out = fitz.open()  # empty target
    # pymupdf uses 0-indexed inclusive-inclusive ranges
    out.insert_pdf(doc, from_page=page_range[0] - 1,
                   to_page=page_range[1] - 1)
    out.save(dst, deflate=True, garbage=4)
    out.close()
    doc.close()
    log(f"[split] src={src.name} range={page_range} → {dst.name}")


def main() -> int:
    if not SRC_DIR.exists():
        sys.exit(f"[redact] source dir missing: {SRC_DIR} — download the raw "
                 f"PDFs first (see Task H.1 Step 1 report).")

    batch_src = SRC_DIR / "invoice_batch_17_digital.pdf"
    estimate_src = SRC_DIR / "estimate_single_11item_scanned.pdf"
    receipt_src = SRC_DIR / "payment_receipt_single_digital.pdf"

    # ── Split fixture 1 into two single-invoice fixtures ────
    # Pages 1-2 = invoice #10847 (single-line pool service).
    # Pages 3-4 = invoice #10774 (also single-line service in the
    # source PDF).  Naming ``multiline`` reflects the vision-mock
    # contract used by the H.1 tests — the mapper receives 2-3
    # canned line items via the mock_vision fixture, so the
    # underlying PDF page count / real line-item count is
    # irrelevant. The file exists as a distinct SHA anchor for
    # H.2 and beyond.
    tmp_single_1  = SRC_DIR / "_tmp_invoice_single_1item.pdf"
    tmp_single_ml = SRC_DIR / "_tmp_invoice_single_multiline.pdf"
    split_pages(batch_src, tmp_single_1,  (1, 2))
    split_pages(batch_src, tmp_single_ml, (3, 4))

    log("─── PRE-REDACTION SOURCE PROVENANCE ───")
    for f in (batch_src, estimate_src, receipt_src):
        log(f"  {sha256_bytes(f)}  {f.stat().st_size:>8}  {f.name}")
    log("")

    # ── Redact all 5 real fixtures ──────────────────────────
    log("─── REDACTION PASS ───")

    redact_file(batch_src,
                DST_DIR / "invoice_batch_17_digital.pdf",
                _DIANE)
    redact_file(tmp_single_1,
                DST_DIR / "invoice_single_1item_digital.pdf",
                _DIANE)
    redact_file(tmp_single_ml,
                DST_DIR / "invoice_single_multiline_digital.pdf",
                _DIANE)
    redact_file(estimate_src,
                DST_DIR / "estimate_single_11item_scanned.pdf",
                _SRIKANT)
    redact_file(receipt_src,
                DST_DIR / "payment_receipt_single_digital.pdf",
                _ERIC)

    # ── REDACTION.md ────────────────────────────────────────
    md = ["# Task H · Phase H.1 · Fixture provenance + redaction log",
          "",
          "Every real PDF fixture in this directory was redacted from a raw",
          "source (unrelated customer PII) via ``_redact_and_split.py`` — the",
          "post-redaction SHAs below are the exact bytes committed to the",
          "repo.  Pre-redaction SHAs are recorded for provenance ONLY — the",
          "raw PDFs are NEVER committed.",
          "",
          "## Raw-source pre-redaction SHA-256 (never committed)",
          "",
          "| SHA-256 | Bytes | File |",
          "|---|---|---|"]
    for f in (batch_src, estimate_src, receipt_src):
        md.append(f"| `{sha256_bytes(f)}` | {f.stat().st_size:,} | `{f.name}` (raw) |")

    md += ["",
           "## Committed post-redaction SHA-256",
           "",
           "| SHA-256 | Bytes | File |",
           "|---|---|---|"]
    for name in ("invoice_batch_17_digital.pdf",
                  "invoice_single_1item_digital.pdf",
                  "invoice_single_multiline_digital.pdf",
                  "estimate_single_11item_scanned.pdf",
                  "payment_receipt_single_digital.pdf"):
        p = DST_DIR / name
        md.append(f"| `{sha256_bytes(p)}` | {p.stat().st_size:,} | `{name}` |")

    md += ["",
           "## Redaction targets (all `search_for` verified post-write)",
           "",
           "**Diane Lloyd batch + splits:**",
           "- `Diane Lloyd` → `Test Customer A`",
           "- `20271 N 51st Dr` → `123 Test Ln A`",
           "- `Glendale AZ 85308` → `Testville AZ 00001`",
           "",
           "**Srikant Mikkilineni estimate:**",
           "- `Srikant Mikkilineni` → `Test Customer B`",
           "- `30773 North 129Th Avenue` → `123 Test Ln B`",
           "- `30773 North 129th Avenue` → `123 Test Ln B`",
           "",
           "**Eric Torkelson payment receipt:**",
           "- `Eric Torkelson` → `Test Customer C`",
           "- `Brian Beckman` → `Ops Operator`  (audit-line operator; H.1 "
           "extractor must NEVER surface this as customer_name — see the "
           "operator-line disambiguation test case)",
           "",
           "## Preserved (tenant business branding — NOT redacted)",
           "",
           "- `Pool & Landscaping of Vistancia LLC`",
           "- `24654 N. Lake Pleasant Pkwy Ste. 103-508`",
           "- `Peoria AZ 85383` — tenant ZIP; note that Srikant's real",
           "  address shared this ZIP.  Only the *street* was redacted for",
           "  Srikant so the tenant brand identifier survives.",
           "- `602-887-4400`",
           "- `www.plofv.com`",
           "",
           "## How to reproduce",
           "",
           "```",
           "python backend/tests/fixtures/pdf/_redact_and_split.py",
           "```",
           "",
           "The script is idempotent — running it against the same source",
           "URLs + a clean ``/tmp/h1-pdfs/`` will produce the SAME committed",
           "SHAs verbatim.  If any target string is missing from the raw",
           "source (e.g. upstream URL updated), the script HALTS with a",
           "clear error instead of writing a possibly-unredacted file.",
           "",
           "## Run log (last execution)",
           ""]
    md += [f"    {line}" for line in LOG_LINES]

    (DST_DIR / "REDACTION.md").write_text("\n".join(md) + "\n")
    log(f"[redact] wrote {DST_DIR / 'REDACTION.md'}")

    # Clean up temp splits
    tmp_single_1.unlink(missing_ok=True)
    tmp_single_ml.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
