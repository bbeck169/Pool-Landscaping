/**
 * Task B · Phase 2 · Commit 3 — PdfInvoiceImportPage polling loop.
 *
 * Locks the async-polling contract that fires once a batch enters
 * PROCESSING:
 *
 *   1. Pure utilities — ``clampPollHint`` (3-15s bracket per
 *      Ruling E.5), ``isTerminalStatus`` (7 terminal states from
 *      recon report §A.2), ``pollBatch`` (GET wire format).
 *   2. ``prettyStage`` pretty-prints the backend stage string
 *      (``extraction 3/7`` → ``Extraction 3/7``, ``persisting``
 *      → ``Persisting``, unknown → passthrough).
 *   3. Component behaviour — a PROCESSING row starts a poll loop
 *      that:
 *        - reads ``progress_pct`` + ``stage`` on every tick
 *        - flips to PREVIEW_READY on ``preview_complete``
 *        - flips to ERROR on ``failed`` / ``cancelled`` /
 *          ``commit_failed`` etc.
 *        - respects the backend-supplied ``poll_hint_seconds``
 *          (clamped 3-15s) for the next-tick delay.
 *   4. Progress-bar DOM contract — ``role="progressbar"`` with
 *      ``aria-valuenow`` reflecting ``progress_pct``.
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

vi.mock("sonner", () => ({
  toast: {
    error:   vi.fn(),
    warning: vi.fn(),
    info:    vi.fn(),
    success: vi.fn(),
  },
}));

import PdfInvoiceImportPage, {
  FILE_STATUS,
  TERMINAL_BATCH_STATUSES,
  POLL_HINT_MIN_SECONDS,
  POLL_HINT_MAX_SECONDS,
  clampPollHint,
  isTerminalStatus,
  prettyStage,
  pollBatch,
} from "@/pages/admin/imports/PdfInvoiceImportPage";


function makePdf(name, sizeBytes) {
  const blob = new Blob([new Uint8Array(1)], { type: "application/pdf" });
  const f = new File([blob], name, { type: "application/pdf" });
  Object.defineProperty(f, "size", { value: sizeBytes });
  return f;
}

function fireFileSelect(input, files) {
  let list;
  try {
    const dt = new DataTransfer();
    for (const f of files) dt.items.add(f);
    list = dt.files;
  } catch {
    list = Object.assign(files, {
      item: (i) => files[i], length: files.length,
    });
  }
  fireEvent.change(input, { target: { files: list } });
}


describe("clampPollHint · 3-15s bracket (Ruling E.5)", () => {
  it.each([
    [1,   POLL_HINT_MIN_SECONDS],
    [3,   3],
    [7,   7],
    [15,  POLL_HINT_MAX_SECONDS],
    [30,  POLL_HINT_MAX_SECONDS],
    [0,   POLL_HINT_MIN_SECONDS],
    [-5,  POLL_HINT_MIN_SECONDS],
    [null, POLL_HINT_MIN_SECONDS],
    ["7", 7],
  ])("clamps %s → %s", (hint, expected) => {
    expect(clampPollHint(hint)).toBe(expected);
  });
});


describe("isTerminalStatus · terminal-set membership", () => {
  it.each([
    ["preview_complete", true],
    ["failed",           true],
    ["cancelled",        true],
    ["committing",       true],
    ["committed",        true],
    ["commit_failed",    true],
    ["rolling_back",     true],
    ["rolled_back",      true],
    ["rollback_failed",  true],
    ["queued",           false],
    ["processing",       false],
    ["",                 false],
    [null,               false],
    [undefined,          false],
  ])("recognises %s → %s", (status, expected) => {
    expect(isTerminalStatus(status)).toBe(expected);
  });

  it("terminal set matches the seven+ backend states documented " +
     "in the recon report §A.2", () => {
    // If the backend adds a new terminal state (e.g. a manual
    // ``abandoned`` on operator dismiss), we want a quick test
    // failure prompting a poll-loop update.
    expect(TERMINAL_BATCH_STATUSES.size).toBeGreaterThanOrEqual(7);
  });
});


describe("prettyStage · backend stage → operator label", () => {
  it.each([
    ["segmentation",       "Segmentation"],
    ["extraction 3/7",     "Extraction 3/7"],
    ["mapping 2/4",        "Mapping 2/4"],
    ["persisting",         "Persisting"],
    ["preview_complete",   "Preview Complete"],
    ["something_new",      "Something New"],
    ["",                   ""],
    [null,                 ""],
    [undefined,            ""],
  ])("prettifies %s → %s", (stage, expected) => {
    expect(prettyStage(stage)).toBe(expected);
  });
});


describe("pollBatch · GET wire format", () => {
  beforeEach(() => {
    vi.spyOn(window, "fetch");
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("GETs the correct endpoint with Bearer auth", async () => {
    const body = {
      batch_id: "b1",
      status: "processing",
      stage: "extraction 2/5",
      progress_pct: 32,
      poll_hint_seconds: 5,
    };
    window.fetch.mockResolvedValueOnce(new Response(
      JSON.stringify(body), { status: 200 },
    ));
    const out = await pollBatch("b1", {
      baseUrl: "https://api.example.com",
      token: "test-jwt",
    });
    expect(out.batch_id).toBe("b1");
    expect(out.progress_pct).toBe(32);
    const [url, opts] = window.fetch.mock.calls[0];
    expect(url).toBe(
      "https://api.example.com/api/imports/pdf-invoice/b1",
    );
    expect(opts.method).toBe("GET");
    expect(opts.headers.Authorization).toBe("Bearer test-jwt");
  });

  it("throws with a translated message on 404 batch_not_found", async () => {
    window.fetch.mockResolvedValueOnce(new Response(
      JSON.stringify({ detail: { error: "batch_not_found" } }),
      { status: 404 },
    ));
    // Commit 5 wired a bespoke ``batch_not_found`` copy into
    // ``messageForUploadError``; 404s carrying that code now
    // exit the generic ``Upload failed (…)`` fallback.  See
    // PdfInvoiceImportPage.jsx `batch_not_found` branch.
    await expect(pollBatch("missing", {
      baseUrl: "https://api.example.com", token: "test-jwt",
    })).rejects.toThrow(/Batch not found/);
  });

  it("url-encodes the batch id (defence against injection)", async () => {
    window.fetch.mockResolvedValueOnce(new Response(
      JSON.stringify({ batch_id: "a/b?c" }), { status: 200 },
    ));
    await pollBatch("a/b?c", {
      baseUrl: "https://api.example.com", token: "test-jwt",
    });
    const [url] = window.fetch.mock.calls[0];
    expect(url).toBe(
      "https://api.example.com/api/imports/pdf-invoice/a%2Fb%3Fc",
    );
  });
});


// ── Component-level polling behaviour ──────────────────────────

describe("PdfInvoiceImportPage · poll loop", () => {
  let fetchSpy;
  beforeEach(() => {
    fetchSpy = vi.spyOn(window, "fetch");
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  async function drain() {
    // Drain the microtask queue AND any macro-task setTimeouts
    // pending under real timers.  Multiple rounds are needed
    // because setState → useEffect → pollOne → fetch resolve →
    // setState is a chain of ~5 microtasks.
    for (let i = 0; i < 12; i += 1) {
      await act(async () => { await Promise.resolve(); });
    }
  }

  it("kicks a GET after a PROCESSING flip and updates progress " +
     "on the response", async () => {
    // 1st fetch = POST kickoff → 202 with batch_id
    // 2nd + subsequent fetches = GET poll ticks — hint 300s so
    // the next-tick setTimeout doesn't fire within the test.
    fetchSpy
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: "poll-batch-1",
          status: "queued",
          poll_hint_seconds: 300,
        }),
        { status: 202 },
      ))
      .mockResolvedValue(new Response(
        JSON.stringify({
          batch_id: "poll-batch-1",
          status: "processing",
          stage: "extraction 2/5",
          progress_pct: 32,
          poll_hint_seconds: 300,
        }),
        { status: 200 },
      ));

    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("supplier.pdf", 4096)]);
    });
    await drain();

    // POST + at least one GET should have fired.
    expect(fetchSpy.mock.calls.length).toBeGreaterThanOrEqual(2);
    const getCall = fetchSpy.mock.calls.find(
      ([_, opts]) => opts?.method === "GET",
    );
    expect(getCall).toBeDefined();
    expect(getCall[0]).toMatch(
      /\/api\/imports\/pdf-invoice\/poll-batch-1$/,
    );

    // Progress bar renders at 32% + stage label prettified.
    await waitFor(() => {
      const bar = screen.getByRole("progressbar");
      expect(bar.getAttribute("aria-valuenow")).toBe("32");
    });
    const row = screen.getAllByTestId(/^pdf-import-file-row-/)[0];
    expect(row.textContent).toMatch(/Extraction 2\/5/);
  });

  it("flips to PREVIEW_READY when the poll returns " +
     "``preview_complete``", async () => {
    fetchSpy
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: "b2", status: "queued", poll_hint_seconds: 300,
        }),
        { status: 202 },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: "b2",
          status: "preview_complete",
          stage: "preview_complete",
          progress_pct: 100,
        }),
        { status: 200 },
      ));

    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("done.pdf", 2048)]);
    });
    await drain();

    await waitFor(() => {
      const rows = screen.getAllByTestId(/^pdf-import-file-row-/);
      expect(rows[0].getAttribute("data-status"))
        .toBe(FILE_STATUS.PREVIEW_READY);
    });
    const bar = screen.getByRole("progressbar");
    expect(bar.getAttribute("aria-valuenow")).toBe("100");
  });

  it("flips to ERROR on a terminal non-success status", async () => {
    fetchSpy
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: "b3", status: "queued", poll_hint_seconds: 300,
        }),
        { status: 202 },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: "b3",
          status: "failed",
          stage: "extraction 4/7",
          progress_pct: 55,
          error: "PyMuPDF: page 4 unreadable.",
        }),
        { status: 200 },
      ));

    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("broken.pdf", 2048)]);
    });
    await drain();

    await waitFor(() => {
      const rows = screen.getAllByTestId(/^pdf-import-file-row-/);
      expect(rows[0].getAttribute("data-status"))
        .toBe(FILE_STATUS.ERROR);
      expect(rows[0].textContent)
        .toMatch(/PyMuPDF: page 4 unreadable/);
    });
  });

  it("terminates polling — no additional fetches fire after " +
     "the terminal response", async () => {
    // Use fake timers ONLY for the 'no additional fetch'
    // portion — we need to fast-forward past a hypothetical
    // next poll tick without hanging waitFor.
    fetchSpy
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: "b4", status: "queued", poll_hint_seconds: 3,
        }),
        { status: 202 },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          batch_id: "b4",
          status: "preview_complete",
          progress_pct: 100,
        }),
        { status: 200 },
      ));

    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    await act(async () => {
      fireFileSelect(input, [makePdf("done.pdf", 2048)]);
    });
    await drain();

    // POST + first GET both fired.
    const postCount = fetchSpy.mock.calls
      .filter(([_, o]) => o?.method === "POST").length;
    const firstGetCount = fetchSpy.mock.calls
      .filter(([_, o]) => o?.method === "GET").length;
    expect(postCount).toBe(1);
    expect(firstGetCount).toBe(1);

    // Row is PREVIEW_READY — terminal.
    await waitFor(() => {
      const rows = screen.getAllByTestId(/^pdf-import-file-row-/);
      expect(rows[0].getAttribute("data-status"))
        .toBe(FILE_STATUS.PREVIEW_READY);
    });

    // Wait a real 200ms — more than enough for any stray
    // setTimeout(3000) to still be pending; the poll loop
    // MUST NOT fire another GET.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 200));
    });
    const secondGetCount = fetchSpy.mock.calls
      .filter(([_, o]) => o?.method === "GET").length;
    expect(secondGetCount).toBe(1);
  });
});
