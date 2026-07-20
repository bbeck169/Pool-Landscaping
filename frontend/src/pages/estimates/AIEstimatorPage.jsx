import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Sparkles, Upload, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";

const $ = (c) => `$${((c || 0) / 100).toFixed(2)}`;

/**
 * QuoteIQ Q2-UI · AI Estimator page.
 *
 * Wizard: photos → description → optional customer/pool ctx → options
 * toggle → Generate. Result: editable line-items or 3 tier cards, plus
 * Promote button. Shows credit-cost preview + warning banner from the
 * balance endpoint.
 */
export default function AIEstimatorPage() {
  const navigate = useNavigate();
  const [balance, setBalance] = useState(null);
  const [desc, setDesc] = useState("");
  const [photos, setPhotos] = useState([]);
  const [customerId, setCustomerId] = useState("");
  const [customers, setCustomers] = useState([]);
  const [poolGallons, setPoolGallons] = useState("");
  const [sqft, setSqft] = useState("");
  const [optionsMode, setOptionsMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState(null);
  const [drafts, setDrafts] = useState([]);

  const load = useCallback(async () => {
    const [b, cs, ds] = await Promise.all([
      api.get("/ai-credits/balance").catch(() => null),
      api.get("/customers?limit=200").catch(() => []),
      api.get("/ai-estimator/drafts?limit=10").catch(() => ({ drafts: [] })),
    ]);
    setBalance(b);
    setCustomers(Array.isArray(cs) ? cs : cs.customers || []);
    setDrafts(ds.drafts || []);
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const cost = optionsMode ? 20 : 10;
  const afterBalance = (balance?.balance ?? 0) - cost;

  const addPhotoUrl = () => {
    const url = prompt(
      "Photo URL (paste an image URL — for upload UI use the media library in a follow-up):",
    );
    if (url) setPhotos([...photos, url]);
  };

  const submit = async () => {
    if (!desc.trim()) {
      toast.error("Description required");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post("/ai-estimator/generate", {
        photo_urls: photos,
        job_description: desc,
        customer_id: customerId || null,
        pool_size_gallons: poolGallons ? parseInt(poolGallons, 10) : null,
        service_area_sqft: sqft ? parseFloat(sqft) : null,
        options_mode: optionsMode,
      });
      setDraft(r.draft);
      if (r.credit_warning)
        toast.warning("Low balance after this generation — consider a top-up.");
      else toast.success("Draft generated");
      load();
    } catch (e) {
      toast.error(e?.message || "Generation failed");
    } finally {
      setBusy(false);
    }
  };

  const promote = async () => {
    if (!draft) return;
    if (!customerId) {
      toast.error("Pick a customer to promote to an estimate.");
      return;
    }
    try {
      const r = await api.post(
        `/ai-estimator/drafts/${draft.id}/promote`,
        { customer_id: customerId, title: desc.slice(0, 80) },
      );
      toast.success("Estimate created");
      navigate(`/estimates/${r.estimate_id}`);
    } catch (e) {
      toast.error(e?.message || "Promote failed");
    }
  };

  return (
    <div className="p-6 space-y-4 max-w-6xl mx-auto" data-testid="ai-estimator-page">
      <div className="flex items-center gap-3">
        <Sparkles className="w-6 h-6 text-sky-600" />
        <h1 className="text-2xl font-semibold">AI Estimator</h1>
        {balance && (
          <div className="ml-auto text-sm text-muted-foreground">
            Balance: <span className="font-semibold">{balance.balance}</span> · Plan:{" "}
            <Badge variant="outline">{balance.plan}</Badge>
          </div>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">1) Describe the job</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            rows={3}
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder="e.g. Weekly service for backyard 20000 gal plaster pool, salt system, moderate leaf load…"
            data-testid="ai-est-desc"
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div>
              <Label>Customer</Label>
              <select
                className="w-full border rounded p-2 text-sm"
                value={customerId}
                onChange={(e) => setCustomerId(e.target.value)}
                data-testid="ai-est-customer"
              >
                <option value="">— none —</option>
                {customers.slice(0, 200).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name || c.email}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Label>Pool gallons</Label>
              <Input
                value={poolGallons}
                onChange={(e) => setPoolGallons(e.target.value)}
                type="number"
              />
            </div>
            <div>
              <Label>Area sqft</Label>
              <Input value={sqft} onChange={(e) => setSqft(e.target.value)} type="number" />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm">
                <Switch
                  checked={optionsMode}
                  onCheckedChange={setOptionsMode}
                  data-testid="ai-est-options"
                />
                Good/Better/Best
              </label>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Upload className="w-4 h-4" />
            2) Photos ({photos.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2 flex-wrap">
            {photos.map((u, i) => (
              <div key={i} className="relative border rounded p-1">
                <img src={u} alt="" className="h-20 rounded" />
                <button
                  onClick={() => setPhotos(photos.filter((_, idx) => idx !== i))}
                  className="absolute -top-2 -right-2 bg-red-500 rounded-full text-white p-1"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))}
            <Button variant="outline" onClick={addPhotoUrl} data-testid="ai-est-add-photo">
              Add photo URL
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3 border-t pt-4">
        <div className="text-sm text-muted-foreground">
          This will use <span className="font-semibold">{cost}</span> credits.
          Balance after: <span className="font-semibold">{afterBalance}</span>
          {afterBalance <
            0.2 * (balance?.monthly_grant || 500) && (
            <span className="ml-2 text-yellow-700">⚠ low balance</span>
          )}
        </div>
        <Button
          className="ml-auto"
          onClick={submit}
          disabled={busy}
          data-testid="ai-est-generate"
        >
          <Sparkles className="w-4 h-4 mr-1" />
          {busy ? "Generating…" : "Generate"}
        </Button>
      </div>

      {draft && (
        <Card data-testid="ai-est-result">
          <CardHeader className="flex flex-row items-center gap-3">
            <CardTitle className="text-base">Draft</CardTitle>
            {draft.status === "error" ? (
              <Badge className="bg-red-500">error</Badge>
            ) : (
              <Badge className="bg-emerald-500">{draft.status}</Badge>
            )}
            <span className="ml-auto text-sm text-muted-foreground">
              Suggested total: <strong>{$(draft.suggested_total_cents)}</strong>
            </span>
          </CardHeader>
          <CardContent>
            {draft.status === "error" && (
              <div className="text-red-700 text-sm">{draft.error}</div>
            )}
            {draft.options_mode && draft.tiers?.length ? (
              <div className="grid gap-3 md:grid-cols-3">
                {draft.tiers.map((t) => (
                  <div
                    key={t.id}
                    className={`border rounded p-3 ${
                      t.is_default ? "border-sky-500 bg-sky-50" : ""
                    }`}
                    data-testid={`ai-est-tier-${t.name.toLowerCase()}`}
                  >
                    <div className="font-semibold">
                      {t.name} {t.is_default && "(default)"}
                    </div>
                    <div className="text-xs text-muted-foreground mb-2">
                      {t.description}
                    </div>
                    <div className="text-sm">{$(t.total_cents)}</div>
                    <ul className="mt-2 text-xs space-y-1">
                      {(t.line_items || []).map((li, i) => (
                        <li key={i}>
                          {li.description} · {li.qty} × {$(li.unit_price_cents)}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground uppercase">
                    <th>Item</th>
                    <th className="text-right">Qty</th>
                    <th className="text-right">Unit</th>
                    <th className="text-right">Subtotal</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {(draft.line_items || []).map((li, i) => (
                    <tr key={i} className="border-b">
                      <td>{li.description}</td>
                      <td className="text-right">{li.qty}</td>
                      <td className="text-right">{$(li.unit_price_cents)}</td>
                      <td className="text-right font-semibold">
                        {$(li.subtotal_cents)}
                      </td>
                      <td>
                        <Badge variant="outline" className="text-[10px]">
                          {li.source}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="mt-4 flex gap-2">
              <Button
                onClick={promote}
                disabled={draft.status !== "complete"}
                data-testid="ai-est-promote"
              >
                Promote to estimate
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setDraft(null);
                  setDesc("");
                  setPhotos([]);
                }}
              >
                New draft
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Recent drafts</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <tbody>
              {drafts.map((d) => (
                <tr key={d.id} className="border-b">
                  <td className="py-2">{d.job_description?.slice(0, 60)}…</td>
                  <td>
                    <Badge variant="outline">{d.status}</Badge>
                  </td>
                  <td className="text-right">{$(d.suggested_total_cents)}</td>
                  <td className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setDraft(d)}
                    >
                      Open
                    </Button>
                  </td>
                </tr>
              ))}
              {drafts.length === 0 && (
                <tr>
                  <td className="text-muted-foreground py-4 text-center" colSpan={4}>
                    No drafts yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
