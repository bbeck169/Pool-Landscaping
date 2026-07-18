import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { X, ExternalLink, Camera, ListChecks, FlaskConical, Beaker, AlertTriangle, StickyNote, Wrench, PenTool, Link2, Share2 } from 'lucide-react';
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

/**
 * Right-side slide-in drawer showing the full field-report for a job.
 * Section order per spec:
 *   Photos, Checklist, Chemical Readings, Chemicals Added,
 *   Service Issues, Notes, Maintenance Log, Signature
 * Empty sections render a friendly placeholder rather than blank space.
 *
 * `onShareToast(text)` optional — parent can render its own toast.
 * `onPermissionDenied()` optional — parent handles unauthorised access.
 */
export default function WorkstreamJobDrawer({ jobId, onClose, onShareToast, onPermissionDenied }) {
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [lightbox, setLightbox] = useState(null);
  const [localToast, setLocalToast] = useState("");

  useEffect(() => {
    if (!jobId) return;
    setJob(null); setError("");
    api.get(`/jobs/${jobId}`)
       .then(setJob)
       .catch((e) => {
         const msg = e?.message || "";
         if (/403|401|forbidden|unauthor/i.test(msg)) {
           onPermissionDenied?.();
         }
         setError(msg || "Failed to load job");
       });
  }, [jobId, onPermissionDenied]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const pushToast = (text) => {
    if (onShareToast) onShareToast(text);
    else { setLocalToast(text); setTimeout(() => setLocalToast(""), 2500); }
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      pushToast("Link copied — anyone with access can view this activity");
    } catch {
      pushToast("Could not copy link");
    }
  };

  const shareLink = async () => {
    const url = window.location.href;
    if (navigator.share) {
      try {
        await navigator.share({ title: job?.title || "Job activity", url });
        return;
      } catch { /* user cancelled — fall through to copy */ }
    }
    copyLink();
  };

  if (!jobId) return null;

  return (
    <div className="fixed inset-0 z-50" data-testid="workstream-job-drawer">
      <div className="absolute inset-0" style={{ backgroundColor: "rgba(0,0,0,0.5)" }} onClick={onClose} />
      <aside className="absolute right-0 top-0 bottom-0 w-full sm:w-[480px] flex flex-col shadow-2xl"
             style={{ backgroundColor: colors.surface, borderLeft: `1px solid ${colors.border}` }}>
        <div className="px-5 py-4 flex items-center justify-between gap-2"
             style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase tracking-wide" style={{ color: colors.muted }}>Job</div>
            <div className="text-base font-bold truncate" style={{ color: colors.onSurface }}>
              {job?.title || (error ? "Error" : "Loading…")}
            </div>
            {job && (
              <div className="text-xs mt-0.5 flex items-center gap-2" style={{ color: colors.muted }}>
                <span>{job.customer_name}</span>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
                      style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}>
                  {job.status}
                </span>
              </div>
            )}
          </div>
          <button onClick={shareLink} className="p-2 rounded-lg"
                  style={{ backgroundColor: colors.surfaceSecondary }}
                  data-testid="drawer-share" title="Share">
            <Share2 size={16} />
          </button>
          <button onClick={copyLink} className="p-2 rounded-lg"
                  style={{ backgroundColor: colors.surfaceSecondary }}
                  data-testid="drawer-copy-link" title="Copy link">
            <Link2 size={16} />
          </button>
          <button onClick={onClose} className="p-2 rounded-lg"
                  style={{ backgroundColor: colors.surfaceSecondary }}
                  data-testid="drawer-close" aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {error && <div className="text-sm" style={{ color: colors.error }}>{error}</div>}
          {!job && !error && <div className="space-y-3">
            {[1,2,3].map((i) => (
              <div key={i} className="animate-pulse rounded-xl h-24" style={{ backgroundColor: colors.surfaceSecondary }} />
            ))}
          </div>}
          {job && <>
            <Section icon={Camera} title="Photos" testId="section-photos" count={(job.photos || []).length}>
              {(job.photos || []).length === 0
                ? <EmptyRow text="No photos captured on this visit." />
                : <div className="grid grid-cols-3 gap-2" data-testid="drawer-photos">
                    {(job.photos || []).map((p) => (
                      <button key={p.id || p.url} onClick={() => setLightbox(p.url || p)}
                              className="rounded-lg overflow-hidden aspect-square"
                              style={{ backgroundColor: colors.surfaceSecondary }}>
                        <img src={p.url || p} alt="job" className="w-full h-full object-cover" />
                      </button>
                    ))}
                  </div>}
            </Section>

            <Section icon={ListChecks} title="Checklist" testId="section-checklist" count={(job.checklist || []).length}>
              {(job.checklist || []).length === 0
                ? <EmptyRow text="No checklist filled." />
                : <ul className="space-y-1.5" data-testid="drawer-checklist">
                    {(job.checklist || []).map((c, i) => (
                      <li key={i} className="flex items-center gap-2 text-sm">
                        <span className="w-4 h-4 rounded flex items-center justify-center text-[10px] font-bold"
                              style={{ backgroundColor: c.done ? "#DCFCE7" : colors.surfaceSecondary,
                                       color: c.done ? "#166534" : colors.muted }}>
                          {c.done ? "✓" : ""}
                        </span>
                        <span style={{ color: c.done ? colors.onSurface : colors.muted, textDecoration: c.done ? "none" : "line-through" }}>
                          {c.label || c.text || c}
                        </span>
                      </li>
                    ))}
                  </ul>}
            </Section>

            <Section icon={FlaskConical} title="Chemical Readings" testId="section-readings"
                     count={(job.chemical_readings || job.reading_report ? 1 : 0)}>
              {ReadingsRender(job)}
            </Section>

            <Section icon={Beaker} title="Chemicals Added" testId="section-chemicals-added"
                     count={(job.chemicals_added || []).length}>
              {(job.chemicals_added || []).length === 0
                ? <EmptyRow text="No chemicals dosed on this visit." />
                : <ul className="space-y-1.5" data-testid="drawer-chemicals-added">
                    {(job.chemicals_added || []).map((c, i) => (
                      <li key={i} className="text-sm flex items-baseline justify-between px-2 py-1.5 rounded"
                          style={{ backgroundColor: colors.surfaceSecondary }}>
                        <span style={{ color: colors.onSurface }}>{c.name || c.chemical}</span>
                        <span className="font-mono text-xs" style={{ color: colors.muted }}>
                          {c.amount ? `${c.amount} ${c.unit || ""}` : c.qty}
                        </span>
                      </li>
                    ))}
                  </ul>}
            </Section>

            <Section icon={AlertTriangle} title="Service Issues" testId="section-issues"
                     count={(job.service_issues || job.issues || []).length}>
              {(job.service_issues || job.issues || []).length === 0
                ? <EmptyRow text="No issues raised." />
                : <ul className="space-y-1.5" data-testid="drawer-issues">
                    {(job.service_issues || job.issues || []).map((it, i) => (
                      <li key={i} className="rounded-lg p-2 text-sm"
                          style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}>
                        <div className="font-semibold">{it.title || it.type || "Issue"}</div>
                        {it.description && <div className="text-xs mt-0.5">{it.description}</div>}
                      </li>
                    ))}
                  </ul>}
            </Section>

            <Section icon={StickyNote} title="Notes" testId="section-notes" count={job.notes ? 1 : 0}>
              {job.notes
                ? <div className="text-sm whitespace-pre-wrap p-3 rounded-lg"
                       style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                       data-testid="drawer-notes">{job.notes}</div>
                : <EmptyRow text="No notes." />}
            </Section>

            <Section icon={Wrench} title="Maintenance Log" testId="section-maint-log"
                     count={(job.maintenance_log || []).length}>
              {(job.maintenance_log || []).length === 0
                ? <EmptyRow text="No maintenance entries logged." />
                : <ul className="space-y-1.5" data-testid="drawer-maint-log">
                    {(job.maintenance_log || []).map((m, i) => (
                      <li key={i} className="text-sm border-l-2 pl-2"
                          style={{ borderColor: colors.brand, color: colors.onSurface }}>
                        <div className="font-semibold">{m.action || m.title}</div>
                        {m.detail && <div className="text-xs" style={{ color: colors.muted }}>{m.detail}</div>}
                      </li>
                    ))}
                  </ul>}
            </Section>

            <Section icon={PenTool} title="Signature" testId="section-signature"
                     count={job.signer_name || job.signature_svg ? 1 : 0}>
              {job.signature_svg || job.signer_name
                ? <div className="text-sm p-3 rounded-lg" style={{ backgroundColor: colors.surfaceSecondary }}
                       data-testid="drawer-signature">
                    <div style={{ color: colors.onSurface }}>Signed by <b>{job.signer_name}</b></div>
                    {job.signed_at && <div className="text-xs mt-1" style={{ color: colors.muted }}>
                      {(job.signed_at || "").slice(0, 19).replace("T", " ")}
                    </div>}
                    {job.signature_svg && (
                      <img src={job.signature_svg} alt="signature"
                           className="mt-2 max-h-24 bg-white rounded border" />
                    )}
                  </div>
                : <EmptyRow text="Not signed." />}
            </Section>
          </>}
        </div>

        <div className="px-5 py-3 flex items-center justify-between gap-2"
             style={{ borderTop: `1px solid ${colors.border}` }}>
          <button onClick={onClose}
                  className="px-3 py-2 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                  data-testid="drawer-close-footer">Close</button>
          {job && (
            <button onClick={() => { onClose(); navigate(`/jobs/${jobId}`); }}
                    className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-semibold text-white"
                    style={{ background: brandGradientCss }}
                    data-testid="drawer-open-full">
              Open full job page <ExternalLink size={13} />
            </button>
          )}
        </div>
      </aside>

      {lightbox && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4"
             style={{ backgroundColor: "rgba(0,0,0,0.85)" }}
             onClick={() => setLightbox(null)}
             data-testid="drawer-lightbox">
          <img src={lightbox} alt="preview" className="max-h-full max-w-full rounded-xl" />
        </div>
      )}

      {localToast && (
        <div className="fixed bottom-6 right-6 z-[70] px-4 py-2 rounded-xl text-sm text-white shadow-lg"
             style={{ backgroundColor: colors.onSurface }}
             data-testid="drawer-toast">
          {localToast}
        </div>
      )}
    </div>
  );
}

function Section({ icon: Icon, title, count, testId, children }) {
  return (
    <div data-testid={testId}>
      <div className="flex items-center gap-2 mb-2">
        <Icon size={14} style={{ color: colors.brand }} />
        <div className="text-xs font-bold uppercase tracking-wide" style={{ color: colors.onSurface }}>
          {title}
        </div>
        {count > 0 && (
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}>
            {count}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

function EmptyRow({ text }) {
  return <div className="text-xs italic" style={{ color: colors.muted }}>{text}</div>;
}

function ReadingsRender(job) {
  // Support two shapes: an array `chemical_readings` OR a single `reading_report` object.
  const arr = Array.isArray(job.chemical_readings) ? job.chemical_readings : null;
  const rr = job.reading_report && typeof job.reading_report === "object" ? job.reading_report : null;
  if ((!arr || arr.length === 0) && (!rr || Object.keys(rr).length === 0)) {
    return <EmptyRow text="No chemistry readings captured." />;
  }
  const rows = arr && arr.length ? arr : [rr];
  const fields = ["fc", "ph", "ta", "cya", "salt", "temperature"];
  return (
    <div className="rounded-lg overflow-hidden" style={{ border: `1px solid ${colors.border}` }}
         data-testid="drawer-readings">
      <table className="w-full text-xs">
        <thead>
          <tr style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}>
            <th className="text-left px-2 py-1.5 font-semibold">When</th>
            {fields.map((f) => <th key={f} className="text-right px-2 py-1.5 font-semibold uppercase">{f}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.filter(Boolean).map((r, i) => {
            const when = String(r?.at || r?.created_at || "");
            return (
              <tr key={i} style={{ borderTop: `1px solid ${colors.border}`, color: colors.onSurface }}>
                <td className="px-2 py-1.5 text-[11px]" style={{ color: colors.muted }}>
                  {when.slice(0, 10) || "—"}
                </td>
                {fields.map((f) => <td key={f} className="text-right px-2 py-1.5">{r?.[f] ?? "—"}</td>)}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
