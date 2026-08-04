import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { GitBranch, Plus, Search, DollarSign, Trophy, XCircle } from "lucide-react";

const centsToDollars = (c) =>
  `$${((c || 0) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

/**
 * QuoteIQ Q1-UI · Pipelines CRM Kanban board.
 *
 * Native HTML5 drag-drop between stage columns (no dnd library — keeps
 * bundle lean). Optimistic UI with rollback on API failure. Deal
 * detail drawer with events timeline + action buttons.
 */
export default function DealsKanbanPage() {
  const [pipelines, setPipelines] = useState([]);
  const [activePipeline, setActivePipeline] = useState(null);
  const [view, setView] = useState(null); // { pipeline, columns: [{stage, deals[], ...}] }
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [detailDeal, setDetailDeal] = useState(null); // opens drawer
  const [newDealOpen, setNewDealOpen] = useState(false);
  const [pipelineDialogOpen, setPipelineDialogOpen] = useState(false);

  const loadPipelines = useCallback(async () => {
    const d = await api.get("/deal-pipelines");
    setPipelines(d.pipelines || []);
    if (!activePipeline && d.pipelines?.length) {
      const def = d.pipelines.find((p) => p.is_default) || d.pipelines[0];
      setActivePipeline(def.id);
    }
  }, [activePipeline]);

  const loadView = useCallback(async () => {
    if (!activePipeline) return;
    setLoading(true);
    try {
      const d = await api.get(
        `/deals/pipeline-view?pipeline_id=${activePipeline}`,
      );
      setView(d);
    } finally {
      setLoading(false);
    }
  }, [activePipeline]);

  useEffect(() => {
    loadPipelines();
  }, [loadPipelines]);

  useEffect(() => {
    loadView();
  }, [loadView]);

  const filteredColumns = useMemo(() => {
    if (!view) return [];
    const needle = q.trim().toLowerCase();
    if (!needle) return view.columns;
    return view.columns.map((col) => ({
      ...col,
      deals: (col.deals || []).filter(
        (d) =>
          (d.title || "").toLowerCase().includes(needle) ||
          (d.contact_name || "").toLowerCase().includes(needle) ||
          (d.contact_email || "").toLowerCase().includes(needle),
      ),
    }));
  }, [view, q]);

  const onDragStart = (e, dealId, fromStageId) => {
    e.dataTransfer.setData("text/plain", JSON.stringify({ dealId, fromStageId }));
    e.dataTransfer.effectAllowed = "move";
  };

  const onDropTo = async (e, toStageId) => {
    e.preventDefault();
    const raw = e.dataTransfer.getData("text/plain");
    if (!raw) return;
    let payload;
    try {
      payload = JSON.parse(raw);
    } catch {
      return;
    }
    const { dealId, fromStageId } = payload;
    if (!dealId || fromStageId === toStageId) return;
    // Optimistic UI.
    const prev = view;
    const next = {
      ...view,
      columns: view.columns.map((c) => ({ ...c, deals: [...(c.deals || [])] })),
    };
    let moved = null;
    for (const col of next.columns) {
      const idx = col.deals.findIndex((d) => d.id === dealId);
      if (idx !== -1) {
        moved = col.deals.splice(idx, 1)[0];
        col.deal_count = (col.deals || []).length;
        col.total_value_cents = col.deals.reduce(
          (s, d) => s + (d.value_cents || 0),
          0,
        );
        break;
      }
    }
    if (moved) {
      const target = next.columns.find((c) => c.stage.id === toStageId);
      if (target) {
        moved.stage_id = toStageId;
        target.deals.unshift(moved);
        target.deal_count = target.deals.length;
        target.total_value_cents = target.deals.reduce(
          (s, d) => s + (d.value_cents || 0),
          0,
        );
        setView(next);
      }
    }
    try {
      await api.post(`/deals/${dealId}/move`, { stage_id: toStageId });
      toast.success("Deal moved");
      loadView();
    } catch (err) {
      setView(prev);
      toast.error(err?.message || "Move failed — reverted");
    }
  };

  return (
    <div className="p-6 space-y-4" data-testid="deals-kanban-page">
      <div className="flex items-center gap-3 flex-wrap">
        <GitBranch className="w-6 h-6 text-sky-600" />
        <h1 className="text-2xl font-semibold tracking-tight">Deals</h1>
        <div className="ml-auto flex gap-2 items-center flex-wrap">
          <Select value={activePipeline || ""} onValueChange={setActivePipeline}>
            <SelectTrigger className="w-64" data-testid="deals-pipeline-select">
              <SelectValue placeholder="Choose pipeline" />
            </SelectTrigger>
            <SelectContent>
              {pipelines.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name}
                  {p.is_default ? " (default)" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="relative">
            <Search className="w-4 h-4 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-8 w-52"
              placeholder="Search deals…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              data-testid="deals-search"
            />
          </div>
          <Button
            variant="outline"
            onClick={() => setPipelineDialogOpen(true)}
            data-testid="deals-pipeline-editor"
          >
            Edit pipeline
          </Button>
          <Button
            onClick={() => setNewDealOpen(true)}
            data-testid="deals-new"
          >
            <Plus className="w-4 h-4 mr-1" />
            New deal
          </Button>
        </div>
      </div>

      {loading && !view ? (
        <div className="p-8 text-center text-muted-foreground">Loading…</div>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-4">
          {filteredColumns.map((col) => (
            <div
              key={col.stage.id}
              className="min-w-[280px] max-w-[300px] flex-1 flex flex-col rounded-md border bg-gray-50"
              onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
              }}
              onDrop={(e) => onDropTo(e, col.stage.id)}
              data-testid={`deals-column-${col.stage.name.toLowerCase().replace(/\s+/g, "-")}`}
            >
              <div
                className="px-3 py-2 border-b flex items-center gap-2"
                style={{ borderTop: `3px solid ${col.stage.color || "#94A3B8"}` }}
              >
                <div className="font-medium text-sm">{col.stage.name}</div>
                <Badge variant="outline" className="text-xs">
                  {col.deal_count}
                </Badge>
                <div className="ml-auto text-xs text-muted-foreground flex items-center gap-1">
                  <DollarSign className="w-3 h-3" />
                  {centsToDollars(col.total_value_cents).replace("$", "")}
                </div>
              </div>
              <div className="p-2 space-y-2 flex-1 min-h-[100px]">
                {(col.deals || []).map((d) => (
                  <DealCard
                    key={d.id}
                    deal={d}
                    onOpen={() => setDetailDeal(d)}
                    onDragStart={(e) => onDragStart(e, d.id, col.stage.id)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {detailDeal && (
        <DealDetailDrawer
          deal={detailDeal}
          onClose={() => setDetailDeal(null)}
          onChanged={() => {
            loadView();
          }}
          pipeline={view?.pipeline}
        />
      )}

      {newDealOpen && (
        <NewDealDialog
          pipeline={view?.pipeline}
          onClose={() => setNewDealOpen(false)}
          onCreated={() => {
            setNewDealOpen(false);
            loadView();
          }}
        />
      )}

      {pipelineDialogOpen && (
        <PipelineEditorDialog
          pipeline={view?.pipeline}
          onClose={() => setPipelineDialogOpen(false)}
          onSaved={() => {
            setPipelineDialogOpen(false);
            loadPipelines();
            loadView();
          }}
        />
      )}
    </div>
  );
}

function DealCard({ deal, onOpen, onDragStart }) {
  const won = deal.status === "won";
  const lost = deal.status === "lost";
  return (
    <div
      draggable
      onDragStart={onDragStart}
      onClick={onOpen}
      className={`cursor-grab active:cursor-grabbing p-3 rounded border bg-white hover:shadow-sm ${
        won ? "border-emerald-500 bg-emerald-50/40" : ""
      } ${lost ? "border-red-400 bg-red-50/40 opacity-70" : ""}`}
      data-testid={`deal-card-${deal.id}`}
    >
      <div className="font-medium text-sm truncate">{deal.title}</div>
      <div className="text-xs text-muted-foreground truncate">
        {deal.contact_name || "—"}
      </div>
      <div className="mt-2 flex items-center justify-between text-xs">
        <span className="font-semibold text-sky-700">
          {centsToDollars(deal.value_cents)}
        </span>
        <span className="text-muted-foreground">
          {deal.probability_pct}%
        </span>
      </div>
      {(deal.tags || []).length > 0 && (
        <div className="mt-1 flex gap-1 flex-wrap">
          {deal.tags.slice(0, 3).map((t) => (
            <Badge key={t} variant="outline" className="text-[10px] py-0">
              {t}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function DealDetailDrawer({ deal, onClose, onChanged, _pipeline }) {
  const [current, setCurrent] = useState(deal);
  const [events, setEvents] = useState([]);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const [d, e] = await Promise.all([
      api.get(`/deals/${deal.id}`),
      api.get(`/deals/${deal.id}/events`),
    ]);
    setCurrent(d);
    setEvents(e.events || []);
  }, [deal.id]);

  useEffect(() => {
    reload();
  }, [reload]);

  const save = async () => {
    setBusy(true);
    try {
      await api.patch(`/deals/${deal.id}`, {
        title: current.title,
        value_cents: parseInt(current.value_cents, 10) || 0,
        contact_name: current.contact_name,
        contact_email: current.contact_email,
        contact_phone: current.contact_phone,
        expected_close_date: current.expected_close_date || null,
        notes: current.notes,
        tags: current.tags,
      });
      toast.success("Deal updated");
      await reload();
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const markWon = async () => {
    await api.post(`/deals/${deal.id}/won`);
    toast.success("Marked won");
    await reload();
    onChanged();
  };

  const markLost = async () => {
    const reason = prompt("Reason for losing this deal?") || "";
    await api.post(`/deals/${deal.id}/lost`, { lost_reason: reason });
    toast.success("Marked lost");
    await reload();
    onChanged();
  };

  const convert = async () => {
    const r = await api.post(`/deals/${deal.id}/convert-to-job`);
    if (r.job_id) {
      toast.success(`Job ${r.job_id.slice(0, 8)}… created`);
    } else {
      toast.info(r.reason || "Deal marked won (no customer to attach)");
    }
    await reload();
    onChanged();
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent
        className="max-w-4xl max-h-[90vh] overflow-y-auto"
        data-testid="deal-detail-drawer"
      >
        <DialogHeader>
          <DialogTitle>{current.title}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="md:col-span-2 space-y-3">
            <div>
              <Label>Title</Label>
              <Input
                value={current.title || ""}
                onChange={(e) => setCurrent({ ...current, title: e.target.value })}
                data-testid="deal-detail-title"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Contact name</Label>
                <Input
                  value={current.contact_name || ""}
                  onChange={(e) =>
                    setCurrent({ ...current, contact_name: e.target.value })
                  }
                />
              </div>
              <div>
                <Label>Value ($ in cents)</Label>
                <Input
                  type="number"
                  value={current.value_cents || 0}
                  onChange={(e) =>
                    setCurrent({ ...current, value_cents: e.target.value })
                  }
                  data-testid="deal-detail-value"
                />
              </div>
              <div>
                <Label>Email</Label>
                <Input
                  value={current.contact_email || ""}
                  onChange={(e) =>
                    setCurrent({ ...current, contact_email: e.target.value })
                  }
                />
              </div>
              <div>
                <Label>Phone</Label>
                <Input
                  value={current.contact_phone || ""}
                  onChange={(e) =>
                    setCurrent({ ...current, contact_phone: e.target.value })
                  }
                />
              </div>
              <div>
                <Label>Expected close</Label>
                <Input
                  type="date"
                  value={(current.expected_close_date || "").slice(0, 10)}
                  onChange={(e) =>
                    setCurrent({
                      ...current,
                      expected_close_date: e.target.value,
                    })
                  }
                />
              </div>
              <div>
                <Label>Probability</Label>
                <Input
                  value={`${current.probability_pct}%`}
                  disabled
                />
              </div>
            </div>
            <div>
              <Label>Notes</Label>
              <Textarea
                rows={4}
                value={current.notes || ""}
                onChange={(e) =>
                  setCurrent({ ...current, notes: e.target.value })
                }
              />
            </div>
            <div className="flex gap-2 flex-wrap">
              <Button onClick={save} disabled={busy} data-testid="deal-detail-save">
                Save
              </Button>
              {current.status === "open" && (
                <>
                  <Button
                    variant="outline"
                    className="text-emerald-700"
                    onClick={markWon}
                    data-testid="deal-detail-won"
                  >
                    <Trophy className="w-4 h-4 mr-1" />
                    Mark won
                  </Button>
                  <Button
                    variant="outline"
                    className="text-red-700"
                    onClick={markLost}
                    data-testid="deal-detail-lost"
                  >
                    <XCircle className="w-4 h-4 mr-1" />
                    Mark lost
                  </Button>
                  <Button
                    variant="outline"
                    onClick={convert}
                    data-testid="deal-detail-convert"
                  >
                    Convert to job
                  </Button>
                </>
              )}
              {current.status === "won" && (
                <Badge className="bg-emerald-500">Won</Badge>
              )}
              {current.status === "lost" && (
                <Badge className="bg-red-500">Lost</Badge>
              )}
            </div>
          </div>
          <div>
            <Label className="mb-2 block">Timeline</Label>
            <div className="space-y-2 max-h-96 overflow-y-auto pr-2">
              {events.length === 0 && (
                <div className="text-xs text-muted-foreground">
                  No events yet.
                </div>
              )}
              {events.map((e) => (
                <div key={e.id} className="text-xs border rounded p-2 bg-gray-50">
                  <div className="font-medium capitalize">
                    {e.type.replace(/_/g, " ")}
                  </div>
                  <div className="text-muted-foreground text-[10px]">
                    {new Date(e.created_at).toLocaleString()}
                  </div>
                  {e.to_value && (
                    <div className="mt-1 text-muted-foreground">
                      → {JSON.stringify(e.to_value)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function NewDealDialog({ pipeline, onClose, onCreated }) {
  const [form, setForm] = useState({
    title: "",
    value_cents: 0,
    contact_name: "",
    contact_email: "",
    contact_phone: "",
    notes: "",
    stage_id: (pipeline?.stages || [])[0]?.id || "",
  });

  const submit = async () => {
    if (!form.title.trim()) {
      toast.error("Title is required");
      return;
    }
    try {
      await api.post("/deals", {
        title: form.title,
        value_cents: parseInt(form.value_cents, 10) || 0,
        contact_name: form.contact_name,
        contact_email: form.contact_email,
        contact_phone: form.contact_phone,
        notes: form.notes,
        stage_id: form.stage_id,
        pipeline_id: pipeline?.id,
      });
      toast.success("Deal created");
      onCreated();
    } catch (e) {
      toast.error(e?.message || "Create failed");
    }
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent data-testid="deal-new-dialog">
        <DialogHeader>
          <DialogTitle>New deal</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>Title *</Label>
            <Input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              data-testid="deal-new-title"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Contact name</Label>
              <Input
                value={form.contact_name}
                onChange={(e) =>
                  setForm({ ...form, contact_name: e.target.value })
                }
              />
            </div>
            <div>
              <Label>Value (cents)</Label>
              <Input
                type="number"
                value={form.value_cents}
                onChange={(e) =>
                  setForm({ ...form, value_cents: e.target.value })
                }
                data-testid="deal-new-value"
              />
            </div>
            <div>
              <Label>Email</Label>
              <Input
                value={form.contact_email}
                onChange={(e) =>
                  setForm({ ...form, contact_email: e.target.value })
                }
              />
            </div>
            <div>
              <Label>Phone</Label>
              <Input
                value={form.contact_phone}
                onChange={(e) =>
                  setForm({ ...form, contact_phone: e.target.value })
                }
              />
            </div>
          </div>
          <div>
            <Label>Starting stage</Label>
            <Select
              value={form.stage_id}
              onValueChange={(v) => setForm({ ...form, stage_id: v })}
            >
              <SelectTrigger data-testid="deal-new-stage">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(pipeline?.stages || []).map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name} — {s.probability_pct}%
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Notes</Label>
            <Textarea
              rows={3}
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} data-testid="deal-new-submit">
            Create deal
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PipelineEditorDialog({ pipeline, onClose, onSaved }) {
  const [name, setName] = useState(pipeline?.name || "");
  const [stages, setStages] = useState(pipeline?.stages || []);

  const setStage = (i, field, val) => {
    const next = [...stages];
    next[i] = { ...next[i], [field]: val };
    setStages(next);
  };

  const save = async () => {
    if (!pipeline?.id) return;
    try {
      await api.patch(`/deal-pipelines/${pipeline.id}`, {
        name,
        stages: stages.map((s, i) => ({
          id: s.id,
          name: s.name,
          order: i,
          color: s.color,
          probability_pct: parseInt(s.probability_pct, 10) || 0,
        })),
      });
      toast.success("Pipeline updated");
      onSaved();
    } catch (e) {
      toast.error(e?.message || "Save failed");
    }
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-3xl" data-testid="pipeline-editor">
        <DialogHeader>
          <DialogTitle>Edit pipeline</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            {stages.map((s, i) => (
              <div key={s.id} className="grid grid-cols-6 gap-2 items-center">
                <div className="col-span-3">
                  <Input
                    value={s.name}
                    onChange={(e) => setStage(i, "name", e.target.value)}
                  />
                </div>
                <div>
                  <Input
                    type="color"
                    value={s.color || "#94A3B8"}
                    onChange={(e) => setStage(i, "color", e.target.value)}
                  />
                </div>
                <div className="col-span-2">
                  <Input
                    type="number"
                    min="0"
                    max="100"
                    value={s.probability_pct}
                    onChange={(e) =>
                      setStage(i, "probability_pct", e.target.value)
                    }
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} data-testid="pipeline-editor-save">
            Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
