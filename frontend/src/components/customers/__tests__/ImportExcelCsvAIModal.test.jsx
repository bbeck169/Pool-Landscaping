/**
 * TD-customer-ai-excel-csv-import · Feb-2026
 * ==========================================
 *
 * Vitest regression lock for the AI-powered customer importer modal.
 *
 * Coverage
 * --------
 * §1 — Mount gating
 *   §1a — open=false renders nothing
 *   §1b — open=true renders the upload prompt + testids
 *
 * §2 — Upload flow
 *   §2a — "Upload & Preview" with no file surfaces an error toast
 *   §2b — happy-path upload renders the preview table with per-row
 *          action dropdowns + mapped-field pairs
 *   §2c — 400 ``row_limit_exceeded`` surfaces a human-readable toast
 *          (NOT the raw JSON detail blob)
 *
 * §3 — Commit flow
 *   §3a — commit payload includes operator-overridden actions
 *          (one row forced from "attach" to "skip") and preserves
 *          the mapped_fields verbatim
 *   §3b — commit result view renders created / attached / skipped /
 *          errored counts
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
    render, screen, fireEvent, waitFor, cleanup, within,
} from "@testing-library/react";


const fetchSpy = vi.fn();

beforeEach(() => {
    globalThis.fetch = fetchSpy;
    fetchSpy.mockReset();
    globalThis.localStorage.setItem("token", "fixture-token");
});

afterEach(() => {
    cleanup();
    globalThis.localStorage.clear();
});


function _mockFetchOnceOk(json) {
    fetchSpy.mockResolvedValueOnce({
        ok: true, status: 200,
        text: async () => JSON.stringify(json),
    });
}

function _mockFetchOnceErr(status, detail) {
    fetchSpy.mockResolvedValueOnce({
        ok: false, status,
        text: async () => JSON.stringify({ detail }),
    });
}


import ImportExcelCsvAIModal
    from "@/components/customers/ImportExcelCsvAIModal";


// ═══════════════════════════════════════════════════════════════════
// §1 — Mount gating
// ═══════════════════════════════════════════════════════════════════
describe("ImportExcelCsvAIModal · mount gating", () => {
    it("open=false renders nothing", () => {
        const { container } = render(
            <ImportExcelCsvAIModal open={false} />,
        );
        expect(container.firstChild).toBeNull();
    });

    it("open=true renders the upload prompt", () => {
        render(<ImportExcelCsvAIModal open={true} />);
        expect(
            screen.getByTestId("import-excel-ai-modal"),
        ).toBeInTheDocument();
        expect(
            screen.getByTestId("import-excel-ai-file-input"),
        ).toBeInTheDocument();
        expect(
            screen.getByTestId("import-excel-ai-upload-submit"),
        ).toBeInTheDocument();
    });
});


// ═══════════════════════════════════════════════════════════════════
// §2 — Upload flow
// ═══════════════════════════════════════════════════════════════════
describe("ImportExcelCsvAIModal · upload", () => {
    it("blocks upload when no file selected (toast error)", () => {
        const toastSpy = vi.fn();
        render(
            <ImportExcelCsvAIModal
                open={true}
                setToast={toastSpy}
            />,
        );
        fireEvent.click(
            screen.getByTestId("import-excel-ai-upload-submit"),
        );
        expect(toastSpy).toHaveBeenCalledWith(expect.objectContaining({
            kind: "error",
            message: expect.stringMatching(/pick an .*file/i),
        }));
        expect(fetchSpy).not.toHaveBeenCalled();
    });

    it("renders the preview table with action dropdowns on 200", async () => {
        _mockFetchOnceOk({
            batch_id: "batch-abc",
            preview: [
                {
                    row_num: 2,
                    raw_cells: { Name: "Alice", Email: "a@x.com" },
                    mapped_fields: {
                        name: "Alice", email: "a@x.com",
                    },
                    match_status: "exact_email",
                    match_candidates: [{
                        customer_id: "cust-1",
                        name: "Alice (existing)",
                        email: "a@x.com",
                        phone: "",
                        match_reason: "exact_email",
                    }],
                    suggested_action: "attach",
                },
                {
                    row_num: 3,
                    raw_cells: { Name: "Bob" },
                    mapped_fields: { name: "Bob" },
                    match_status: "no_match",
                    match_candidates: [],
                    suggested_action: "create",
                },
            ],
            stats: {
                rows_total: 2, rows_create: 1,
                rows_attach: 1, rows_skip: 0, rows_errored: 0,
            },
            headers: ["Name", "Email"],
            ai_providers: { emergent: 2 },
        });

        render(<ImportExcelCsvAIModal open={true} setToast={() => {}} />);
        const file = new File(["x"], "test.csv", { type: "text/csv" });
        const input = screen.getByTestId("import-excel-ai-file-input");
        Object.defineProperty(input, "files", { value: [file] });
        fireEvent.change(input);
        fireEvent.click(
            screen.getByTestId("import-excel-ai-upload-submit"),
        );
        await waitFor(() => {
            expect(
                screen.getByTestId("import-excel-ai-preview-table"),
            ).toBeInTheDocument();
        });
        // Per-row action dropdowns pre-seeded with suggested
        // actions from the preview.
        const row2Action = screen.getByTestId(
            "import-excel-ai-action-2",
        );
        const row3Action = screen.getByTestId(
            "import-excel-ai-action-3",
        );
        expect(row2Action.value).toBe("attach");
        expect(row3Action.value).toBe("create");
        // Match-status labels surface in the match column.
        expect(
            screen.getByTestId("import-excel-ai-match-2").textContent,
        ).toMatch(/email match/i);
        expect(
            screen.getByTestId("import-excel-ai-match-3").textContent,
        ).toMatch(/no match/i);
    });

    it("row_limit_exceeded 400 surfaces human-readable toast",
            async () => {
        _mockFetchOnceErr(400, {
            error: "row_limit_exceeded",
            max_rows: 2000, found_rows: 2001,
        });
        const toastSpy = vi.fn();
        render(
            <ImportExcelCsvAIModal
                open={true} setToast={toastSpy}
            />,
        );
        const file = new File(["x"], "test.csv", { type: "text/csv" });
        const input = screen.getByTestId("import-excel-ai-file-input");
        Object.defineProperty(input, "files", { value: [file] });
        fireEvent.change(input);
        fireEvent.click(
            screen.getByTestId("import-excel-ai-upload-submit"),
        );
        await waitFor(() => {
            expect(toastSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    kind: "error",
                    message: expect.stringMatching(
                        /2000 row limit.*2001 rows found/i,
                    ),
                }),
            );
        });
    });
});


// ═══════════════════════════════════════════════════════════════════
// §3 — Commit flow
// ═══════════════════════════════════════════════════════════════════
describe("ImportExcelCsvAIModal · commit", () => {
    it("commit payload includes operator-overridden actions + "
                + "verbatim mapped_fields",
            async () => {
        _mockFetchOnceOk({
            batch_id: "batch-xyz",
            preview: [
                {
                    row_num: 2,
                    raw_cells: { Email: "foo@x.com" },
                    mapped_fields: { email: "foo@x.com" },
                    match_status: "exact_email",
                    match_candidates: [{
                        customer_id: "cust-fix", name: "Foo",
                        email: "foo@x.com", phone: "",
                        match_reason: "exact_email",
                    }],
                    suggested_action: "attach",
                },
            ],
            stats: {
                rows_total: 1, rows_create: 0, rows_attach: 1,
                rows_skip: 0, rows_errored: 0,
            },
            ai_providers: { emergent: 1 },
        });
        _mockFetchOnceOk({
            created: 0, attached: 0, skipped: 1, errored: 0,
            row_errors: [],
            created_ids: [], attached_ids: [],
        });

        render(<ImportExcelCsvAIModal open={true} setToast={() => {}} />);
        const file = new File(["x"], "test.csv", { type: "text/csv" });
        const input = screen.getByTestId("import-excel-ai-file-input");
        Object.defineProperty(input, "files", { value: [file] });
        fireEvent.change(input);
        fireEvent.click(
            screen.getByTestId("import-excel-ai-upload-submit"),
        );
        await waitFor(() => {
            expect(
                screen.getByTestId("import-excel-ai-preview-table"),
            ).toBeInTheDocument();
        });

        // Operator overrides the suggested "attach" to "skip".
        fireEvent.change(
            screen.getByTestId("import-excel-ai-action-2"),
            { target: { value: "skip" } },
        );
        fireEvent.click(
            screen.getByTestId("import-excel-ai-commit-submit"),
        );
        await waitFor(() => {
            expect(fetchSpy).toHaveBeenCalledTimes(2);
        });
        const [, commitCall] = fetchSpy.mock.calls;
        expect(commitCall[0]).toMatch(
            /\/api\/customers\/import-excel\/commit$/,
        );
        const payload = JSON.parse(commitCall[1].body);
        expect(payload.batch_id).toBe("batch-xyz");
        expect(payload.rows).toHaveLength(1);
        expect(payload.rows[0].row_num).toBe(2);
        expect(payload.rows[0].action).toBe("skip");
        expect(payload.rows[0].mapped_fields)
            .toEqual({ email: "foo@x.com" });
    });

    it("commit result view renders created / attached / "
                + "skipped / errored counts",
            async () => {
        _mockFetchOnceOk({
            batch_id: "batch-r",
            preview: [{
                row_num: 2,
                raw_cells: { Email: "x@y.com" },
                mapped_fields: { email: "x@y.com" },
                match_status: "no_match",
                match_candidates: [],
                suggested_action: "create",
            }],
            stats: {
                rows_total: 1, rows_create: 1,
                rows_attach: 0, rows_skip: 0, rows_errored: 0,
            },
            ai_providers: { emergent: 1 },
        });
        _mockFetchOnceOk({
            created: 1, attached: 2, skipped: 3, errored: 4,
            row_errors: [{ row_num: 7, reason: "insert_failed" }],
            created_ids: [], attached_ids: [],
        });
        render(<ImportExcelCsvAIModal open={true} setToast={() => {}} />);
        const file = new File(["x"], "test.csv", { type: "text/csv" });
        const input = screen.getByTestId("import-excel-ai-file-input");
        Object.defineProperty(input, "files", { value: [file] });
        fireEvent.change(input);
        fireEvent.click(
            screen.getByTestId("import-excel-ai-upload-submit"),
        );
        await waitFor(() => {
            expect(
                screen.getByTestId("import-excel-ai-preview-table"),
            ).toBeInTheDocument();
        });
        fireEvent.click(
            screen.getByTestId("import-excel-ai-commit-submit"),
        );
        await waitFor(() => {
            expect(
                screen.getByTestId("import-excel-ai-result-view"),
            ).toBeInTheDocument();
        });
        expect(
            screen.getByTestId("import-excel-ai-result-created").textContent,
        ).toBe("1");
        expect(
            screen.getByTestId("import-excel-ai-result-attached").textContent,
        ).toBe("2");
        expect(
            screen.getByTestId("import-excel-ai-result-skipped").textContent,
        ).toBe("3");
        expect(
            screen.getByTestId("import-excel-ai-result-errored").textContent,
        ).toBe("4");
    });
});
