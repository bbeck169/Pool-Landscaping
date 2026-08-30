/**
 * Phase S2 · Feb-2026 — Brand Brain tab.
 *
 * Read-only display of the tenant's ingested brand memory plus a
 * "Re-ingest from website" modal that calls
 * ``POST /api/soshie/ingest-website``.  Reads:
 *
 *   * ``GET /api/soshie/brand-brain`` — combined brand_brain +
 *     latest ingest metadata.
 */
import React, { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { RefreshCw, Globe, Loader2, Palette, MapPin,
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


function IngestModal({ open, onClose, onDone }) {
  const [url, setUrl] = useState("");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!url.trim()) {
      toast.error("Enter a website URL first");
      return;
    }
    setBusy(true);
    try {
      const idem = `bb-${Date.now()}`;
      await api.post("/soshie/ingest-website",
        { website_url: url.trim() },
        { headers: { "X-Idempotency-Key": idem } });
      toast.success("Website ingested — brand memory refreshed");
      onDone();
      onClose();
    } catch (e) {
      toast.error(e?.message || "Ingest failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose}
             title="Re-ingest brand memory"
             testid="brand-brain-ingest-modal"
             footer={
               <div className="flex gap-2 justify-end">
                 <Button variant="ghost" onClick={onClose}
                            testid="ingest-cancel"
                            disabled={busy}>Cancel</Button>
                 <Button onClick={submit}
                            testid="ingest-submit"
                            disabled={busy}>
                   {busy ? <><Loader2 className="animate-spin mr-1.5"
                                        size={14} />Ingesting…</>
                             : "Ingest website"}
                 </Button>
               </div>
             }>
      <div className="space-y-3">
        <TextInput label="Website URL" id="ingest-url"
                        placeholder="https://your-company.com"
                        value={url}
                        onChange={(e) => setUrl(e.target.value)}
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
                        data-testid="ingest-extra-input" />
          <p className="text-xs mt-1" style={{ color: colors.muted }}>
            Home page ingest is enough for most brands. Extra paths
            will be crawled if provided.
          </p>
        </div>
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
