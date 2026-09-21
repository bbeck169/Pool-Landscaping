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
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Search, Upload, X as XIcon, Link as LinkIcon, Check, ImageOff,
  FileText, FileSpreadsheet, File as FileIcon,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

const BASE = process.env.REACT_APP_BACKEND_URL;

/**
 * Feb-2026 · Media library P1 fix helper.
 *
 * The backend serves media at ``/api/marketing/media/{id}/download``.
 * When the URL is relative, prepend REACT_APP_BACKEND_URL so the
 * ``<img>`` request lands on the API host (in prod the CRM frontend is
 * on a different origin). Fully-qualified URLs are returned as-is.
 */
function absMediaUrl(u) {
  if (!u) return u;
  if (/^https?:/i.test(u)) return u;
  if (BASE && u.startsWith("/")) return `${BASE}${u}`;
  return u;
}


/**
 * Feb-2026 · Customer-Attachments (Option D).
 *
 * The library was image-only. It now stores PDFs and Office docs.
 * ``isImageMime`` gates the ``<img>`` thumb path so we don't try
 * to render a PDF as an image (which would just show the broken-
 * image placeholder). Non-image mimes fall back to a labeled
 * file-type tile via ``<FileThumb>``.
 */
function isImageMime(m) {
  return (m || "").toLowerCase().startsWith("image/");
}


function pickFileIcon(mime) {
  const m = (mime || "").toLowerCase();
  if (m.includes("spreadsheet") || m === "text/csv") return FileSpreadsheet;
  if (m === "application/pdf" || m.startsWith("text/") || m.includes("word"))
    return FileText;
  return FileIcon;
}


function FileThumb({ item, className }) {
  const Icon = pickFileIcon(item?.mime_type);
  const ext = (
    (item?.file_name || "").split(".").pop() || ""
  ).toLowerCase().slice(0, 5);
  return (
    <div
      className={`${className || ""} bg-zinc-50 flex flex-col items-center justify-center text-zinc-500 gap-1`}
      data-testid="media-file-thumb"
    >
      <Icon className="w-8 h-8" />
      {ext ? (
        <span className="text-[10px] font-semibold uppercase tracking-wide">
          {ext}
        </span>
      ) : null}
      <span
        className="text-[10px] text-zinc-500 px-2 text-center truncate max-w-full"
        title={item?.file_name || ""}
      >
        {item?.file_name || "file"}
      </span>
    </div>
  );
}


/**
 * Client-side variant of the ``accept`` attribute check. Same fuzzy
 * matching browsers do: comma-separated list where each entry is
 * either a wildcard mime (``image/*``), a full mime, or a
 * ``.extension``. Server remains the source of truth.
 */
function _clientAccepts(file, acceptAttr) {
  if (!acceptAttr) return true;
  const parts = acceptAttr.split(",").map((s) => s.trim()).filter(Boolean);
  if (parts.length === 0) return true;
  const name = (file.name || "").toLowerCase();
  const mime = (file.type || "").toLowerCase();
  for (const p of parts) {
    const pl = p.toLowerCase();
    if (pl.startsWith(".")) {
      if (name.endsWith(pl)) return true;
    } else if (pl.endsWith("/*")) {
      const prefix = pl.slice(0, -1);
      if (mime.startsWith(prefix)) return true;
    } else if (pl.includes("/")) {
      if (mime === pl) return true;
    }
  }
  return false;
}

/**
 * Small ``<img>`` wrapper that swaps in a broken-image placeholder
 * when the underlying network request fails (401, 404, 5xx, network
 * error, etc.). Preserves the exact tile geometry so the grid doesn't
 * jump when a single asset fails to load.
 */
function MediaThumb({ src, alt, className }) {
  const [errored, setErrored] = useState(false);
  useEffect(() => { setErrored(false); }, [src]);
  if (errored || !src) {
    return (
      <div
        className={`${className || ""} bg-zinc-100 flex flex-col items-center justify-center text-zinc-400 text-[10px] gap-1`}
        data-testid="media-thumb-broken"
      >
        <ImageOff className="w-5 h-5" />
        <span>Image unavailable</span>
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={alt || "media"}
      className={className}
      loading="lazy"
      onError={() => setErrored(true)}
    />
  );
}

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

/**
 * Feb-2026 · Customer-Attachments (Option D) — additive props:
 *   * ``multiSelect``  — when true, the picker gathers selections into
 *     an array and surfaces them via ``onSelectMultiple(items[])`` on
 *     the "Use N files" primary button. Existing single-select
 *     callers (``TemplateEditor``) are untouched — default is false
 *     and ``onSelect`` fires as before.
 *   * ``kind``         — ``"image"`` | ``"document"`` | ``null`` (all).
 *     Fed to the backend list endpoint as a filter and gates the
 *     upload input's ``accept`` attribute.
 *   * ``accept``       — HTML file-input accept string; defaults to a
 *     sensible set based on ``kind``.
 */
export function MediaLibraryPicker({
  open, onOpenChange, onSelect,
  multiSelect = false,
  onSelectMultiple,
  kind: kindProp = null,
  accept: acceptProp = null,
}) {
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

  // Feb-2026 · Kind filter (Images / Documents / All). Internal state
  // is seeded from the ``kindProp``; user can flip it inside the modal.
  const [kind, setKind] = useState(kindProp);
  useEffect(() => { setKind(kindProp); }, [kindProp]);

  // Feb-2026 · Multi-select batch buffer. Only used when
  // ``multiSelect`` is true. Keyed by media id for O(1) toggle.
  const [batch, setBatch] = useState({});
  const batchList = useMemo(() => Object.values(batch), [batch]);
  const batchCount = batchList.length;
  const isBatched = (id) => Object.prototype.hasOwnProperty.call(batch, id);
  const toggleBatch = (m) => {
    setBatch((prev) => {
      const next = { ...prev };
      if (next[m.id]) delete next[m.id];
      else next[m.id] = m;
      return next;
    });
  };

  const acceptAttr = acceptProp
    || (kind === "document"
          ? ".pdf,.docx,.xlsx,.csv,.txt,application/pdf"
          : kind === "image"
              ? "image/*"
              : "image/*,.pdf,.docx,.xlsx,.csv,.txt");

  const load = useCallback(async (reset = true) => {
    setLoading(true);
    try {
      const nextPageToRequest = reset ? 1 : nextPage;
      const params = new URLSearchParams({ page_size: "48" });
      if (q) params.set("search", q);
      if (tagFilter) params.set("tag", tagFilter);
      if (kind) params.set("kind", kind);
      params.set("page", String(nextPageToRequest));
      const res = await api.get(`/marketing/media?${params}`);
      const items = res.rows || res.items || res.media || [];
      setRows(reset ? items : [...rows, ...items]);
      const total = Number(res.total ?? 0);
      const pageSize = Number(res.page_size ?? 48);
      const has = res.has_more ?? (nextPageToRequest * pageSize < total);
      setHasMore(!!has);
      setNextPage(nextPageToRequest + 1);
      // Build tag universe.
      const tags = new Set();
      items.forEach((m) => (m.tags || []).forEach((t) => tags.add(t)));
      setAllTags(Array.from(tags).sort());
    } catch (e) {
      toast.error(e.message || "Failed to load media library");
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, kind, nextPage, rows]);

  useEffect(() => {
    if (!open) return;
    setSelected(null);
    setBatch({});
    setNextPage(1);
    load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, q, tagFilter, kind]);

  async function onPickFiles(files) {
    if (!files || files.length === 0) return;
    setUploading(true);
    setProgress(0);
    try {
      for (const f of files) {
        // Feb-2026 — client-side validation is a hint; the server is
        // the source of truth (magic bytes + per-type size caps).
        const okByAccept = _clientAccepts(f, acceptAttr);
        if (!okByAccept) {
          toast.error(`${f.name}: file type not allowed`);
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
      const rawUrl = m.storage_url || m.url || m.cdn_url;
      const absUrl = absMediaUrl(m.cdn_url || m.storage_url || m.url);
      onSelect({
        id: m.id,
        // Preserve the API-relative signed URL so backend can find /
        // strip references later, but ALSO expose the fully-qualified
        // absolute URL for direct <img src> use in the editor / email.
        url: absUrl,
        cdn_url: absUrl,
        storage_url: rawUrl,
        alt_text: m.alt_text || "",
        mime_type: m.mime_type || null,
        file_name: m.file_name || null,
      });
    }
    onOpenChange(false);
  }

  function confirmBatch() {
    if (typeof onSelectMultiple === "function") {
      onSelectMultiple(
        batchList.map((m) => ({
          id: m.id,
          url: absMediaUrl(m.cdn_url || m.storage_url || m.url),
          cdn_url: absMediaUrl(m.cdn_url || m.storage_url || m.url),
          storage_url: m.storage_url || m.url || m.cdn_url,
          alt_text: m.alt_text || "",
          mime_type: m.mime_type || null,
          file_name: m.file_name || null,
          size_bytes: m.size_bytes || null,
        })),
      );
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
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#0284C7]" />
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
                accept={acceptAttr}
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
            {/* Feb-2026 · Kind filter row — Images / Documents / All */}
            <div
              className="px-6 py-2 flex items-center gap-1.5 border-b border-zinc-100"
              data-testid="media-picker-kind-filter"
            >
              {[
                { k: null,         label: "All"       },
                { k: "image",      label: "Images"    },
                { k: "document",   label: "Documents" },
              ].map(({ k, label }) => (
                <button
                  key={label}
                  type="button"
                  onClick={() => setKind(k)}
                  data-testid={`media-picker-kind-${k || "all"}`}
                  className={`px-2.5 py-1 rounded-full text-xs whitespace-nowrap ${
                    kind === k ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600"
                  }`}
                >
                  {label}
                </button>
              ))}
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
                  {kind === "document"
                    ? "No documents yet — drop files or click Upload."
                    : kind === "image"
                        ? "No images yet — drop files or click Upload."
                        : "No files yet — drop files or click Upload."}
                </div>
              )}
              <div className="grid grid-cols-4 gap-3">
                {rows.map((m) => {
                  const isImg = isImageMime(m.mime_type);
                  const inBatch = isBatched(m.id);
                  const primaryHighlight = multiSelect
                    ? inBatch
                    : selected?.id === m.id;
                  return (
                    <button
                      key={m.id}
                      onClick={() => {
                        if (multiSelect) toggleBatch(m);
                        else setSelected(m);
                      }}
                      data-testid={`media-picker-item-${m.id}`}
                      className={`relative aspect-square rounded-lg overflow-hidden border transition ${
                        primaryHighlight
                          ? "border-zinc-900 ring-2 ring-zinc-900"
                          : "border-zinc-200 hover:border-zinc-400"
                      }`}
                      title={m.file_name || ""}
                    >
                      {isImg ? (
                        <MediaThumb
                          src={absMediaUrl(m.cdn_url || m.storage_url || m.url)}
                          alt={m.alt_text || m.file_name || "media"}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <FileThumb item={m} className="w-full h-full" />
                      )}
                      {primaryHighlight && (
                        <span className="absolute top-1.5 right-1.5 bg-zinc-900 text-white rounded-full p-1">
                          <Check className="w-3 h-3" />
                        </span>
                      )}
                    </button>
                  );
                })}
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
            {multiSelect ? (
              // Feb-2026 · Customer-Attachments (Option D) — batch mode.
              // Right pane becomes a "selected files" list with an
              // Attach primary CTA. Individual detail editing (alt
              // text / tags) is not offered here on purpose — batch
              // attach is a picking operation, not a curation one.
              <>
                <div className="p-4 border-b border-zinc-100 flex items-center justify-between">
                  <div className="text-sm font-semibold text-zinc-900">
                    Selected ({batchCount})
                  </div>
                  {batchCount > 0 ? (
                    <button
                      onClick={() => setBatch({})}
                      className="text-xs text-zinc-500 hover:text-zinc-900"
                      data-testid="media-picker-batch-clear"
                    >
                      Clear
                    </button>
                  ) : null}
                </div>
                <div className="flex-1 overflow-y-auto p-3 space-y-2">
                  {batchList.length === 0 ? (
                    <div
                      className="text-center py-8 text-sm text-zinc-400"
                      data-testid="media-picker-batch-empty"
                    >
                      Tap tiles to add them here.
                    </div>
                  ) : batchList.map((m) => {
                    const isImg = isImageMime(m.mime_type);
                    return (
                      <div
                        key={m.id}
                        className="flex items-center gap-2 rounded-lg border border-zinc-200 p-2"
                        data-testid={`media-picker-batch-row-${m.id}`}
                      >
                        <div className="w-10 h-10 rounded overflow-hidden bg-zinc-100 flex-shrink-0">
                          {isImg ? (
                            <MediaThumb
                              src={absMediaUrl(m.cdn_url || m.storage_url || m.url)}
                              alt={m.alt_text || m.file_name || ""}
                              className="w-full h-full object-cover"
                            />
                          ) : (
                            <FileThumb item={m} className="w-full h-full" />
                          )}
                        </div>
                        <div className="flex-1 min-w-0 text-xs">
                          <div className="truncate font-medium text-zinc-900">
                            {m.file_name || m.id}
                          </div>
                          <div className="text-zinc-500 truncate">
                            {m.mime_type || "unknown"}
                          </div>
                        </div>
                        <button
                          onClick={() => toggleBatch(m)}
                          className="text-zinc-400 hover:text-zinc-900 p-1"
                          aria-label={`Remove ${m.file_name || m.id}`}
                          data-testid={`media-picker-batch-remove-${m.id}`}
                        >
                          <XIcon className="w-4 h-4" />
                        </button>
                      </div>
                    );
                  })}
                </div>
                <div className="p-4 border-t border-zinc-100 flex items-center gap-2">
                  <button
                    onClick={() => onOpenChange(false)}
                    className="px-3 py-2 rounded-lg border border-zinc-200 text-sm hover:bg-zinc-50"
                    data-testid="media-picker-batch-cancel"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={confirmBatch}
                    disabled={batchCount === 0}
                    className="ml-auto inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 disabled:opacity-40"
                    data-testid="media-picker-batch-confirm"
                  >
                    <Check className="w-4 h-4" />
                    {batchCount === 0
                      ? "Attach"
                      : `Attach ${batchCount} file${batchCount === 1 ? "" : "s"}`}
                  </button>
                </div>
              </>
            ) : !selected ? (
              <div className="flex-1 flex items-center justify-center p-6 text-center text-sm text-zinc-400">
                Select an item to see details.
              </div>
            ) : (
              <>
                <div className="p-4 border-b border-zinc-100">
                  {isImageMime(selected.mime_type) ? (
                    <MediaThumb
                      src={absMediaUrl(selected.cdn_url || selected.storage_url || selected.url)}
                      alt={selected.alt_text || ""}
                      className="w-full max-h-40 object-contain rounded"
                    />
                  ) : (
                    <FileThumb item={selected} className="w-full h-40 rounded" />
                  )}
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
                        navigator.clipboard.writeText(absMediaUrl(selected.cdn_url || selected.storage_url || selected.url));
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
                    {isImageMime(selected.mime_type) ? "Use this image" : "Use this file"}
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
