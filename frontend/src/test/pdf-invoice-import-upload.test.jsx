/**
 * Task B · Phase 2 · Commit 2 — PdfInvoiceImportPage upload flow.
 *
 * Locks the upload contract for the multi-file selection surface:
 *
 *   1. Pure validation utilities are correct — 20-cap enforcement,
 *      10 MB per-file rejection, soft-warn threshold at 10 files.
 *   2. Typed-error mapping is correct — 413 pdf_too_large / 415
 *      pdf_only / 429 rate-limited / 401 / 403 / 400 pdf_parse_failed
 *      all resolve to user-friendly copy.
 *   3. Kickoff POST hits the correct endpoint with a FormData body
 *      carrying the ``file`` field, an Authorization header from
 *      localStorage, and NO forced Content-Type (multipart boundary
 *      must be browser-generated).
 *   4. Component-level idle → queued → uploading → processing flow
 *      is driven by the hidden <input> onChange handler.
 *   5. Concurrency pool cap (2 slots) is respected — 5 selected
 *      files result in ≤2 UPLOADING rows and the rest sit QUEUED
 *      until slots free.
 *   6. Toast surface matches the Phase 2 ruling copy exactly
 *      (max 20 / soft-warn at 10 / individual over-10-MB rejects).
 */
import React from "react";
import {
  render,
  screen,
  fireEvent,
  act,
  waitFor,
} from "@testing-library/react";
import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach,
} from "vitest";
import { toast } from "sonner";

// Mock sonner BEFORE the page import so the component picks up
// the stub.  Test setup already resets vi.clearAllMocks in
// afterEach so we don't need explicit reset here.
vi.mock("sonner", () => ({
  toast: {
    error:   vi.fn(),
    warning: vi.fn(),
    info:    vi.fn(),
    success: vi.fn(),
  },
}));

import PdfInvoiceImportPage, {
  MAX_FILES_PER_BATCH,
  MAX_BYTES_PER_FILE,
  SOFT_WARN_FILES,
  CONCURRENCY_POOL,
  FILE_STATUS,
  validateSelection,
  formatBytes,
  messageForUploadError,
  postPdfInvoice,
} from "@/pages/admin/imports/PdfInvoiceImportPage";


// ── Helpers ────────────────────────────────────────────────────
function makePdf(name, sizeBytes) {
  // File constructor with a fake body — JSDOM exposes real File
  // + FormData APIs so this works without polyfills.
  const blob = new Blob([new Uint8Array(1)], { type: "application/pdf" });
  const f = new File([blob], name, { type: "application/pdf" });
  // Bypass the browser's derived size and inject the caller-
  // supplied byte count so we can drive the size-cap edge case
  // without allocating 10+ MB in RAM.
  Object.defineProperty(f, "size", { value: sizeBytes });
  return f;
}

function fireFileSelect(input, files) {
  // FileList is not directly constructible; DataTransfer
  // synthesises one for us in JSDOM.  Fallback to defineProperty
  // where the older jsdom releases don't support DataTransfer.
  let list;
  try {
    const dt = new DataTransfer();
    for (const f of files) dt.items.add(f);
    list = dt.files;
  } catch {
    list = Object.assign(files, {
      item: (i) => files[i],
      length: files.length,
    });
  }
  fireEvent.change(input, { target: { files: list } });
}


beforeEach(() => {
  vi.spyOn(window, "fetch").mockImplementation(async (url) => {
    // Default happy-path response (each vitest can override with
    // a per-test spy) — 202 + a fake batch_id.
    return new Response(
      JSON.stringify({
        batch_id: `mock-batch-${Math.random().toString(36).slice(2, 10)}`,
        status: "queued",
        poll_hint_seconds: 5,
        poll_url: `/api/imports/pdf-invoice/mock-batch`,
        async: true,
      }),
      { status: 202, headers: { "Content-Type": "application/json" } },
    );
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});


// ── Pure validation utilities ──────────────────────────────────

describe("validateSelection · pure caps enforcement", () => {
  it("rejects the whole selection when count > MAX_FILES_PER_BATCH", () => {
    const files = Array.from(
      { length: MAX_FILES_PER_BATCH + 1 },
      (_, i) => makePdf(`f${i}.pdf`, 100),
    );
    const out = validateSelection(files);
    expect(out.accepted).toHaveLength(0);
    expect(out.rejectedForCount).toHaveLength(MAX_FILES_PER_BATCH + 1);
    expect(out.shouldSoftWarn).toBe(false);
  });

  it("accepts a selection at exactly MAX_FILES_PER_BATCH", () => {
    const files = Array.from(
      { length: MAX_FILES_PER_BATCH },
      (_, i) => makePdf(`f${i}.pdf`, 100),
    );
    const out = validateSelection(files);
    expect(out.accepted).toHaveLength(MAX_FILES_PER_BATCH);
    expect(out.rejectedForCount).toHaveLength(0);
    expect(out.shouldSoftWarn).toBe(true);
  });

  it("triggers the soft-warn threshold at exactly " +
     "SOFT_WARN_FILES", () => {
    const files = Array.from(
      { length: SOFT_WARN_FILES },
      (_, i) => makePdf(`f${i}.pdf`, 100),
    );
    const out = validateSelection(files);
    expect(out.shouldSoftWarn).toBe(true);
    expect(out.accepted).toHaveLength(SOFT_WARN_FILES);
  });

  it("splits oversized files (> 10 MB) out of accepted", () => {
    const files = [
      makePdf("small.pdf", 1024 * 1024),                       //  1 MB
      makePdf("big.pdf",   MAX_BYTES_PER_FILE + 1),            // 10 MB + 1 B
      makePdf("medium.pdf", 5 * 1024 * 1024),                  //  5 MB
    ];
    const out = validateSelection(files);
    expect(out.accepted.map((f) => f.name))
      .toEqual(["small.pdf", "medium.pdf"]);
    expect(out.oversized.map((f) => f.name)).toEqual(["big.pdf"]);
  });

  it("accepts a file at exactly MAX_BYTES_PER_FILE (boundary)", () => {
    const files = [makePdf("exactly-10mb.pdf", MAX_BYTES_PER_FILE)];
    const out = validateSelection(files);
    expect(out.accepted).toHaveLength(1);
    expect(out.oversized).toHaveLength(0);
  });
});


describe("formatBytes · byte formatter", () => {
  it.each([
    [0, "0 B"],
    [512, "512 B"],
    [1024, "1.0 KB"],
    [1024 * 1024, "1.0 MB"],
    [12 * 1024 * 1024, "12.0 MB"],
    [MAX_BYTES_PER_FILE + 1, "10.0 MB"],
  ])("formats %s bytes → %s", (bytes, expected) => {
    expect(formatBytes(bytes)).toBe(expected);
  });
});


describe("messageForUploadError · typed-error → user copy", () => {
  it.each([
    [413, { error: "pdf_too_large" }, /10 MB size cap/],
    [415, { error: "pdf_only" },      /Only PDF files/],
    [400, { error: "pdf_parse_failed" }, /re-saving as a flat PDF/],
    [429, {},                         /Too many uploads/],
    [401, {},                         /Session expired/],
    [403, {},                         /do not have permission/],
    [500, {},                         /Upload failed \(500\)/],
    [null, null,                      /Upload failed \(network\)/],
  ])("status %s → matches copy pattern", (status, detail, pattern) => {
    expect(messageForUploadError(status, detail)).toMatch(pattern);
  });
});


describe("postPdfInvoice · kickoff POST wire-format", () => {
  it("POSTs to /api/imports/pdf-invoice with multipart FormData " +
     "and Bearer token, no forced Content-Type", async () => {
    const fetchSpy = vi.spyOn(window, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({ batch_id: "abc", status: "queued" }),
        { status: 202 },
      ),
    );
    const file = makePdf("supplier.pdf", 2048);
    const envelope = await postPdfInvoice(file, {
      baseUrl: "https://api.example.com",
      token: "test-jwt",
    });
    expect(envelope.batch_id).toBe("abc");
    // Assert the fetch call.
    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toBe("https://api.example.com/api/imports/pdf-invoice");
    expect(opts.method).toBe("POST");
    // Auth header on, Content-Type OFF.
    expect(opts.headers.Authorization).toBe("Bearer test-jwt");
    expect(opts.headers["Content-Type"]).toBeUndefined();
    // Body is a FormData carrying the file field.
    expect(opts.body).toBeInstanceOf(FormData);
    expect(opts.body.get("file")).toBeInstanceOf(File);
    expect(opts.body.get("file").name).toBe("supplier.pdf");
  });

  it("throws an Error carrying the translated typed-error copy " +
     "on 413", async () => {
    vi.spyOn(window, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: { error: "pdf_too_large" } }),
        { status: 413 },
      ),
    );
    const file = makePdf("big.pdf", 2048);
    await expect(postPdfInvoice(file, {
      baseUrl: "https://api.example.com", token: "test-jwt",
    })).rejects.toThrow(/10 MB size cap/);
  });

  it("unwraps the FastAPI outer ``detail`` field before running " +
     "the typed-error mapper (400 pdf_parse_failed happy path)", async () => {
    // FastAPI wraps HTTPException(detail=X) as {\"detail\": X} on
    // the wire.  postPdfInvoice must unwrap the outer layer so
    // the mapper sees the nested typed error, not the wrapper.
    vi.spyOn(window, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: { error: "pdf_parse_failed",
                                    message: "PyMuPDF failed" } }),
        { status: 400 },
      ),
    );
    const file = makePdf("scrambled.pdf", 4);
    await expect(postPdfInvoice(file, {
      baseUrl: "https://api.example.com", token: "test-jwt",
    })).rejects.toThrow(/re-saving as a flat PDF/);
  });
});


// ── Component behaviour ────────────────────────────────────────

describe("PdfInvoiceImportPage · file-select handler", () => {
  it("rejects an over-count selection with a toast and keeps " +
     "the files list empty", async () => {
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    const files = Array.from(
      { length: MAX_FILES_PER_BATCH + 1 },
      (_, i) => makePdf(`f${i}.pdf`, 100),
    );
    await act(async () => {
      fireFileSelect(input, files);
    });
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringMatching(/Max 20 PDFs per batch/),
    );
    // No files list rendered — hasFiles === false.
    expect(
      screen.queryByTestId("pdf-import-files-list"),
    ).toBeNull();
  });

  it("rejects oversized files with a per-file toast but accepts " +
     "the small ones", async () => {
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    const files = [
      makePdf("small.pdf",  1024),
      makePdf("big.pdf",    MAX_BYTES_PER_FILE + 1),
    ];
    await act(async () => {
      fireFileSelect(input, files);
    });
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringMatching(/^big\.pdf is [\d.]+ MB — max 10 MB per PDF\./),
    );
    // Only 'small.pdf' should reach the queue.
    await waitFor(() => {
      const list = screen.getByTestId("pdf-import-files-list");
      expect(list.textContent).toMatch(/small\.pdf/);
      expect(list.textContent).not.toMatch(/big\.pdf/);
    });
  });

  it("fires the soft-warn toast when the accepted count " +
     "reaches SOFT_WARN_FILES", async () => {
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    const files = Array.from(
      { length: SOFT_WARN_FILES },
      (_, i) => makePdf(`f${i}.pdf`, 1024),
    );
    await act(async () => {
      fireFileSelect(input, files);
    });
    expect(toast.warning).toHaveBeenCalledWith(
      expect.stringMatching(
        `Uploading ${SOFT_WARN_FILES} files — this may take a few minutes.`,
      ),
    );
  });

  it("respects the CONCURRENCY_POOL cap — at most 2 rows sit in " +
     "UPLOADING while the rest wait as QUEUED", async () => {
    // Stall every fetch so all POSTs stay in-flight — we're
    // testing the pool cap, not resolution behaviour.
    let releaseAll;
    const pending = new Promise((resolve) => { releaseAll = resolve; });
    vi.spyOn(window, "fetch").mockImplementation(() => pending);

    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    const files = Array.from(
      { length: 5 },
      (_, i) => makePdf(`f${i}.pdf`, 1024),
    );
    await act(async () => {
      fireFileSelect(input, files);
    });
    // Give the pump a microtask beat.
    await act(async () => { await Promise.resolve(); });

    // Read the status pills off the DOM.  Two UPLOADING, three
    // QUEUED — the exact IDs are opaque so we just count.
    const rows = screen.getAllByTestId(
      /^pdf-import-file-row-/,
    );
    expect(rows).toHaveLength(5);
    const statuses = rows.map((r) => r.getAttribute("data-status"));
    const uploading = statuses.filter((s) => s === FILE_STATUS.UPLOADING);
    const queued    = statuses.filter((s) => s === FILE_STATUS.QUEUED);
    expect(uploading.length).toBe(CONCURRENCY_POOL);
    expect(queued.length).toBe(5 - CONCURRENCY_POOL);

    // Release the fetches so the pool drains and any subsequent
    // pump-microtask completes before the test tears down.
    releaseAll(new Response(
      JSON.stringify({ batch_id: "done", status: "queued" }),
      { status: 202 },
    ));
  });

  it("flips a file row to PROCESSING with the returned batch_id " +
     "on a 202 kickoff", async () => {
    vi.spyOn(window, "fetch").mockResolvedValue(new Response(
      JSON.stringify({
        batch_id: "returned-batch-42",
        status: "queued",
        poll_hint_seconds: 5,
      }),
      { status: 202 },
    ));
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("ok.pdf", 4096)]);
    });
    await waitFor(() => {
      const rows = screen.getAllByTestId(/^pdf-import-file-row-/);
      expect(rows).toHaveLength(1);
      expect(rows[0].getAttribute("data-status"))
        .toBe(FILE_STATUS.PROCESSING);
    });
  });

  it("flips a file row to ERROR with translated typed-error copy " +
     "on a 413 rejection from the backend", async () => {
    vi.spyOn(window, "fetch").mockResolvedValue(new Response(
      JSON.stringify({ detail: { error: "pdf_too_large" } }),
      { status: 413 },
    ));
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("racey.pdf", 4096)]);
    });
    await waitFor(() => {
      const rows = screen.getAllByTestId(/^pdf-import-file-row-/);
      expect(rows).toHaveLength(1);
      expect(rows[0].getAttribute("data-status"))
        .toBe(FILE_STATUS.ERROR);
      expect(rows[0].textContent).toMatch(/10 MB size cap/);
    });
  });
});
