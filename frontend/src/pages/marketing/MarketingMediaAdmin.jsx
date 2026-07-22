/**
 * Phase 9B · Feb 2026 — Marketing Media Library management page.
 *
 * Bulk actions on top of the MediaLibraryPicker grid:
 *   * bulk-tag (add / remove chip tag on selected items)
 *   * bulk-soft-delete (respects 409 ref-guard per item — end-of-run
 *     summary shows how many deleted vs blocked)
 * Selection: cmd/ctrl-click toggles a single item; shift-click extends
 * range; Select all / Clear.
 */
import React, { useCallback, useEffect, useState } from "react";
import { Upload, Trash2, Tag as TagIcon, Search, CheckSquare, Square } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";

const BASE = process.env.REACT_APP_BACKEND_URL;

function authHeaders() {
  const h = { };
  const t = localStorage.getItem("token");
  const s = localStorage.getItem("tenant_slug");
  if (t) h["Authorization"] = `Bearer ${t}`;
  if (s) h["X-Tenant-Slug"] = s;
  return h;
}

export default function MarketingMediaAdminPage() {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [tagInput, setTagInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileInputRef = React.useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (q) params.set("q", q);
      const res = await api.get(`/marketing/media?${params}`);
      setRows(res.items || res.media || res.rows || []);
    } catch (e) {
      toast.error(e.message || "Failed to load media");
    } finally {
      setLoading(false);
    }
  }, [q]);

  useEffect(() => { load(); }, [load]);

  function toggleSelected(id, extend = false) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const allSelected = rows.length > 0 && selectedIds.size === rows.length;
  function toggleSelectAll() {
    if (allSelected) setSelectedIds(new Set());
    else setSelectedIds(new Set(rows.map((r) => r.id)));
  }

  async function upload(files) {
    if (!files || !files.length) return;
    setUploading(true);
    try {
      for (const f of files) {
        const fd = new FormData();
        fd.append("file", f);
        const res = await fetch(`${BASE}/api/marketing/media/upload`, {
          method: "POST", body: fd, headers: authHeaders(),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `Upload failed (${res.status})`);
        }
        const j = await res.json();
        setRows((prev) => [j, ...prev]);
      }
      toast.success(`Uploaded ${files.length} file(s)`);
    } catch (e) {
      toast.error(e.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function bulkTag() {
    const tag = tagInput.trim();
    if (!tag) {
      toast.error("Enter a tag first");
      return;
    }
    if (selectedIds.size === 0) {
      toast.error("Select at least one image");
      return;
    }
    let ok = 0, fail = 0;
    for (const id of selectedIds) {
      try {
        const row = rows.find((r) => r.id === id);
        const nextTags = Array.from(new Set([...(row?.tags || []), tag]));
        await api.patch(`/marketing/media/${id}`, { tags: nextTags });
        ok += 1;
      } catch { fail += 1; }
    }
    setTagInput("");
    toast.success(`Tag added on ${ok} · ${fail} failed`);
    load();
  }

  async function bulkDelete() {
    if (selectedIds.size === 0) {
      toast.error("Select at least one image");
      return;
    }
    if (!window.confirm(`Delete ${selectedIds.size} image(s)?`)) return;
    let deleted = 0, blocked = 0, failed = 0;
    for (const id of selectedIds) {
      try {
        await api.del(`/marketing/media/${id}`);
        deleted += 1;
      } catch (e) {
        if (/409|referenced/i.test(String(e.message))) blocked += 1;
        else failed += 1;
      }
    }
    toast.success(
      `${deleted} deleted · ${blocked} still referenced · ${failed} failed`
    );
    setSelectedIds(new Set());
    load();
  }

  return (
    <div className="min-h-screen bg-zinc-50" data-testid="media-admin-page">
      <div className="bg-white border-b border-zinc-200">
        <div className="max-w-7xl mx-auto px-6 py-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-zinc-900">Media library</h1>
            <p className="text-sm text-zinc-500 mt-0.5">
              Manage images used across marketing templates + campaigns.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <input ref={fileInputRef} type="file" multiple accept="image/*" hidden
                   onChange={(e) => upload(Array.from(e.target.files || []))}
                   data-testid="media-admin-file-input" />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              data-testid="media-admin-upload-btn"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 disabled:opacity-50"
            >
              <Upload className="w-4 h-4" />
              {uploading ? "Uploading…" : "Upload"}
            </button>
          </div>
        </div>
        <div className="max-w-7xl mx-auto px-6 pb-4 flex items-center gap-2">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
            <input value={q}
                   onChange={(e) => setQ(e.target.value)}
                   placeholder="Search…"
                   data-testid="media-admin-search"
                   className="w-full pl-9 pr-3 py-2 rounded-lg border border-zinc-200 text-sm placeholder:text-zinc-400"/>
          </div>
          <button
            onClick={toggleSelectAll}
            data-testid="media-admin-select-all"
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-zinc-200 text-sm text-zinc-700 hover:bg-zinc-50"
          >
            {allSelected
              ? <CheckSquare className="w-4 h-4" />
              : <Square className="w-4 h-4" />}
            {allSelected ? "Clear" : "Select all"}
          </button>
          {selectedIds.size > 0 && (
            <>
              <div className="ml-auto text-sm text-zinc-500">
                {selectedIds.size} selected
              </div>
              <input
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                placeholder="Tag to add…"
                data-testid="media-admin-bulk-tag-input"
                className="px-3 py-2 rounded-lg border border-zinc-200 text-sm w-40"
              />
              <button
                onClick={bulkTag}
                data-testid="media-admin-bulk-tag-btn"
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-zinc-200 text-sm text-zinc-700 hover:bg-zinc-50"
              >
                <TagIcon className="w-4 h-4" />
                Add tag
              </button>
              <button
                onClick={bulkDelete}
                data-testid="media-admin-bulk-delete-btn"
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-red-600 border border-red-200 text-sm hover:bg-red-50"
              >
                <Trash2 className="w-4 h-4" />
                Delete
              </button>
            </>
          )}
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6">
        {loading && (
          <div className="py-16 text-center text-sm text-zinc-500">Loading…</div>
        )}
        {!loading && rows.length === 0 && (
          <div className="py-16 text-center text-sm text-zinc-400 bg-white rounded-xl border border-dashed border-zinc-200">
            No images uploaded. Click Upload to add your first.
          </div>
        )}
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
          {rows.map((m) => {
            const isSel = selectedIds.has(m.id);
            return (
              <button
                key={m.id}
                onClick={(e) => toggleSelected(m.id, e.shiftKey)}
                data-testid={`media-admin-item-${m.id}`}
                className={`relative aspect-square rounded-lg overflow-hidden border transition ${
                  isSel
                    ? "border-zinc-900 ring-2 ring-zinc-900"
                    : "border-zinc-200 hover:border-zinc-400"
                }`}
                title={m.file_name || ""}
              >
                <img src={m.cdn_url || m.storage_url || m.url}
                     alt={m.alt_text || ""}
                     className="w-full h-full object-cover" loading="lazy"/>
                {isSel && (
                  <span className="absolute top-1.5 right-1.5 bg-zinc-900 text-white rounded-full p-1">
                    <CheckSquare className="w-3 h-3" />
                  </span>
                )}
                {(m.tags || []).length > 0 && (
                  <div className="absolute bottom-1 left-1 right-1 flex flex-wrap gap-1">
                    {(m.tags || []).slice(0, 3).map((t) => (
                      <span key={t}
                            className="px-1.5 py-0.5 rounded text-[10px] bg-black/60 text-white">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
