// Phase KB3 · Feb-2026 — Knowledge Base file-ingestion modal.
//
// Admin-only wrapper around ``POST /api/ai/knowledge/file``. Accepts
// PDF / DOCX / TXT / MD, uploads through the shared
// ``/api/files``-style S3 pipeline, and lets the backend do
// text extraction + KB row insertion in a single call.
//
// UX shape:
//   * File picker (accept="*.pdf,*.docx,*.txt,*.md")
//   * Optional title override
//   * Kind dropdown (matches KIND_OPTIONS in AIBrainPage)
//   * Tags CSV
//   * Progress bar during XHR upload
//   * Truthful toast on success / failure (per the P0.5 pattern)
import React, { useState, useRef } from "react";
import { toast } from "sonner";
import { UploadCloud, X } from "lucide-react";
import { uploadKnowledgeFile } from "@/api/files";

const KIND_OPTIONS = [
  { key: "company_profile", label: "Company profile" },
  { key: "faq",             label: "FAQ" },
  { key: "policy",          label: "Policy" },
  { key: "custom",          label: "Custom" },
];
const ACCEPT = ".pdf,.docx,.txt,.md";

export default function KBFileUploadModal({ onClose, onUploaded }) {
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("custom");
  const [tags, setTags] = useState("");
  const [progress, setProgress] = useState(0);
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef(null);

  const canSubmit = !!file && !busy;

  const submit = async () => {
    setBusy(true);
    setProgress(0);
    try {
      const res = await uploadKnowledgeFile({
        file, title, kind, tags,
        onProgress: (pct) => setProgress(pct),
      });
      toast.success("Knowledge file ingested", {
        description: res?.kb?.title
          ? `Added: ${res.kb.title}`
          : "Ready for retrieval.",
      });
      onUploaded?.(res);
      onClose?.();
    } catch (e) {
      // Truthful — surface the actual server message (e.g.
      // "No extractable text was found" for a scanned PDF).
      toast.error(e?.message || "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      data-testid="kb-file-upload-modal"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-lg max-w-lg w-full p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold">Upload knowledge file</h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700"
            aria-label="Close upload modal"
            data-testid="kb-file-upload-close"
          >
            <X size={18} />
          </button>
        </div>

        <div
          className="mb-3 rounded border-2 border-dashed border-slate-300 p-4 text-center cursor-pointer hover:bg-slate-50"
          onClick={() => fileInputRef.current?.click()}
          data-testid="kb-file-upload-dropzone"
        >
          <UploadCloud size={22} className="inline mb-1 text-slate-500" />
          <div className="text-sm text-slate-700">
            {file ? (
              <span className="font-medium">{file.name}</span>
            ) : (
              <>Click to choose a PDF, DOCX, TXT, or MD file</>
            )}
          </div>
          <div className="text-[11px] text-slate-500 mt-1">
            Max 25 MB · scanned PDFs must be OCR'd first
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0] || null;
              setFile(f);
              if (f && !title) {
                // Auto-suggest title from filename (backend does the
                // same fallback, but showing it here lets the admin
                // edit before submit).
                const dot = f.name.lastIndexOf(".");
                setTitle(dot > 0 ? f.name.slice(0, dot) : f.name);
              }
            }}
            data-testid="kb-file-upload-input"
          />
        </div>

        <div className="mb-2">
          <label className="text-xs font-medium text-slate-600">Title (optional)</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            placeholder="Defaults to the filename"
            className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5 text-sm"
            data-testid="kb-file-upload-title"
          />
        </div>

        <div className="mb-2 grid grid-cols-2 gap-2">
          <div>
            <label className="text-xs font-medium text-slate-600">Kind</label>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5 text-sm"
              data-testid="kb-file-upload-kind"
            >
              {KIND_OPTIONS.map((k) => (
                <option key={k.key} value={k.key}>{k.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-slate-600">Tags (CSV)</label>
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="warranty, pump"
              className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5 text-sm"
              data-testid="kb-file-upload-tags"
            />
          </div>
        </div>

        {busy && (
          <div
            className="mt-3 w-full h-2 bg-slate-100 rounded overflow-hidden"
            data-testid="kb-file-upload-progress"
          >
            <div
              className="h-full bg-sky-600 transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded border border-slate-300 text-sm"
            data-testid="kb-file-upload-cancel"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={!canSubmit}
            className="px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-700 text-white text-sm disabled:opacity-50"
            data-testid="kb-file-upload-send"
          >
            {busy ? `Uploading…${progress ? ` ${progress}%` : ""}` : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
