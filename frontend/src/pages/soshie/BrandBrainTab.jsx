/**
 * Phase S2 · Feb-2026 — Brand Brain tab.
 *
 * Feb 2026 · Phase I4 — Async ingest job.  The "Re-ingest from
 * website" modal used to await the sync ``POST /soshie/ingest-website``
 * response, which timed out at 30s on cold crawls of large sites.
 * The endpoint is now fire-and-forget (returns 202 with a job_id);
 * this component polls ``GET /soshie/brand-brain/ingest/latest``
 * every 5s while the modal is open, and renders a top-of-page
 * banner on mount if a prior job is still running.
 *
 * Reads:
 *
 *   * ``GET /api/soshie/brand-brain`` — combined brand_brain +
 *     latest ingest metadata.
 *   * ``GET /api/soshie/brand-brain/ingest/latest`` — latest job
 *     row (any status) for the current tenant. Drives the
 *     resume-banner + modal poll.
 */
import React, { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import { RefreshCw, Globe, Loader2, MapPin,
           MessageSquare } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button, Skeleton, EmptyState, Modal, TextInput }
  from "@/components/ui-kit";


function Card({ children, className = "", testId }) {
  return (
    <div className={`rounded-2xl p-5 ${className}`}
         style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
         data-testid={testId}>
      {children}
    </div>
  );
}


function Section({ title, icon: Icon, children, testId }) {
  return (
    <Card testId={testId} className="mb-4">
      <div className="flex items-center gap-2 mb-3">
        {Icon ? <Icon size={16} style={{ color: colors.muted }} /> : null}
        <h3 className="text-sm font-semibold"
            style={{ color: colors.onSurface }}>{title}</h3>
      </div>
      <div className="text-sm" style={{ color: colors.onSurface }}>
        {children}
      </div>
    </Card>
  );
}


// Phase I4 · Feb-2026 — poll interval for the async ingest job.
const INGEST_POLL_MS = 5000;
const _isTerminal = (s) => s === "succeeded" || s === "failed";


function IngestModal({ open, onClose, onDone }) {
  const [url, setUrl] = useState("");
  const [extra, setExtra] = useState("");
  const [job, setJob] = useState(null);
  const [busy, setBusy] = useState(false);
  const pollTimer = useRef(null);

  const clearPoll = () => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  };

  useEffect(() => {
    if (!open) {
      clearPoll();
      return;
    }
    return clearPoll;
  }, [open]);

  const pollOnce = useCallback(async () => {
    try {
      const r = await api.get("/soshie/brand-brain/ingest/latest");
      const latest = r?.job || null;
      if (!latest) return;
      setJob(latest);
      if (_isTerminal(latest.status)) {
        clearPoll();
        if (latest.status === "succeeded") {
          toast.success("Brand memory ingest complete.");
          onDone?.();
          onClose?.();
        }
        // On failure keep the modal open so the operator can Retry.
      }
    } catch { /* silent — poll retries */ }
  }, [onClose, onDone]);

  const submit = async () => {
    if (!url.trim()) {
      toast.error("Enter a website URL first");
      return;
    }
    const extraPaths = extra.split("\n").map((s) => s.trim()).filter(Boolean);
    setBusy(true);
    try {
      const posted = await api.post(
        "/soshie/brand-brain/ingest",
        { website_url: url.trim(), extra_paths: extraPaths },
      );
      setJob(posted);
      // Kick a poll cycle immediately + on interval so the operator
      // sees status transition without waiting a full 5s.
      clearPoll();
      pollTimer.current = setInterval(pollOnce, INGEST_POLL_MS);
      pollOnce();
    } catch (e) {
      toast.error(e?.message || "Ingest failed to start");
    } finally {
      setBusy(false);
    }
  };

  const retry = () => {
    setJob(null);
    submit();
  };

  const inFlight = job && !_isTerminal(job.status);
  const failed = job && job.status === "failed";

  return (
    <Modal open={open} onClose={onClose}
             title="Re-ingest brand memory"
             testid="brand-brain-ingest-modal"
             footer={
               <div className="flex gap-2 justify-end"
                     data-testid="ingest-modal-footer">
                 <Button variant="ghost" onClick={onClose}
                            testid="ingest-cancel"
                            disabled={busy}>
                   {inFlight ? "Close (keeps running)" : "Cancel"}
                 </Button>
                 {failed ? (
                   <Button onClick={retry} testid="ingest-retry"
                              disabled={busy}>
                     Retry
                   </Button>
                 ) : inFlight ? (
                   <Button disabled testid="ingest-in-flight">
                     <Loader2 className="animate-spin mr-1.5"
                                 size={14} />
                     Ingesting…
                   </Button>
                 ) : (
                   <Button onClick={submit} testid="ingest-submit"
                              disabled={busy}>
                     {busy ? "Starting…" : "Ingest website"}
                   </Button>
                 )}
               </div>
             }>
      <div className="space-y-3">
        <TextInput label="Website URL" id="ingest-url"
                        placeholder="https://your-company.com"
                        value={url}
                        onChange={(e) => setUrl(e.target.value)}
                        disabled={inFlight}
                        testid="ingest-url-input" />
        <div>
          <label className="block text-xs font-semibold mb-1"
                    style={{ color: colors.muted }}
                    htmlFor="ingest-extra">
            Optional additional paths (one per line)
          </label>
          <textarea id="ingest-extra"
                        className="w-full px-3 py-2 rounded-lg text-sm"
                        style={{ backgroundColor: colors.surfaceSecondary,
                                    border: `1px solid ${colors.border}`,
                                    color: colors.onSurface,
                                    minHeight: 80 }}
                        placeholder={"/services\n/about"}
                        value={extra}
                        onChange={(e) => setExtra(e.target.value)}
                        disabled={inFlight}
                        data-testid="ingest-extra-input" />
          <p className="text-xs mt-1" style={{ color: colors.muted }}>
            Home page ingest is enough for most brands. Extra paths
            will be crawled if provided. Up to 4 extras (5 pages total).
          </p>
        </div>

        {/* Phase I4 · Feb-2026 — progress indicator while a job is
             in flight. Persists across modal-close via the
             GET /ingest/latest poll on next open. */}
        {job ? (
          <div className="rounded-lg p-3 mt-3"
                   style={{
                     background: failed ? "#FEE2E2"
                                : job.status === "succeeded"
                                  ? "#DCFCE7"
                                  : "#DBEAFE",
                     color: failed ? "#991B1B"
                             : job.status === "succeeded"
                               ? "#166534"
                               : "#1E3A8A",
                     border: `1px solid ${failed ? "#FCA5A5"
                                    : job.status === "succeeded"
                                       ? "#86EFAC" : "#93C5FD"}`,
                   }}
                   data-testid="ingest-progress">
            <div className="text-xs font-bold uppercase tracking-wider mb-1"
                     data-testid="ingest-progress-status">
              {job.status}
            </div>
            {inFlight ? (
              <div className="text-sm"
                       data-testid="ingest-progress-body">
                Ingest in progress — this can take 1–3 minutes. You can close
                this modal and check back.
                <div className="mt-1 font-mono text-xs"
                         data-testid="ingest-progress-counter">
                  Step: {job.progress?.current_step || "…"} · Pages{" "}
                  {job.progress?.paths_crawled ?? 0}/
                  {job.progress?.paths_total ?? 0}
                </div>
              </div>
            ) : failed ? (
              <div className="text-sm"
                       data-testid="ingest-progress-error">
                Ingest failed: {job.error || "unknown error"}
              </div>
            ) : (
              <div className="text-sm">
                Ingest complete — {job.result_summary?.pages_fetched ?? 0}{" "}
                page{(job.result_summary?.pages_fetched ?? 0) === 1
                     ? "" : "s"} · {job.result_summary?.bullets_added ?? 0}{" "}
                new talking point(s).
              </div>
            )}
          </div>
        ) : null}
      </div>
    </Modal>
  );
}


export default function BrandBrainTab() {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [data, setData] = useState({ brand_brain: null,
                                          latest_ingest: null });
  const [ingestOpen, setIngestOpen] = useState(false);
  // Phase I4 · Feb-2026 — resume-banner state. Populated on mount
  // via GET /ingest/latest so a page reload after leaving the
  // modal open surfaces the "still running" hint.
  const [runningJob, setRunningJob] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/soshie/brand-brain");
      setData(r || {});
      setErr("");
    } catch (e) {
      setErr(e?.message || "Couldn't load brand memory");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  // Phase I4 — check for a still-running ingest on mount.
  const loadRunningJob = useCallback(async () => {
    try {
      const r = await api.get("/soshie/brand-brain/ingest/latest");
      const latest = r?.job || null;
      if (latest && !_isTerminal(latest.status)) {
        setRunningJob(latest);
      } else {
        setRunningJob(null);
      }
    } catch { /* silent */ }
  }, []);
  useEffect(() => { loadRunningJob(); }, [loadRunningJob]);

  if (loading) {
    return (
      <div className="space-y-4" data-testid="brand-brain-loading">
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-32 rounded-2xl" />
        <Skeleton className="h-24 rounded-2xl" />
      </div>
    );
  }
  if (err) {
    return (
      <Card testId="brand-brain-error">
        <p className="text-sm" style={{ color: colors.error }}>{err}</p>
      </Card>
    );
  }

  const bb = data.brand_brain || {};
  const ingest = data.latest_ingest;
  const isEmpty = !bb.tone && !bb.audience
                    && !(bb.talking_points || []).length
                    && !ingest;

  if (isEmpty) {
    return (
      <Card testId="brand-brain-empty">
        <EmptyState
          icon={Globe}
          title="No brand memory yet"
          hint="Ingest your website to teach Soshie your voice, services, and region."
          action={
            <Button onClick={() => setIngestOpen(true)}
                       testid="ingest-empty-cta">
              Ingest your website
            </Button>
          }
        />
        <IngestModal open={ingestOpen}
                          onClose={() => setIngestOpen(false)}
                          onDone={load} />
      </Card>
    );
  }

  return (
    <div className="space-y-4" data-testid="brand-brain-content">
      {runningJob ? (
        <div className="rounded-lg px-4 py-2 flex items-center gap-2 text-sm"
             style={{
               background: "#DBEAFE", color: "#1E3A8A",
               border: "1px solid #93C5FD",
             }}
             data-testid="brand-brain-resume-banner">
          <Loader2 className="animate-spin" size={14} />
          <span>
            Ingest in progress —
            {" "}
            {runningJob.progress?.current_step || "starting"}
            {" · "}
            {runningJob.progress?.paths_crawled ?? 0}/
            {runningJob.progress?.paths_total ?? 0} pages.
          </span>
          <Button variant="ghost"
                     onClick={() => setIngestOpen(true)}
                     testid="brand-brain-resume-open">
            Open modal
          </Button>
        </div>
      ) : null}
      <Card testId="brand-brain-header">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h2 className="text-lg font-semibold"
                style={{ color: colors.onSurface }}>Brand memory</h2>
            {ingest ? (
              <p className="text-xs mt-1"
                    style={{ color: colors.muted }}
                    data-testid="brand-brain-last-ingest">
                Last ingested{" "}
                {ingest.ingested_at
                  ? new Date(ingest.ingested_at).toLocaleDateString()
                  : "recently"}
                {ingest.url ? ` · ${ingest.url}` : ""}
              </p>
            ) : (
              <p className="text-xs mt-1"
                    style={{ color: colors.muted }}
                    data-testid="brand-brain-manual">
                Brand memory is manually authored (no website ingest yet).
              </p>
            )}
          </div>
          <Button onClick={() => setIngestOpen(true)}
                     testid="brand-brain-reingest-btn"
                     variant="ghost">
            <RefreshCw size={14} className="mr-1.5" />
            Re-ingest from website
          </Button>
        </div>
      </Card>

      {bb.tone ? (
        <Section title="Brand voice / tone"
                  icon={MessageSquare} testId="section-tone">
          <p data-testid="brand-brain-tone">{bb.tone}</p>
          {bb.brand_voice_snippet ? (
            <p className="mt-2 text-xs italic"
                style={{ color: colors.muted }}
                data-testid="brand-brain-voice-snippet">
              "{bb.brand_voice_snippet}"
            </p>
          ) : null}
        </Section>
      ) : null}

      {bb.audience ? (
        <Section title="Target audience" testId="section-audience">
          <p data-testid="brand-brain-audience">{bb.audience}</p>
        </Section>
      ) : null}

      {(bb.talking_points || []).length ? (
        <Section title="Key talking points"
                  testId="section-talking-points">
          <ul className="list-disc pl-5 space-y-1"
              data-testid="brand-brain-talking-points">
            {bb.talking_points.map((p, i) => (<li key={i}>{p}</li>))}
          </ul>
        </Section>
      ) : null}

      {(bb.do_say || []).length || (bb.dont_say || []).length ? (
        <Section title="Voice guardrails" testId="section-guardrails">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <div className="text-xs font-semibold mb-1"
                    style={{ color: colors.muted }}>DO SAY</div>
              <ul className="list-disc pl-5 space-y-0.5 text-sm"
                    data-testid="brand-brain-do-say">
                {(bb.do_say || []).map((p, i) => (<li key={i}>{p}</li>))}
                {!(bb.do_say || []).length ? (
                  <li style={{ color: colors.muted }}>—</li>
                ) : null}
              </ul>
            </div>
            <div>
              <div className="text-xs font-semibold mb-1"
                    style={{ color: colors.muted }}>DON'T SAY</div>
              <ul className="list-disc pl-5 space-y-0.5 text-sm"
                    data-testid="brand-brain-dont-say">
                {(bb.dont_say || []).map((p, i) => (<li key={i}>{p}</li>))}
                {!(bb.dont_say || []).length ? (
                  <li style={{ color: colors.muted }}>—</li>
                ) : null}
              </ul>
            </div>
          </div>
        </Section>
      ) : null}

      {ingest && (ingest.service_summary || (ingest.headings || []).length) ? (
        <Section title="Ingested website details"
                  icon={MapPin} testId="section-ingest">
          {ingest.service_summary ? (
            <p className="mb-2" data-testid="brand-brain-service-summary">
              {ingest.service_summary}
            </p>
          ) : null}
          {(ingest.headings || []).length ? (
            <div>
              <div className="text-xs font-semibold mb-1"
                    style={{ color: colors.muted }}>Headings pulled</div>
              <ul className="list-disc pl-5 text-sm"
                    data-testid="brand-brain-headings">
                {ingest.headings.slice(0, 8).map((h, i) => (
                  <li key={i}>{h}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </Section>
      ) : null}

      <IngestModal open={ingestOpen}
                        onClose={() => setIngestOpen(false)}
                        onDone={load} />
    </div>
  );
}
