import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { FlaskConical, DollarSign, Package } from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
} from "recharts";

function centsToDollars(c) {
  return `$${((c || 0) / 100).toFixed(2)}`;
}

/**
 * QuoteIQ Q1-UI · Chemical Products + Profitability admin page.
 *
 * Tabs: Products (CRUD) | Profitability (filters + rollup + per-product bar).
 */
export default function ChemicalsPage() {
  const [tab, setTab] = useState("products");
  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto" data-testid="chemicals-page">
      <div className="flex items-center gap-3">
        <FlaskConical className="w-6 h-6 text-sky-600" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Chemical Products
          </h1>
          <p className="text-sm text-muted-foreground">
            Manage your chemical catalog, track cost snapshots on every visit,
            and measure per-customer margin.
          </p>
        </div>
      </div>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList data-testid="chemicals-tabs">
          <TabsTrigger value="products" data-testid="chemicals-tab-products">
            <Package className="w-4 h-4 mr-2" />
            Products
          </TabsTrigger>
          <TabsTrigger value="profitability" data-testid="chemicals-tab-profitability">
            <DollarSign className="w-4 h-4 mr-2" />
            Profitability
          </TabsTrigger>
        </TabsList>
        <TabsContent value="products">
          <ProductsTab />
        </TabsContent>
        <TabsContent value="profitability">
          <ProfitabilityTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function ProductsTab() {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState(null);
  const [formOpen, setFormOpen] = useState(false);

  const load = async () => {
    const qs = new URLSearchParams();
    if (q) qs.set("q", q);
    if (!showInactive) qs.set("active", "true");
    const d = await api.get(`/chemical-products?${qs.toString()}`);
    setRows(d.products || []);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showInactive]);

  const openNew = () => {
    setEditing({
      name: "",
      sku: "",
      unit: "lb",
      unit_cost_cents: 0,
      active: true,
    });
    setFormOpen(true);
  };

  const submit = async () => {
    if (!editing.name || !editing.unit) {
      toast.error("Name and unit are required");
      return;
    }
    const payload = {
      name: editing.name,
      sku: editing.sku,
      unit: editing.unit,
      unit_cost_cents: parseInt(editing.unit_cost_cents, 10) || 0,
      active: !!editing.active,
    };
    try {
      if (editing.slug) {
        await api.patch(`/chemical-products/${editing.slug}`, payload);
        toast.success("Product updated");
      } else {
        await api.post("/chemical-products", payload);
        toast.success("Product created");
      }
      setFormOpen(false);
      setEditing(null);
      await load();
    } catch (e) {
      toast.error(e?.message || "Save failed");
    }
  };

  const removeRow = async (slug) => {
    if (!confirm("Deactivate this product? Historical costs are preserved.")) return;
    await api.del(`/chemical-products/${slug}`);
    toast.success("Product deactivated");
    await load();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Input
          className="max-w-xs"
          placeholder="Search name / SKU / slug…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
          data-testid="chem-product-search"
        />
        <Button variant="outline" onClick={load}>
          Search
        </Button>
        <label className="flex items-center gap-2 text-sm">
          <Switch
            checked={showInactive}
            onCheckedChange={setShowInactive}
            data-testid="chem-product-show-inactive"
          />
          Show inactive
        </label>
        <Button className="ml-auto" onClick={openNew} data-testid="chem-product-new">
          New product
        </Button>
      </div>
      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground text-xs uppercase tracking-wide">
                <th className="py-2 pl-4 pr-4">Name</th>
                <th className="py-2 pr-4">SKU</th>
                <th className="py-2 pr-4">Unit</th>
                <th className="py-2 pr-4 text-right">Unit cost</th>
                <th className="py-2 pr-4">Active</th>
                <th className="py-2 pr-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} className="border-b last:border-b-0">
                  <td className="py-2 pl-4 pr-4 font-medium">{p.name}</td>
                  <td className="py-2 pr-4 text-muted-foreground">
                    {p.sku || "—"}
                  </td>
                  <td className="py-2 pr-4">{p.unit}</td>
                  <td className="py-2 pr-4 text-right">
                    {centsToDollars(p.unit_cost_cents)}
                  </td>
                  <td className="py-2 pr-4">
                    {p.active ? (
                      <Badge variant="outline" className="text-emerald-700">
                        active
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-muted-foreground">
                        inactive
                      </Badge>
                    )}
                  </td>
                  <td className="py-2 pr-4 text-right space-x-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setEditing({ ...p });
                        setFormOpen(true);
                      }}
                      data-testid={`chem-product-edit-${p.slug}`}
                    >
                      Edit
                    </Button>
                    {p.active && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => removeRow(p.slug)}
                        data-testid={`chem-product-remove-${p.slug}`}
                      >
                        Deactivate
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-6 text-center text-muted-foreground">
                    No products yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent data-testid="chem-product-modal">
          <DialogHeader>
            <DialogTitle>
              {editing?.slug ? "Edit product" : "New product"}
            </DialogTitle>
          </DialogHeader>
          {editing && (
            <div className="grid gap-3 grid-cols-2">
              <div className="col-span-2">
                <Label>Name *</Label>
                <Input
                  value={editing.name}
                  onChange={(e) =>
                    setEditing({ ...editing, name: e.target.value })
                  }
                  data-testid="chem-product-name"
                />
              </div>
              <div>
                <Label>SKU</Label>
                <Input
                  value={editing.sku || ""}
                  onChange={(e) =>
                    setEditing({ ...editing, sku: e.target.value })
                  }
                />
              </div>
              <div>
                <Label>Unit *</Label>
                <Input
                  value={editing.unit}
                  onChange={(e) =>
                    setEditing({ ...editing, unit: e.target.value })
                  }
                  placeholder="lb, gal, oz"
                  data-testid="chem-product-unit"
                />
              </div>
              <div className="col-span-2">
                <Label>Unit cost (cents)</Label>
                {/* PRICING-DECIMAL-INPUT-PARITY · Feb-2026 — pre-fix
                    this rendered as type="number" which (per HTML5
                    spec) blanks ``e.target.value`` on intermediate
                    decimal states like ``"125."``.  The adjacent
                    ``centsToDollars`` preview + the save payload both
                    read ``editing.unit_cost_cents`` LIVE (no blur
                    commit), so a shared ``<DecimalInput>`` with its
                    blur-only onChange would strand the preview on
                    the pre-keystroke value.  Inline the keystroke-
                    safe pattern (text + inputMode + regex guard) as
                    documented in ``ChemistryConfigurationSettings``
                    commit ``0f5e7886f``. */}
                <Input
                  type="text"
                  inputMode="decimal"
                  pattern="[0-9]*[.,]?[0-9]*"
                  value={editing.unit_cost_cents}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v !== "" && !/^\d*\.?\d*$/.test(v)) return;
                    setEditing({
                      ...editing,
                      unit_cost_cents: v,
                    });
                  }}
                  data-testid="chem-product-cost"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Storage in cents. {centsToDollars(editing.unit_cost_cents)}{" "}
                  per {editing.unit || "unit"}.
                </p>
              </div>
              <label className="col-span-2 flex items-center gap-2 text-sm">
                <Switch
                  checked={!!editing.active}
                  onCheckedChange={(v) =>
                    setEditing({ ...editing, active: v })
                  }
                />
                Active
              </label>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setFormOpen(false)}>
              Cancel
            </Button>
            <Button onClick={submit} data-testid="chem-product-save">
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ProfitabilityTab() {
  const [customerId, setCustomerId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [data, setData] = useState(null);

  const load = async () => {
    const qs = new URLSearchParams();
    if (customerId) qs.set("customer_id", customerId);
    if (start) qs.set("start", start);
    if (end) qs.set("end", end);
    const d = await api.get(`/chemicals/profitability?${qs.toString()}`);
    setData(d);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const chartData = useMemo(() => {
    return (data?.per_product_breakdown || []).slice(0, 12).map((r) => ({
      name: r.name || r.product_slug,
      cost: (r.total_cost_cents || 0) / 100,
      qty: r.quantity_used || 0,
    }));
  }, [data]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Filters</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 grid-cols-1 md:grid-cols-4">
          <div>
            <Label>Customer ID</Label>
            <Input
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              placeholder="optional"
              data-testid="chem-profit-customer"
            />
          </div>
          <div>
            <Label>From</Label>
            <Input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </div>
          <div>
            <Label>To</Label>
            <Input
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </div>
          <div className="flex items-end">
            <Button className="w-full" onClick={load} data-testid="chem-profit-apply">
              Apply
            </Button>
          </div>
        </CardContent>
      </Card>

      {data && (
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-xs text-muted-foreground uppercase">
                Total chemical cost
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-semibold" data-testid="chem-profit-total">
                {centsToDollars(data.total_chemical_cost_cents)}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-xs text-muted-foreground uppercase">
                Visits
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-semibold">{data.visit_count}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-xs text-muted-foreground uppercase">
                Avg per visit
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-semibold">
                {centsToDollars(data.avg_cost_per_visit_cents)}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Per-product breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          {chartData.length === 0 ? (
            <div className="text-sm text-muted-foreground py-8 text-center">
              No usage events in the selected window yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={chartData}>
                <XAxis dataKey="name" tick={{ fontSize: 12 }} interval={0} angle={-15} textAnchor="end" height={70} />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="cost" name="Cost ($)" fill="#0ea5e9" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
