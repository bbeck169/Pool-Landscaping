/**
 * Phase F1 · Feb 2026 — FileUpload component (web).
 *
 * Drag-and-drop OR click-to-browse. Client-side size + MIME gate
 * mirrors the F0 backend (25MB · image/* · video/mp4 · application/pdf)
 * so users see the rejection instantly, not after a wasted upload.
 *
 * Callbacks:
 *   onUploaded(payload)   — one call per successful upload
 *   onError(errObj)         — one call per rejection (client-side OR backend)
 *
 * Props:
 *   purpose, linkedEntityType, linkedEntityId — passed through to
 *                                                  the upload endpoint
 *                                                  as form fields.
 *   accept       — restrict the browse dialog (default: "image/*").
 *   multiple     — allow multi-select; defaults to single-file.
 *   maxFiles     — max queue size in multi-file mode (default 1).
 *   buttonLabel  — override the browse-button copy.
 *   disabled     — locks the whole zone.
 *
 * A11y: label + role=button on the drop-zone; keyboard-navigable
 * browse button; ARIA live region for status messages.
 */
import React, { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { UploadCloud, X, FileText, Video as VideoIcon, Image as ImageIcon } from "lucide-react";
import { uploadFile, deleteFile } from "@/api/files";
import { compressImageIfNeeded } from "../../lib/imageCompress";

const MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024;

function mimeAllowed(ct, accept) {
  const acc = (accept || "").split(",").map((s) => s.trim()).filter(Boolean);
  if (acc.length === 0) return true;
  const type = (ct || "").toLowerCase();
  return acc.some((rule) => {
    if (rule === "*/*") return true;
    if (rule.endsWith("/*")) return type.startsWith(rule.slice(0, -1));
    return type === rule.toLowerCase();
  });
}

function humanBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function iconFor(ct) {
  const type = (ct || "").toLowerCase();
  if (type.startsWith("image/")) return <ImageIcon size={16} />;
  if (type.startsWith("video/")) return <VideoIcon size={16} />;
  if (type === "application/pdf") return <FileText size={16} />;
  return <FileText size={16} />;
}

export function FileUpload({
  purpose,
  linkedEntityType,
  linkedEntityId,
  accept = "image/*",
  multiple = false,
  maxFiles = 1,
  onUploaded,
  onError,
  disabled = false,
  className = "",
  buttonLabel,
}) {
  const inputRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);
  const [items, setItems] = useState([]);   // uploaded queue

  const reject = useCallback((code, message) => {
    const err = { code, message };
    onError?.(err);
    toast.error(message);
  }, [onError]);

  const doUpload = useCallback(async (rawFile) => {
    // Feb 2026 · iOS field-upload timeout fix — shrink modern iPhone
    // photos before they hit the wire. Non-image files + small images
    // pass through unchanged. See `lib/imageCompress.js`.
    const file = await compressImageIfNeeded(rawFile);
    // 1. client-side gates
    if (file.size > MAX_UPLOAD_SIZE_BYTES) {
      reject("FILE_TOO_LARGE",
        `File "${file.name}" is ${humanBytes(file.size)} — max 25 MB.`);
      return;
    }
    if (!mimeAllowed(file.type, accept)) {
      reject("UNSUPPORTED_MIME",
        `File "${file.name}" (${file.type || "unknown"}) is not an allowed type.`);
      return;
    }

    const clientId = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setItems((prev) => [
      ...prev,
      { clientId, filename: file.name, size: file.size,
         content_type: file.type, progress: 0, uploading: true },
    ]);

    try {
      const payload = await uploadFile({
        file,
        purpose,
        linkedEntityType,
        linkedEntityId,
        onProgress: (p) => setItems((prev) =>
          prev.map((it) => (it.clientId === clientId ? { ...it, progress: p } : it))),
      });
      setItems((prev) => prev.map((it) => (
        it.clientId === clientId
          ? { ...it, ...payload, uploading: false, progress: 100 }
          : it
      )));
      onUploaded?.(payload);
    } catch (e) {
      setItems((prev) => prev.filter((it) => it.clientId !== clientId));
      reject(e?.status ? String(e.status) : "UPLOAD_FAILED",
        e?.message || "Upload failed.");
    }
  }, [accept, purpose, linkedEntityType, linkedEntityId,
       reject, onUploaded]);

  const openBrowse = () => {
    if (disabled || items.length >= maxFiles) return;
    inputRef.current?.click();
  };

  const handleFiles = useCallback((list) => {
    const arr = Array.from(list || []);
    const room = Math.max(0, maxFiles - items.length);
    const toTake = multiple ? arr.slice(0, room) : arr.slice(0, 1);
    if (!toTake.length && arr.length) {
      reject("QUEUE_FULL", `Max ${maxFiles} file(s) allowed.`);
      return;
    }
    for (const f of toTake) doUpload(f);
  }, [multiple, maxFiles, items.length, doUpload, reject]);

  const onDrop = (e) => {
    e.preventDefault(); e.stopPropagation();
    setDragOver(false);
    if (disabled) return;
    handleFiles(e.dataTransfer?.files);
  };

  const removeItem = async (it) => {
    if (it.id) {
      try { await deleteFile(it.id); } catch { /* toast handled via caller */ }
    }
    setItems((prev) => prev.filter((x) => x.clientId !== it.clientId));
  };

  const zoneClasses = useMemo(() => {
    const base = "rounded-2xl border-2 border-dashed p-6 text-center transition cursor-pointer";
    const state = dragOver
      ? "border-blue-500 bg-blue-50"
      : "border-zinc-300 bg-zinc-50 hover:border-zinc-400";
    const dis = disabled ? "opacity-50 pointer-events-none" : "";
    return [base, state, dis, className].filter(Boolean).join(" ");
  }, [dragOver, disabled, className]);

  return (
    <div data-testid="file-upload-root">
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label="Upload file — drop here or click to browse"
        aria-disabled={disabled ? "true" : "false"}
        onClick={openBrowse}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openBrowse(); }
        }}
        onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={zoneClasses}
        data-testid="file-upload-dropzone"
      >
        <UploadCloud className="mx-auto mb-2" size={28} />
        <div className="text-sm font-medium">
          {buttonLabel || "Drop a file here — or click to browse"}
        </div>
        <div className="text-xs text-zinc-500 mt-1">
          Images, MP4 video, or PDF · up to 25 MB
        </div>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          onChange={(e) => handleFiles(e.target.files)}
          data-testid="file-upload-input"
        />
      </div>

      {items.length > 0 && (
        <ul className="mt-3 space-y-2" aria-live="polite">
          {items.map((it) => (
            <li key={it.clientId}
                className="rounded-xl border border-zinc-200 bg-white p-3 flex items-center gap-3"
                data-testid={`file-upload-item-${it.clientId}`}>
              <div className="shrink-0" aria-hidden="true">{iconFor(it.content_type)}</div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{it.original_filename || it.filename}</div>
                <div className="text-xs text-zinc-500">
                  {humanBytes(it.size || 0)} · {it.content_type || "unknown"}
                  {it.uploading && ` · ${it.progress}%`}
                </div>
                {it.uploading && (
                  <div className="w-full bg-zinc-100 rounded-full h-1.5 mt-1">
                    <div className="bg-blue-500 h-1.5 rounded-full transition-all"
                          style={{ width: `${it.progress}%` }} />
                  </div>
                )}
              </div>
              <button
                onClick={() => removeItem(it)}
                aria-label={`Remove ${it.original_filename || it.filename}`}
                data-testid={`file-upload-remove-${it.clientId}`}
                className="p-1 rounded-lg hover:bg-zinc-100">
                <X size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default FileUpload;
