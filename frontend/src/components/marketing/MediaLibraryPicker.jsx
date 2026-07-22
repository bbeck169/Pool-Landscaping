/**
 * Phase 9B · Feb 2026 — MediaLibraryPicker.
 *
 * Full-width grid of marketing media. Fetches ``GET /api/marketing/media``
 * (paginated), supports drag-drop / click-upload against
 * ``POST /api/marketing/media/upload``. Selected item shows a right-side
 * detail pane with editable alt_text + tag chips + Copy URL + Select.
 *
 * ``onSelect({id, url, cdn_url, alt_text})`` fires when the primary
 * "Use this image" button is clicked.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Search, Upload, X as XIcon, Link as LinkIcon, Check } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

const BASE = process.env.REACT_APP_BACKEND_URL;

function TokenAuthHeaders(extra = {}) {
  const token = localStorage.getItem("token") || "";
  const tenantSlug = localStorage.getItem("tenant_slug") || "";
  const h = { ...extra };
  if (token) h["Authorization"] = `Bearer ${token}`;
  if (tenantSlug) h["X-Tenant-Slug"] = tenantSlug;
  return h;
}

async function uploadFile(file, onProgress) {
  // Direct fetch — need multipart/form-data. api.js uses JSON.
  const fd = new FormData();
  fd.append("file", file);
  if (file.name) fd.append("alt_text", "");
  const url = `${BASE}/api/marketing/media/upload`;
  // Progress tracking via XHR (fetch stream API can't reliably measure
  // multipart upload progress across all browsers).
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    const headers = TokenAuthHeaders();
    Object.entries(headers).forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress((e.loaded / e.total) * 100);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)); }
        catch { resolve({}); }
      } else {
        try {
          const body = JSON.parse(xhr.responseText);
          reject(new Error(body?.detail?.message || body?.detail || `Upload failed (${xhr.status})`));
        } catch {
          reject(new Error(`Upload failed (${xhr.status})`));
        }
      }
    };
    xhr.onerror = () => reject(new Error("Network error uploading file"));
    xhr.send(fd);
  });
}

export function MediaLibraryPicker({ open, onOpenChange, onSelect }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [allTags, setAllTags] = useState([]);
  const [selected, setSelected] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [nextPage, setNextPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const fileInputRef = useRef(null);

  const load = useCallback(async (reset = true) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "48" });
      if (q) params.set("q", q);
      if (tagFilter) params.set("tag", tagFilter);
      if (!reset && nextPage) params.set("page", String(nextPage));
      const res = await api.get(`/marketing/media?${params}`);
      const items = res.items || res.media || res.rows || [];
      setRows(reset ? items : [...rows, ...items]);
      setHasMore(!!res.has_more);
      setNextPage((res.next_page ?? nextPage) || nextPage);
      // Build tag universe.
      const tags = new Set();
      items.forEach((m) => (m.tags || []).forEach((t) => tags.add(t)));
      setAllTags(Array.from(tags).sort());
    } catch (e) {
      toast.error(e.message || "Failed to load media library");
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, nextPage, rows]);

  useEffect(() => {
    if (!open) return;
    setSelected(null);
    setNextPage(1);
    load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, q, tagFilter]);

  async function onPickFiles(files) {
    if (!files || files.length === 0) return;
    setUploading(true);
    setProgress(0);
    try {
      for (const f of files) {
        // Basic client-side validation — server also validates.
        if (!/^image\//.test(f.type)) {
          toast.error(`${f.name}: not an image`);
          continue;
        }
        const created = await uploadFile(f, setProgress);
        toast.success(`Uploaded ${f.name}`);
        if (created && (created.id || created.url)) {
          setRows((prev) => [created, ...prev]);
        }
      }
    } catch (e) {
      toast.error(e.message || "Upload failed");
    } finally {
      setUploading(false);
      setProgress(0);
    }
  }

  function onDrop(e) {
    e.preventDefault();
    setDragging(false);
    onPickFiles(Array.from(e.dataTransfer.files || []));
  }

  function pickImage(m) {
    if (typeof onSelect === "function") {
      onSelect({
        id: m.id,
        url: m.storage_url || m.url,
        cdn_url: m.cdn_url || m.storage_url || m.url,
        alt_text: m.alt_text || "",
      });
    }
    onOpenChange(false);
  }

  async function saveMetadata() {
    if (!selected) return;
    try {
      const updated = await api.patch(`/marketing/media/${selected.id}`, {
        alt_text: selected.alt_text || "",
        tags: selected.tags || [],
      });
      setRows((prev) => prev.map((r) => (r.id === selected.id ? { ...r, ...updated } : r)));
      setSelected((prev) => ({ ...prev, ...updated }));
      toast.success("Metadata saved");
    } catch (e) {
      toast.error(e.message || "Save failed");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl p-0 overflow-hidden"
                      data-testid="media-picker-dialog">
        <DialogHeader className="px-6 pt-6 pb-3 border-b border-zinc-100">
          <DialogTitle>Media library</DialogTitle>
        </DialogHeader>
        <div className="flex" style={{ minHeight: "60vh" }}>
          {/* Left — grid + toolbar */}
          <div className="flex-1 flex flex-col border-r border-zinc-100">
            <div className="px-6 py-3 flex items-center gap-2 border-b border-zinc-100">
              <div className="relative flex-1 max-w-sm">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search filename or alt text…"
                  data-testid="media-picker-search"
                  className="w-full pl-9 pr-3 py-2 rounded-lg border border-zinc-200 text-sm placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-300"
                />
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                hidden
                onChange={(e) => onPickFiles(Array.from(e.target.files || []))}
                data-testid="media-picker-file-input"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                data-testid="media-picker-upload-btn"
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 disabled:opacity-50"
              >
                <Upload className="w-4 h-4" />
                {uploading ? `Uploading ${progress.toFixed(0)}%` : "Upload"}
              </button>
            </div>
            {allTags.length > 0 && (
              <div className="px-6 py-2 flex items-center gap-1.5 border-b border-zinc-100 overflow-x-auto">
                <button
                  onClick={() => setTagFilter("")}
                  data-testid="media-picker-tag-all"
                  className={`px-2.5 py-1 rounded-full text-xs whitespace-nowrap ${
                    tagFilter === "" ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600"
                  }`}
                >
                  All
                </button>
                {allTags.map((t) => (
                  <button key={t}
                          onClick={() => setTagFilter(t)}
                          data-testid={`media-picker-tag-${t}`}
                          className={`px-2.5 py-1 rounded-full text-xs whitespace-nowrap ${
                            tagFilter === t ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600"
                          }`}>
                    {t}
                  </button>
                ))}
              </div>
            )}
            <div
              onDrop={onDrop}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              className={`flex-1 overflow-y-auto p-4 relative ${dragging ? "bg-blue-50/40" : ""}`}
              data-testid="media-picker-grid"
            >
              {dragging && (
                <div className="absolute inset-0 pointer-events-none border-2 border-dashed border-blue-400 rounded-lg m-2 flex items-center justify-center text-blue-700 text-sm">
                  Drop images to upload
                </div>
              )}
              {loading && rows.length === 0 && (
                <div className="text-center py-16 text-sm text-zinc-500">Loading media…</div>
              )}
              {!loading && rows.length === 0 && (
                <div className="text-center py-16 text-sm text-zinc-400"
                     data-testid="media-picker-empty">
                  No images yet — drop files or click Upload.
                </div>
              )}
              <div className="grid grid-cols-4 gap-3">
                {rows.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => setSelected(m)}
                    data-testid={`media-picker-item-${m.id}`}
                    className={`relative aspect-square rounded-lg overflow-hidden border transition ${
                      selected?.id === m.id
                        ? "border-zinc-900 ring-2 ring-zinc-900"
                        : "border-zinc-200 hover:border-zinc-400"
                    }`}
                    title={m.file_name || ""}
                  >
                    <img
                      src={m.cdn_url || m.storage_url || m.url}
                      alt={m.alt_text || m.file_name || "media"}
                      className="w-full h-full object-cover"
                      loading="lazy"
                    />
                    {selected?.id === m.id && (
                      <span className="absolute top-1.5 right-1.5 bg-zinc-900 text-white rounded-full p-1">
                        <Check className="w-3 h-3" />
                      </span>
                    )}
                  </button>
                ))}
              </div>
              {hasMore && !loading && (
                <div className="text-center mt-4">
                  <button
                    onClick={() => load(false)}
                    className="px-4 py-2 rounded-lg border border-zinc-200 text-sm hover:bg-zinc-50"
                    data-testid="media-picker-load-more"
                  >
                    Load more
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Right — detail pane */}
          <div className="w-80 flex flex-col">
            {!selected ? (
              <div className="flex-1 flex items-center justify-center p-6 text-center text-sm text-zinc-400">
                Select an image to see details.
              </div>
            ) : (
              <>
                <div className="p-4 border-b border-zinc-100">
                  <img
                    src={selected.cdn_url || selected.storage_url || selected.url}
                    alt={selected.alt_text || ""}
                    className="w-full max-h-40 object-contain rounded"
                  />
                </div>
                <div className="p-4 space-y-3 flex-1 overflow-y-auto">
                  <div>
                    <div className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-1">
                      Alt text
                    </div>
                    <textarea
                      value={selected.alt_text || ""}
                      onChange={(e) => setSelected({ ...selected, alt_text: e.target.value })}
                      data-testid="media-picker-alt-input"
                      rows={2}
                      className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-300"
                      placeholder="Describe for screen readers"
                    />
                  </div>
                  <div>
                    <div className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-1">
                      Tags
                    </div>
                    <ChipInput
                      value={selected.tags || []}
                      onChange={(tags) => setSelected({ ...selected, tags })}
                    />
                  </div>
                  <div className="flex items-center gap-1 text-xs text-zinc-500">
                    <span>URL:</span>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(selected.cdn_url || selected.storage_url || selected.url);
                        toast.success("URL copied");
                      }}
                      data-testid="media-picker-copy-url"
                      className="inline-flex items-center gap-1 text-zinc-900 underline"
                    >
                      <LinkIcon className="w-3 h-3" />
                      copy
                    </button>
                  </div>
                </div>
                <div className="p-4 border-t border-zinc-100 flex items-center gap-2">
                  <button
                    onClick={saveMetadata}
                    className="px-3 py-2 rounded-lg border border-zinc-200 text-sm hover:bg-zinc-50"
                    data-testid="media-picker-save-meta"
                  >
                    Save meta
                  </button>
                  <button
                    onClick={() => pickImage(selected)}
                    className="ml-auto inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800"
                    data-testid="media-picker-select-btn"
                  >
                    <Check className="w-4 h-4" />
                    Use this image
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}


function ChipInput({ value, onChange }) {
  const [text, setText] = useState("");
  function addTag() {
    const v = text.trim().replace(/,+$/, "");
    if (!v) return;
    if (!(value || []).includes(v)) {
      onChange([...(value || []), v]);
    }
    setText("");
  }
  return (
    <div className="flex flex-wrap gap-1 p-2 rounded-lg border border-zinc-200 min-h-[44px]"
         data-testid="media-picker-chip-input">
      {(value || []).map((t) => (
        <span key={t}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-zinc-100 text-zinc-700">
          {t}
          <button
            onClick={() => onChange((value || []).filter((x) => x !== t))}
            className="text-zinc-400 hover:text-zinc-700"
            aria-label={`Remove ${t}`}
            data-testid={`media-picker-chip-x-${t}`}
          >
            <XIcon className="w-3 h-3" />
          </button>
        </span>
      ))}
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTag(); }
          else if (e.key === "Backspace" && !text && (value || []).length) {
            onChange((value || []).slice(0, -1));
          }
        }}
        onBlur={addTag}
        placeholder="Add tag…"
        className="flex-1 min-w-[80px] text-sm focus:outline-none"
      />
    </div>
  );
}
