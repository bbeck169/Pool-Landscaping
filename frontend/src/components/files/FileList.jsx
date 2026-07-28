/**
 * Phase F1 · Feb 2026 — FileList component (web).
 *
 * Lists files linked to an entity (type + id). Refetches on delete.
 */
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { FileText, Video as VideoIcon, Trash2, ImageIcon } from "lucide-react";
import { listFilesByEntity, deleteFile } from "@/api/files";
import { AuthedImage } from "@/components/files/AuthedImage";

function humanBytes(n) {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function isImage(ct) { return (ct || "").toLowerCase().startsWith("image/"); }

function iconFor(ct) {
  const type = (ct || "").toLowerCase();
  if (type.startsWith("image/")) return <ImageIcon size={20} />;
  if (type.startsWith("video/")) return <VideoIcon size={20} />;
  return <FileText size={20} />;
}

export function FileList({
  linkedEntityType, linkedEntityId, canDelete = false, onChange,
  className = "",
}) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState(null);

  const reload = useCallback(async () => {
    setErr(null);
    try {
      const items = await listFilesByEntity(linkedEntityType, linkedEntityId);
      setRows(items);
      onChange?.(items);
    } catch (e) {
      setRows([]);
      setErr(e?.message || "Failed to load files.");
    }
  }, [linkedEntityType, linkedEntityId, onChange]);

  useEffect(() => { reload(); }, [reload]);

  const remove = async (id) => {
    try {
      await deleteFile(id);
      toast.success("File removed.");
      await reload();
    } catch (e) {
      toast.error(e?.message || "Delete failed.");
    }
  };

  if (rows === null) {
    return <div className={`text-sm text-zinc-500 ${className}`}
                data-testid="file-list-loading">Loading…</div>;
  }
  if (err) {
    return <div className={`text-sm text-red-600 ${className}`}
                data-testid="file-list-error">{err}</div>;
  }
  if (rows.length === 0) {
    return <div className={`text-sm text-zinc-500 ${className}`}
                data-testid="file-list-empty">No files yet.</div>;
  }

  return (
    <ul className={`grid grid-cols-1 sm:grid-cols-2 gap-2 ${className}`}
        data-testid="file-list">
      {rows.map((r) => (
        <li key={r.id}
            data-testid={`file-list-item-${r.id}`}
            className="rounded-xl border border-zinc-200 bg-white p-3 flex items-center gap-3">
          <div className="shrink-0">
            {isImage(r.content_type)
              ? <AuthedImage fileId={r.id} alt={r.original_filename} size={48} />
              : (
                <div className="w-12 h-12 rounded-lg bg-zinc-100 flex items-center justify-center text-zinc-500">
                  {iconFor(r.content_type)}
                </div>
              )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate">{r.original_filename}</div>
            <div className="text-xs text-zinc-500">
              {humanBytes(r.size)} · {r.content_type || "unknown"}
              {r.created_at && ` · ${String(r.created_at).slice(0, 10)}`}
            </div>
          </div>
          {canDelete && (
            <button
              onClick={() => remove(r.id)}
              aria-label={`Delete ${r.original_filename}`}
              data-testid={`file-list-delete-${r.id}`}
              className="p-1.5 rounded-lg text-red-600 hover:bg-red-50">
              <Trash2 size={16} />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

export default FileList;
