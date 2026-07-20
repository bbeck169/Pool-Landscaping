import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft, Camera, Copy, Download, Layers, Sparkles, Trash2, Wand2,
  RefreshCw, Eye, MousePointerClick,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

const STYLES = [
  { v: "side_by_side", label: "Side-by-side" },
  { v: "stacked", label: "Stacked" },
  { v: "slider", label: "Slider preview" },
];
const SERVICE_TYPES = [
  "pool_cleaning", "tile_repair", "resurfacing",
  "landscape_before_after", "other",
];
const CREDIT_COST = 5;

function fileToDataUri(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

function DropZone({ label, value, onChange, testId }) {
  const inputRef = React.useRef();
  const onFile = async (f) => {
    if (!f) return;
    if (!/image\/(png|jpe?g|webp)/i.test(f.type)) {
      toast.error("Only PNG / JPG / WEBP images are supported");
      return;
    }
    if (f.size > 8 * 1024 * 1024) {
      toast.error("Image too large (max 8 MB)");
      return;
    }
    const uri = await fileToDataUri(f);
    onChange(uri);
  };
  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-3 items-center justify-center min-h-[240px] relative"
      style={{
        backgroundColor: colors.surfaceSecondary,
        border: `2px dashed ${colors.border}`,
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        onFile(e.dataTransfer.files?.[0]);
      }}
      data-testid={testId}
    >
      {value ? (
        <>
          <img
            src={value}
            alt={label}
            className="max-h-[240px] rounded-lg object-contain"
          />
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()}>
              Replace
            </Button>
            <Button
              variant="ghost" size="sm"
              onClick={() => onChange(null)}
              data-testid={`${testId}-clear`}
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        </>
      ) : (
        <>
          <Camera className="w-8 h-8" style={{ color: colors.muted }} />
          <div className="text-sm font-semibold">{label}</div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Drag &amp; drop or click to upload
          </div>
          <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()}>
            Choose file
          </Button>
        </>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => onFile(e.target.files?.[0])}
        data-testid={`${testId}-input`}
      />
    </div>
  );
}

export default function BeforeAfterStudio() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [balance, setBalance] = useState(null);
  const [beforeUri, setBeforeUri] = useState(null);
  const [afterUri, setAfterUri] = useState(null);
  const [style, setStyle] = useState("side_by_side");
  const [caption, setCaption] = useState("");
  const [serviceType, setServiceType] = useState("pool_cleaning");
  const [includeBranding, setIncludeBranding] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pair, setPair] = useState(null);
  const [gallery, setGallery] = useState([]);
  const [regenStyle, setRegenStyle] = useState("stacked");

  const load = useCallback(async () => {
    const [b, list] = await Promise.all([
      api.get("/ai-credits/balance").catch(() => null),
      api.get("/before-after/pairs?limit=24").catch(() => ({ pairs: [] })),
    ]);
    setBalance(b);
    setGallery(list.pairs || []);
  }, []);

  useEffect(() => { load(); }, [load]);

  const afterBal = (balance?.balance ?? 0) - CREDIT_COST;
  const lowBal = afterBal < 0.2 * (balance?.monthly_grant || 500);

  const shareUrl = (tok) =>
    tok ? `${window.location.origin}/api/before-after/public/${tok}` : "";

  const generate = async () => {
    if (!beforeUri || !afterUri) {
      toast.error("Both a before AND an after photo are required");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post("/before-after/generate", {
        before_photo_url: beforeUri,
        after_photo_url: afterUri,
        style,
        caption,
        service_type: serviceType,
        include_branding: includeBranding,
        job_id: sp.get("job_id") || null,
        customer_id: sp.get("customer_id") || null,
      });
      setPair(r.pair);
      if (r.pair.status === "error") {
        toast.error(`Compose failed: ${r.pair.error || "unknown"}`);
      } else {
        toast.success("Before/After card generated");
      }
      load();
    } catch (e) {
      toast.error(e?.message || "Generate failed");
    } finally {
      setBusy(false);
    }
  };

  const regen = async () => {
    if (!pair) return;
    setBusy(true);
    try {
      const r = await api.post(`/before-after/pairs/${pair.id}/regenerate`, {
        style: regenStyle,
      });
      setPair(r.pair);
      toast.success("Card regenerated");
      load();
    } catch (e) {
      toast.error(e?.message || "Regenerate failed");
    } finally {
      setBusy(false);
    }
  };

  const del = async (pid) => {
    if (!window.confirm("Delete this before/after pair?")) return;
    try {
      await api.delete(`/before-after/pairs/${pid}`);
      if (pair?.id === pid) setPair(null);
      load();
    } catch (e) {
      toast.error(e?.message || "Delete failed");
    }
  };

  const copyShare = (tok) => {
    if (!tok) return;
    navigator.clipboard.writeText(shareUrl(tok));
    toast.success("Share link copied");
  };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-4"
         data-testid="before-after-studio">
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl md:text-3xl font-bold"
              style={{ color: colors.onSurface }}>
            Before &amp; After Studio
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Turn a job photo pair into a branded share card. 5 credits per
            generation.
          </p>
        </div>
        {balance && (
          <Badge variant="outline" data-testid="ba-balance">
            Balance: <span className="ml-1 font-bold">{balance.balance}</span>
          </Badge>
        )}
      </div>

      <div className="rounded-2xl p-4 md:p-5 space-y-4"
           style={{ backgroundColor: colors.surface,
                     border: `1px solid ${colors.border}` }}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <DropZone label="BEFORE photo" value={beforeUri}
                     onChange={setBeforeUri} testId="ba-before" />
          <DropZone label="AFTER photo" value={afterUri}
                     onChange={setAfterUri} testId="ba-after" />
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <Label>Style</Label>
            <select className="w-full border rounded p-2 text-sm mt-1"
                    value={style}
                    onChange={(e) => setStyle(e.target.value)}
                    data-testid="ba-style">
              {STYLES.map((s) =>
                <option key={s.v} value={s.v}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <Label>Service type</Label>
            <select className="w-full border rounded p-2 text-sm mt-1"
                    value={serviceType}
                    onChange={(e) => setServiceType(e.target.value)}
                    data-testid="ba-service-type">
              {SERVICE_TYPES.map((s) =>
                <option key={s} value={s}>
                  {s.replace(/_/g, " ")}
                </option>)}
            </select>
          </div>
          <div className="col-span-2">
            <Label>Caption (optional)</Label>
            <Input value={caption}
                    onChange={(e) => setCaption(e.target.value)}
                    placeholder="e.g. 3-day salt cell replacement + polish"
                    className="mt-1"
                    data-testid="ba-caption" />
          </div>
        </div>

        <div className="flex items-center justify-between border-t pt-3 gap-3 flex-wrap"
             style={{ borderColor: colors.border }}>
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={includeBranding}
                     onCheckedChange={setIncludeBranding}
                     data-testid="ba-branding" />
            Include branding footer
          </label>
          <div className="text-sm" style={{ color: colors.muted }}>
            This will use <b>{CREDIT_COST}</b> credits · after: <b>{afterBal}</b>
            {lowBal && (
              <span className="ml-2 text-yellow-700">
                ⚠ low balance
              </span>
            )}
          </div>
          <Button onClick={generate} disabled={busy}
                    data-testid="ba-generate">
            <Sparkles className="w-4 h-4 mr-1" />
            {busy ? "Generating…" : "Generate card"}
          </Button>
        </div>
      </div>

      {pair && (
        <div className="rounded-2xl p-4 md:p-5"
              style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="ba-result">
          <div className="flex items-center gap-3 mb-3">
            <h2 className="font-semibold">Generated card</h2>
            {pair.status === "error"
              ? <Badge className="bg-red-500">error</Badge>
              : <Badge className="bg-emerald-500">{pair.status}</Badge>}
            <div className="ml-auto flex gap-2 items-center">
              <select value={regenStyle}
                       onChange={(e) => setRegenStyle(e.target.value)}
                       className="border rounded p-1 text-xs"
                       data-testid="ba-regen-style">
                {STYLES.map((s) => (
                  <option key={s.v} value={s.v}>{s.label}</option>
                ))}
              </select>
              <Button variant="outline" size="sm" onClick={regen}
                       disabled={busy}
                       data-testid="ba-regen">
                <RefreshCw className="w-3 h-3 mr-1" />
                Regenerate (5)
              </Button>
              <Button variant="outline" size="sm"
                       onClick={() => copyShare(pair.share_token)}
                       disabled={!pair.share_token}
                       data-testid="ba-copy-share">
                <Copy className="w-3 h-3 mr-1" />
                Copy link
              </Button>
              {pair.generated_card_url && (
                <a href={pair.generated_card_url}
                    target="_blank" rel="noreferrer"
                    className="inline-flex items-center rounded-md border px-2 py-1 text-xs"
                    data-testid="ba-download">
                  <Download className="w-3 h-3 mr-1" />
                  Open
                </a>
              )}
            </div>
          </div>
          {pair.error && (
            <div className="text-red-600 text-sm mb-2">{pair.error}</div>
          )}
          {pair.generated_card_url && (
            <img src={pair.generated_card_url}
                  alt="Generated card"
                  className="max-w-full rounded-lg border"
                  style={{ borderColor: colors.border }} />
          )}
          {pair.share_token && (
            <div className="text-xs mt-2" style={{ color: colors.muted }}>
              Share link:{" "}
              <span className="font-mono break-all">
                {shareUrl(pair.share_token)}
              </span>
            </div>
          )}
        </div>
      )}

      <div className="rounded-2xl p-4 md:p-5"
           style={{ backgroundColor: colors.surface,
                     border: `1px solid ${colors.border}` }}>
        <div className="flex items-center gap-3 mb-3">
          <Layers className="w-4 h-4" />
          <h2 className="font-semibold">Recent pairs</h2>
          <span className="text-xs" style={{ color: colors.muted }}>
            {gallery.length} loaded
          </span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {gallery.map((p) => (
            <div key={p.id}
                  className="rounded-lg overflow-hidden"
                  style={{ backgroundColor: colors.surfaceSecondary,
                           border: `1px solid ${colors.border}` }}
                  data-testid={`ba-gallery-${p.id}`}>
              {p.generated_card_url ? (
                <img src={p.generated_card_url} alt=""
                      className="w-full h-32 object-cover" />
              ) : (
                <div className="w-full h-32 flex items-center justify-center text-xs text-red-600">
                  {p.status || "pending"}
                </div>
              )}
              <div className="p-2 text-xs space-y-1">
                <div className="flex items-center gap-1">
                  <Badge variant="outline" className="text-[10px]">
                    {p.style}
                  </Badge>
                  {p.service_type && (
                    <span style={{ color: colors.muted }}>
                      {p.service_type.replace(/_/g, " ")}
                    </span>
                  )}
                </div>
                {p.caption && <div className="truncate">{p.caption}</div>}
                <div className="flex items-center gap-2 pt-0.5"
                      style={{ color: colors.muted }}
                      data-testid={`ba-stats-${p.id}`}>
                  <span className="inline-flex items-center gap-0.5"
                         title="Impressions on public share">
                    <Eye className="w-3 h-3" /> {Number(p.impressions_count || 0)}
                  </span>
                  <span className="inline-flex items-center gap-0.5"
                         title="Clicks on public share">
                    <MousePointerClick className="w-3 h-3" /> {Number(p.click_count || 0)}
                  </span>
                </div>
                <div className="flex gap-1 justify-end">
                  <button onClick={() => copyShare(p.share_token)}
                          className="p-1 hover:brightness-95 rounded"
                          title="Copy share link">
                    <Copy className="w-3 h-3" />
                  </button>
                  <button onClick={() => setPair(p)}
                          className="p-1 hover:brightness-95 rounded"
                          title="Open">
                    <Wand2 className="w-3 h-3" />
                  </button>
                  <button onClick={() => del(p.id)}
                          className="p-1 hover:brightness-95 rounded text-red-600"
                          title="Delete">
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
            </div>
          ))}
          {gallery.length === 0 && (
            <div className="col-span-full text-center text-sm py-8"
                  style={{ color: colors.muted }}>
              No before/after pairs yet — generate your first one above.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
