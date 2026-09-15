/**
 * Phase KB3 · Feb-2026 · KB file-upload modal (vitest).
 *
 * Coverage:
 *  1. Send button starts disabled; picking a file enables it.
 *  2. Progress bar appears while an upload is in-flight.
 *  3. Truthful toast on mocked upload failure (uses the server's
 *     error message when present).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

const _upload = vi.fn();
vi.mock("@/api/files", () => ({
  uploadKnowledgeFile: (...args) => _upload(...args),
}));

const _toastSuccess = vi.fn();
const _toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...a) => _toastSuccess(...a),
    error: (...a) => _toastError(...a),
  },
}));

// eslint-disable-next-line import/first
import KBFileUploadModal from "../pages/settings/KBFileUploadModal";

beforeEach(() => {
  _upload.mockReset();
  _toastSuccess.mockReset();
  _toastError.mockReset();
});

function fakePdf() {
  return new File(
    [new Uint8Array([0x25, 0x50, 0x44, 0x46])],
    "warranty.pdf",
    { type: "application/pdf" },
  );
}

describe("KBFileUploadModal", () => {
  it("send button stays disabled until a file is picked", () => {
    render(<KBFileUploadModal onClose={() => {}} />);
    const send = screen.getByTestId("kb-file-upload-send");
    expect(send).toBeDisabled();

    const input = screen.getByTestId("kb-file-upload-input");
    fireEvent.change(input, { target: { files: [fakePdf()] } });
    expect(send).not.toBeDisabled();
    // Title auto-fills from the filename.
    expect(screen.getByTestId("kb-file-upload-title").value).toBe("warranty");
  });

  it("shows the progress bar while an upload is in-flight", async () => {
    let resolveUpload;
    _upload.mockImplementation(({ onProgress }) => {
      onProgress?.(35);
      return new Promise((resolve) => { resolveUpload = resolve; });
    });
    render(<KBFileUploadModal onClose={() => {}} />);
    const input = screen.getByTestId("kb-file-upload-input");
    fireEvent.change(input, { target: { files: [fakePdf()] } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("kb-file-upload-send"));
      await Promise.resolve();
    });
    expect(screen.getByTestId("kb-file-upload-progress")).toBeInTheDocument();

    // Resolve the in-flight upload so the promise chain settles.
    await act(async () => {
      resolveUpload({ kb: { title: "warranty" } });
      await Promise.resolve();
    });
  });

  it("surfaces the server error verbatim on upload failure", async () => {
    _upload.mockImplementation(() => Promise.reject(
      Object.assign(new Error("No extractable text was found in the uploaded file."), {
        status: 400,
      }),
    ));
    render(<KBFileUploadModal onClose={() => {}} />);
    const input = screen.getByTestId("kb-file-upload-input");
    fireEvent.change(input, { target: { files: [fakePdf()] } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("kb-file-upload-send"));
      await Promise.resolve();
    });

    expect(_toastError).toHaveBeenCalledWith(
      "No extractable text was found in the uploaded file.",
    );
    expect(_toastSuccess).not.toHaveBeenCalled();
  });
});
