import React, { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { colors } from "@/theme";
import { X, Upload, CheckCircle2, Phone, Mail } from "lucide-react";

const BASE = process.env.REACT_APP_BACKEND_URL;
const MAX_FILES = 10;
const MAX_FILE_MB = 20;

export default function PublicLeadRequestPage() {
  const { token } = useParams();
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState("");
  const [values, setValues] = useState({});
  const [files, setFiles] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    fetch(`${BASE}/api/public/lead-request/${token}`)
      .then(async (r) => {
        if (r.ok) return r.json();
        const data = await r.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${r.status}`);
      })
      .then(setMeta)
      .catch((e) => setError(e.message || "Not found"));
  }, [token]);

  const setField = (k, v) => setValues((s) => ({ ...s, [k]: v }));

  const onFiles = (list) => {
    const next = [...files];
    for (const f of list) {
      if (next.length >= MAX_FILES) break;
      if (f.size > MAX_FILE_MB * 1024 * 1024) continue;
      next.push(f);
    }
    setFiles(next);
  };
  const removeFile = (i) => setFiles(files.filter((_, ix) => ix !== i));

  const submit = async () => {
    setError("");
    setSubmitting(true);
    try {
      const form = new FormData();
      Object.entries(values).forEach(([k, v]) => form.append(k, v ?? ""));
      files.forEach((f) => form.append("files", f, f.name));
      const r = await fetch(`${BASE}/api/public/lead-request/${token}/submit`, {
        method: "POST", body: form,
      });
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        throw new Error(data.detail || "Submit failed");
      }
      setDone(true);
    } catch (e) { setError(e.message || "Failed"); }
    finally { setSubmitting(false); }
  };

  if (error && !meta) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6" data-testid="public-lr-error"
           style={{ backgroundColor: "#F1F5F9" }}>
        <div className="max-w-md text-center bg-white rounded-2xl p-8 shadow-xl">
          <div className="text-lg font-bold mb-2" style={{ color: colors.onSurface }}>Link not available</div>
          <div className="text-sm" style={{ color: colors.muted }}>{error}</div>
        </div>
      </div>
    );
  }
  if (!meta) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;

  const b = meta.branding || {};
  const primary = b.primary_color || "#0284C7";
  const secondary = b.secondary_color || "#16A34A";
  const gradient = `linear-gradient(135deg, ${primary} 0%, ${secondary} 100%)`;

  if (done) {
    return (
      <div className="min-h-screen p-4 md:p-8" style={{ backgroundColor: "#F1F5F9" }}
           data-testid="public-lr-done">
        <div className="max-w-2xl mx-auto">
          <div className="rounded-t-3xl p-8 text-white text-center" style={{ background: gradient }}>
            <CheckCircle2 size={56} className="mx-auto mb-3" />
            <h1 className="text-2xl font-bold">Thanks — we'll be in touch shortly!</h1>
            <div className="text-sm opacity-90 mt-2">Your information has been received.</div>
          </div>
          <div className="bg-white rounded-b-3xl p-6 text-sm space-y-2" style={{ color: colors.onSurface }}>
            <div className="font-bold">{b.business_name}</div>
            {(b.address_lines || []).map((l, i) => <div key={i} style={{ color: colors.muted }}>{l}</div>)}
            {b.phone && <div className="flex items-center gap-1"><Phone size={12} /> {b.phone}</div>}
            {b.email && <div className="flex items-center gap-1"><Mail size={12} /> {b.email}</div>}
          </div>
        </div>
      </div>
    );
  }

  const fields = meta.form?.fields || [];
  const req = (f) => f.required;

  return (
    <div className="min-h-screen" style={{ backgroundColor: "#F1F5F9" }} data-testid="public-lr-form">
      <div className="max-w-2xl mx-auto">
        {/* Branded header */}
        <div className="rounded-t-3xl p-8 text-white text-center" style={{ background: gradient }}
             data-testid="public-lr-header">
          {b.logo_url
            ? <img src={b.logo_url} alt="logo" className="mx-auto mb-3 max-h-16" />
            : <div className="mx-auto mb-3 w-16 h-16 rounded-2xl bg-white/20 flex items-center justify-center text-2xl font-bold">
                {(b.business_name || "A").charAt(0)}
              </div>}
          <div className="text-xl md:text-2xl font-bold">{b.business_name}</div>
          {(b.address_lines || []).map((l, i) => <div key={i} className="text-sm opacity-90">{l}</div>)}
          <div className="mt-2 text-sm opacity-90 flex items-center justify-center gap-4 flex-wrap">
            {b.phone && <div className="flex items-center gap-1"><Phone size={12} /> {b.phone}</div>}
            {b.email && <div className="flex items-center gap-1"><Mail size={12} /> {b.email}</div>}
          </div>
        </div>

        {/* Form card */}
        <div className="bg-white -mt-4 rounded-3xl shadow-xl p-6 md:p-8">
          <h2 className="text-xl font-bold mb-2" style={{ color: colors.onSurface }}>{meta.form?.title || "Customer Form"}</h2>
          {meta.personal_message && (
            <div className="mb-5 p-3 rounded-lg text-sm"
                 style={{ backgroundColor: "#F0F9FF", color: colors.onSurface }}
                 data-testid="public-lr-message">
              <b>Message:</b> {meta.personal_message}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {fields.map((f) => (
              <div key={f.key} className={f.type === "textarea" ? "md:col-span-2" : ""} data-testid={`field-wrap-${f.key}`}>
                <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.muted }}>
                  {f.label.toUpperCase()}{req(f) && " *"}
                </label>
                {f.type === "textarea" ? (
                  <textarea value={values[f.key] || ""} onChange={(e) => setField(f.key, e.target.value)} rows={4}
                            required={req(f)}
                            className="w-full px-3 py-2 rounded-lg text-sm outline-none focus:ring-2"
                            style={{ border: `1px solid ${colors.border}`, color: colors.onSurface }}
                            data-testid={`in-${f.key}`} />
                ) : (
                  <input type={f.type === "number" ? "number" : f.type === "email" ? "email" : f.type === "phone" ? "tel" : "text"}
                         value={values[f.key] || ""} onChange={(e) => setField(f.key, e.target.value)}
                         required={req(f)}
                         className="w-full px-3 py-2 rounded-lg text-sm outline-none focus:ring-2"
                         style={{ border: `1px solid ${colors.border}`, color: colors.onSurface }}
                         data-testid={`in-${f.key}`} />
                )}
              </div>
            ))}
          </div>

          {/* File uploads */}
          <div className="mt-5">
            <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.muted }}>
              PHOTOS / VIDEOS (optional, up to {MAX_FILES})
            </label>
            <div onClick={() => fileInputRef.current?.click()}
                 onDragOver={(e) => e.preventDefault()}
                 onDrop={(e) => { e.preventDefault(); onFiles(e.dataTransfer.files); }}
                 className="rounded-xl p-6 text-center cursor-pointer"
                 style={{ border: `2px dashed ${colors.border}`, backgroundColor: "#F8FAFC" }}
                 data-testid="lr-file-drop">
              <Upload size={20} className="mx-auto mb-1" style={{ color: colors.muted }} />
              <div className="text-xs" style={{ color: colors.muted }}>
                Drag &amp; drop files or click to browse — max {MAX_FILE_MB}MB each
              </div>
              <input ref={fileInputRef} type="file" multiple hidden
                     onChange={(e) => onFiles(e.target.files)} data-testid="lr-file-input" />
            </div>
            {files.length > 0 && (
              <div className="mt-3 grid grid-cols-2 md:grid-cols-3 gap-2" data-testid="lr-file-list">
                {files.map((f, i) => (
                  <div key={i} className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs"
                       style={{ backgroundColor: colors.surfaceSecondary }}>
                    <div className="flex-1 truncate" style={{ color: colors.onSurface }}>{f.name}</div>
                    <div style={{ color: colors.muted }}>{(f.size / 1024).toFixed(0)}k</div>
                    <button onClick={() => removeFile(i)} data-testid={`lr-file-remove-${i}`}>
                      <X size={12} style={{ color: colors.muted }} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {error && <div className="mt-3 text-sm" style={{ color: colors.error }}>{error}</div>}

          <button onClick={submit} disabled={submitting}
                  className="mt-6 w-full py-4 rounded-xl font-bold text-white text-sm uppercase tracking-widest"
                  style={{ background: gradient, opacity: submitting ? 0.7 : 1 }}
                  data-testid="lr-submit">
            {submitting ? "Sending…" : "Send Information"}
          </button>
          {meta.expiry_hours && (
            <div className="mt-3 text-center text-xs" style={{ color: colors.muted }}>
              Please complete within {meta.expiry_hours} hours, thank you.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
