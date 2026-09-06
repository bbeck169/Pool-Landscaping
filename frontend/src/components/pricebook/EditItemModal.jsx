/**
 * Backlog #iii · Feb-2026 — Edit Item modal for the Pricebook.
 *
 * Four tabs: General / Pricing / Suppliers / Categories.
 *
 * Contract (locked with user):
 *   • Server is authoritative for the ``suppliers[]`` shape. Client
 *     posts the full array; server validates + regenerates the two
 *     compat mirrors (``wholesale_price`` scalar + ``supplier_prices[]``
 *     compact).
 *   • Categories tab uses free-text with autocomplete against the
 *     existing ``/income-categories`` + ``/service-categories`` lists.
 *     A new name that doesn't match anything triggers
 *     ``POST /*-categories/resolve-or-create`` on save (case-
 *     insensitive get-then-create — never 409).
 *   • Empty-suppliers guardrail (R4): chemical items with 0
 *     supplier rows show a soft yellow warning banner. Save is
 *     never blocked.
 *   • Suppliers tab supplier_name autocomplete (R3) queries
 *     ``/pricebook/supplier-names`` and includes free-text create.
 *
 * Opened from either:
 *   a) The pricebook list row's "Edit…" button (defaults to the
 *      "General" tab).
 *   b) The read-only column-3 pencil (defaults to the "Suppliers"
 *      tab) — see prop ``initialTab``.
 */
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, AlertTriangle, Check } from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Command, CommandList, CommandItem, CommandEmpty,
} from "@/components/ui/command";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { colors, money } from "@/theme";
import { api } from "@/api";


// ─── Empty defaults ────────────────────────────────────────────────
const _newSupplierRow = () => ({
  id: "",  // server auto-stamps when omitted
  supplier_name: "",
  supplier_sku: "",
  unit_cost: "",
  unit_size: "",
  notes: "",
});


// ─── Category autocomplete input ───────────────────────────────────
// Free-text with combobox dropdown. Emits { id, name } on select.
// A NEW name (no case-insensitive match in the source list) shows a
// "+ Create '{query}'" affordance at the bottom of the dropdown; the
// caller resolves-or-creates on save.
function CategoryAutocomplete({
  label, testidPrefix, source, value, onChange,
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState(value?.name || "");
  useEffect(() => { setQ(value?.name || ""); }, [value?.id, value?.name]);

  const filtered = useMemo(() => {
    if (!q.trim()) return source.slice(0, 8);
    const nq = q.trim().toLowerCase();
    return source
      .filter((c) => (c.name || "").toLowerCase().includes(nq))
      .slice(0, 8);
  }, [q, source]);

  const exactMatch = useMemo(() => {
    const nq = (q || "").trim().toLowerCase();
    if (!nq) return null;
    return source.find((c) => (c.name || "").toLowerCase() === nq) || null;
  }, [q, source]);

  const showCreate = q.trim().length > 0 && !exactMatch;

  return (
    <div className="space-y-1">
      <Label className="text-xs uppercase tracking-wide"
              style={{ color: colors.muted }}>{label}</Label>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Input
            data-testid={`${testidPrefix}-input`}
            value={q}
            onChange={(e) => { setQ(e.target.value); setOpen(true); }}
            onFocus={() => setOpen(true)}
            placeholder={`Type or select ${label.toLowerCase()}…`}
          />
        </PopoverTrigger>
        <PopoverContent className="w-[--radix-popover-trigger-width] p-0"
                          align="start"
                          onOpenAutoFocus={(e) => e.preventDefault()}>
          <Command shouldFilter={false}>
            <CommandList data-testid={`${testidPrefix}-list`}>
              {filtered.length === 0 && !showCreate ? (
                <CommandEmpty>No matches.</CommandEmpty>
              ) : null}
              {filtered.map((c) => (
                <CommandItem
                  key={c.id}
                  data-testid={`${testidPrefix}-option-${c.id}`}
                  value={c.name}
                  onSelect={() => {
                    onChange({ id: c.id, name: c.name });
                    setQ(c.name);
                    setOpen(false);
                  }}
                >
                  <Check className={`mr-2 h-4 w-4 ${value?.id === c.id ? "opacity-100" : "opacity-0"}`} />
                  {c.name}
                </CommandItem>
              ))}
              {showCreate ? (
                <CommandItem
                  data-testid={`${testidPrefix}-create`}
                  value={`__create__${q}`}
                  onSelect={() => {
                    onChange({ id: null, name: q.trim() });
                    setOpen(false);
                  }}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Create &ldquo;{q.trim()}&rdquo;
                </CommandItem>
              ) : null}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}


// ─── Supplier-name autocomplete (free-text with dropdown) ─────────
function SupplierNameAutocomplete({ names, value, onChange, testid }) {
  const [open, setOpen] = useState(false);
  const filtered = useMemo(() => {
    if (!value?.trim()) return names.slice(0, 8);
    const nq = value.trim().toLowerCase();
    return names.filter((n) => n.toLowerCase().includes(nq)).slice(0, 8);
  }, [value, names]);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Input
          data-testid={testid}
          value={value || ""}
          placeholder="e.g. Pool360"
          onChange={(e) => { onChange(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
        />
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0"
                        align="start"
                        onOpenAutoFocus={(e) => e.preventDefault()}>
        <Command shouldFilter={false}>
          <CommandList>
            {filtered.length === 0 ? (
              <CommandEmpty>Type to create a new supplier.</CommandEmpty>
            ) : null}
            {filtered.map((n) => (
              <CommandItem key={n} value={n}
                              data-testid={`${testid}-opt-${n.toLowerCase().replace(/\s+/g, "-")}`}
                              onSelect={() => { onChange(n); setOpen(false); }}>
                {n}
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}


// ─── The modal ────────────────────────────────────────────────────
export default function EditItemModal({
  open, onOpenChange, item, initialTab = "general",
  onSaved,
}) {
  const [tab, setTab] = useState(initialTab);
  useEffect(() => { setTab(initialTab); }, [initialTab, open]);
  const [saving, setSaving] = useState(false);

  // ─── Form state ─────────────────────────────────────────────────
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");            // Taxonomy A
  const [unit, setUnit] = useState("");
  const [description, setDescription] = useState("");
  const [itemType, setItemType] = useState("product");
  const [unitPrice, setUnitPrice] = useState("");
  const [taxRate, setTaxRate] = useState("");
  const [laborCostDefault, setLaborCostDefault] = useState("");
  const [suppliers, setSuppliers] = useState([]);
  const [incomeCat, setIncomeCat] = useState(null);       // {id, name}
  const [serviceCat, setServiceCat] = useState(null);     // {id, name}

  // Data sources for autocompletes.
  const [incomeSource, setIncomeSource] = useState([]);
  const [serviceSource, setServiceSource] = useState([]);
  const [supplierNames, setSupplierNames] = useState([]);

  // Reset on open.
  useEffect(() => {
    if (!open || !item) return;
    setName(item.name || "");
    setCategory(item.category || "");
    setUnit(item.unit || "");
    setDescription(item.description || "");
    setItemType((item.item_type || "product").toLowerCase());
    setUnitPrice(String(item.unit_price ?? ""));
    setTaxRate(String(item.tax_rate ?? ""));
    setLaborCostDefault(String(item.labor_cost_default ?? ""));
    setSuppliers(Array.isArray(item.suppliers) ? item.suppliers.map((s) => ({ ..._newSupplierRow(), ...s })) : []);
    setIncomeCat(item.income_category_id
      ? { id: item.income_category_id, name: item.income_category_name || "" }
      : null);
    setServiceCat(item.service_category_id
      ? { id: item.service_category_id, name: item.service_category_name || "" }
      : null);
  }, [open, item]);

  // Load autocomplete sources.
  useEffect(() => {
    if (!open) return;
    (async () => {
      try {
        const r = await api.get("/income-categories");
        const rows = Array.isArray(r) ? r : (r?.items || []);
        setIncomeSource(rows.filter((c) => !c.is_archived));
      } catch { setIncomeSource([]); }
    })();
    (async () => {
      try {
        const r = await api.get("/service-categories");
        const rows = Array.isArray(r) ? r : (r?.items || []);
        setServiceSource(rows.filter((c) => !c.is_archived));
      } catch { setServiceSource([]); }
    })();
    (async () => {
      try {
        const r = await api.get("/pricebook/supplier-names");
        setSupplierNames(Array.isArray(r?.names) ? r.names : []);
      } catch { setSupplierNames([]); }
    })();
  }, [open]);

  // ─── Derived ────────────────────────────────────────────────────
  const effectiveCost = useMemo(() => {
    const costs = suppliers
      .map((s) => Number(s.unit_cost))
      .filter((n) => Number.isFinite(n) && n >= 0);
    if (!costs.length) return null;
    return Math.min(...costs);
  }, [suppliers]);

  const isChemical = /^chemical/i.test(String(category || "").trim());
  const emptySuppliersWarn = isChemical && suppliers.length === 0;

  // ─── Suppliers-tab operations ───────────────────────────────────
  const addRow = () => setSuppliers([...suppliers, _newSupplierRow()]);
  const updateRow = (idx, patch) =>
    setSuppliers(suppliers.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  const removeRow = (idx) => setSuppliers(suppliers.filter((_, i) => i !== idx));

  // ─── Save ───────────────────────────────────────────────────────
  async function save() {
    if (!item?.id) return;
    setSaving(true);
    try {
      // 1. Resolve categories — create-on-save when the picker
      //    returned a name with no id.
      let incomeId = incomeCat?.id ?? null;
      if (incomeCat && !incomeCat.id && incomeCat.name?.trim()) {
        const r = await api.post("/income-categories/resolve-or-create",
          { name: incomeCat.name.trim() });
        incomeId = r?.category?.id || null;
      }
      let serviceId = serviceCat?.id ?? null;
      if (serviceCat && !serviceCat.id && serviceCat.name?.trim()) {
        const r = await api.post("/service-categories/resolve-or-create",
          { name: serviceCat.name.trim() });
        serviceId = r?.category?.id || null;
      }

      // 2. Normalise supplier rows — coerce numeric fields, strip
      //    blank strings so the server sees "None" instead of "".
      const cleanSuppliers = suppliers
        .filter((s) => (s.supplier_name || "").trim() !== "")
        .map((s) => ({
          id: s.id || undefined,
          supplier_name: s.supplier_name.trim(),
          supplier_sku: (s.supplier_sku || "").trim(),
          unit_cost: (s.unit_cost === "" || s.unit_cost === null || s.unit_cost === undefined)
            ? null
            : Number(s.unit_cost),
          unit_size: (s.unit_size || "").trim(),
          notes: (s.notes || "").trim(),
        }));

      const payload = {
        name: (name || "").trim(),
        category: (category || "").trim(),
        unit: (unit || "").trim(),
        description: (description || "").trim(),
        item_type: itemType,
        unit_price: unitPrice === "" ? 0 : Number(unitPrice),
        tax_rate: taxRate === "" ? 0 : Number(taxRate),
        labor_cost_default: laborCostDefault === "" ? 0 : Number(laborCostDefault),
        suppliers: cleanSuppliers,
      };
      if (incomeId) payload.income_category_id = incomeId;
      if (serviceId) payload.service_category_id = serviceId;

      const updated = await api.patch(`/items/${item.id}`, payload);
      toast.success("Item saved");
      onOpenChange?.(false);
      onSaved?.(updated);
    } catch (e) {
      const msg = e?.data?.detail?.message
        || e?.data?.detail?.error
        || e?.message
        || "Save failed";
      toast.error(String(msg));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-3xl p-0 gap-0"
        data-testid="edit-item-modal"
      >
        <DialogHeader className="px-6 pt-5 pb-3 border-b"
                        style={{ borderColor: colors.border }}>
          <DialogTitle className="text-lg font-semibold flex items-center gap-2">
            <Pencil className="h-4 w-4" style={{ color: colors.muted }} />
            Edit item — <span style={{ color: colors.muted }}>{item?.name}</span>
          </DialogTitle>
        </DialogHeader>

        <Tabs value={tab} onValueChange={setTab} className="w-full">
          <TabsList className="mx-6 mt-3 grid grid-cols-4 w-auto"
                       data-testid="edit-item-tabs">
            <TabsTrigger value="general" data-testid="tab-general">General</TabsTrigger>
            <TabsTrigger value="pricing" data-testid="tab-pricing">Pricing</TabsTrigger>
            <TabsTrigger value="suppliers" data-testid="tab-suppliers">
              Suppliers
              {suppliers.length > 0 ? (
                <Badge variant="secondary" className="ml-2 h-4 min-w-[1.25rem] px-1.5 text-[10px]">
                  {suppliers.length}
                </Badge>
              ) : null}
            </TabsTrigger>
            <TabsTrigger value="categories" data-testid="tab-categories">Categories</TabsTrigger>
          </TabsList>

          {/* GENERAL */}
          <TabsContent value="general" className="px-6 py-5 space-y-4"
                          data-testid="tab-general-panel">
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <Label className="text-xs uppercase" style={{ color: colors.muted }}>Name</Label>
                <Input data-testid="ei-name" value={name}
                        onChange={(e) => setName(e.target.value)} />
              </div>
              <div>
                <Label className="text-xs uppercase" style={{ color: colors.muted }}>Type (Taxonomy A)</Label>
                <Input data-testid="ei-category" value={category}
                        onChange={(e) => setCategory(e.target.value)}
                        placeholder="e.g. Chemical, Service, Part" />
              </div>
              <div>
                <Label className="text-xs uppercase" style={{ color: colors.muted }}>Unit</Label>
                <Input data-testid="ei-unit" value={unit}
                        onChange={(e) => setUnit(e.target.value)}
                        placeholder="e.g. each, 25 lb" />
              </div>
              <div className="col-span-2">
                <Label className="text-xs uppercase" style={{ color: colors.muted }}>Description</Label>
                <Input data-testid="ei-description" value={description}
                        onChange={(e) => setDescription(e.target.value)} />
              </div>
              <div>
                <Label className="text-xs uppercase" style={{ color: colors.muted }}>Item kind</Label>
                <select data-testid="ei-item-type"
                          value={itemType}
                          onChange={(e) => setItemType(e.target.value)}
                          className="w-full h-9 rounded-md border px-3 text-sm"
                          style={{ borderColor: colors.border }}>
                  <option value="product">Product</option>
                  <option value="service">Service</option>
                </select>
              </div>
            </div>
          </TabsContent>

          {/* PRICING */}
          <TabsContent value="pricing" className="px-6 py-5 space-y-4"
                          data-testid="tab-pricing-panel">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs uppercase" style={{ color: colors.muted }}>Retail price ($)</Label>
                <Input data-testid="ei-unit-price" type="number" step="0.01" min="0"
                        value={unitPrice} onChange={(e) => setUnitPrice(e.target.value)} />
              </div>
              <div>
                <Label className="text-xs uppercase" style={{ color: colors.muted }}>Tax rate (%)</Label>
                <Input data-testid="ei-tax-rate" type="number" step="0.01" min="0" max="100"
                        value={taxRate} onChange={(e) => setTaxRate(e.target.value)} />
              </div>
              <div>
                <Label className="text-xs uppercase" style={{ color: colors.muted }}>Effective cost</Label>
                <div data-testid="ei-effective-cost"
                        className="h-9 rounded-md border px-3 text-sm flex items-center font-mono"
                        style={{ borderColor: colors.border, background: colors.surfaceSecondary,
                                    color: colors.onSurface }}
                        title={effectiveCost != null
                          ? `Cheapest of ${suppliers.filter((s) => Number.isFinite(Number(s.unit_cost))).length} suppliers`
                          : "No supplier prices — add suppliers on the Suppliers tab"}>
                  {effectiveCost != null ? money(effectiveCost) : "—"}
                  {effectiveCost != null ? (
                    <span className="ml-2 text-xs" style={{ color: colors.muted }}>
                      (min of {suppliers.filter((s) => Number.isFinite(Number(s.unit_cost))).length} suppliers)
                    </span>
                  ) : null}
                </div>
              </div>
              <div>
                <Label className="text-xs uppercase" style={{ color: colors.muted }}>Labor cost ($, internal)</Label>
                <Input data-testid="ei-labor-cost" type="number" step="0.01" min="0"
                        value={laborCostDefault} onChange={(e) => setLaborCostDefault(e.target.value)} />
              </div>
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              Effective cost is derived from the <button
                type="button"
                className="underline"
                onClick={() => setTab("suppliers")}
                data-testid="ei-goto-suppliers">Suppliers tab</button> — cheapest per-unit price wins.
            </div>
          </TabsContent>

          {/* SUPPLIERS */}
          <TabsContent value="suppliers" className="px-6 py-5 space-y-3"
                          data-testid="tab-suppliers-panel">
            {emptySuppliersWarn ? (
              <div className="flex items-start gap-2 rounded-md p-3 text-sm"
                      style={{ background: "#FEF3C7", color: "#78350F",
                                border: "1px solid #FCD34D" }}
                      data-testid="ei-suppliers-empty-warning">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <div className="font-semibold">This chemical has no suppliers.</div>
                  Chemical cost report will show $0 for it. Add at least one supplier to enable accurate cost reporting.
                </div>
              </div>
            ) : null}

            {suppliers.length === 0 ? (
              <div className="text-center py-6 text-sm rounded-md border-2 border-dashed"
                      style={{ color: colors.muted, borderColor: colors.border }}
                      data-testid="ei-suppliers-empty">
                No suppliers yet. Click <b>Add supplier</b> below to enter one.
              </div>
            ) : (
              <div className="space-y-2">
                {suppliers.map((s, idx) => (
                  <div key={s.id || `new-${idx}`}
                          className="rounded-md p-3 border"
                          style={{ borderColor: colors.border }}
                          data-testid={`ei-supplier-row-${idx}`}>
                    <div className="grid grid-cols-6 gap-2">
                      <div className="col-span-2">
                        <Label className="text-[10px] uppercase" style={{ color: colors.muted }}>Supplier name</Label>
                        <SupplierNameAutocomplete
                          names={supplierNames}
                          value={s.supplier_name}
                          onChange={(v) => updateRow(idx, { supplier_name: v })}
                          testid={`ei-supplier-name-${idx}`}
                        />
                      </div>
                      <div>
                        <Label className="text-[10px] uppercase" style={{ color: colors.muted }}>SKU</Label>
                        <Input data-testid={`ei-supplier-sku-${idx}`}
                                 value={s.supplier_sku || ""}
                                 onChange={(e) => updateRow(idx, { supplier_sku: e.target.value })} />
                      </div>
                      <div>
                        <Label className="text-[10px] uppercase" style={{ color: colors.muted }}>Unit cost</Label>
                        <Input data-testid={`ei-supplier-cost-${idx}`}
                                 type="number" step="0.01" min="0"
                                 value={s.unit_cost ?? ""}
                                 onChange={(e) => updateRow(idx, { unit_cost: e.target.value })} />
                      </div>
                      <div>
                        <Label className="text-[10px] uppercase" style={{ color: colors.muted }}>Unit size</Label>
                        <Input data-testid={`ei-supplier-size-${idx}`}
                                 value={s.unit_size || ""}
                                 onChange={(e) => updateRow(idx, { unit_size: e.target.value })} />
                      </div>
                      <div className="flex items-end justify-end">
                        <Button variant="ghost" size="sm"
                                  onClick={() => removeRow(idx)}
                                  data-testid={`ei-supplier-remove-${idx}`}>
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                      <div className="col-span-6">
                        <Label className="text-[10px] uppercase" style={{ color: colors.muted }}>Notes</Label>
                        <Input data-testid={`ei-supplier-notes-${idx}`}
                                 value={s.notes || ""}
                                 onChange={(e) => updateRow(idx, { notes: e.target.value })} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <Button onClick={addRow} variant="outline" size="sm"
                       data-testid="ei-supplier-add">
              <Plus className="h-4 w-4 mr-1" /> Add supplier
            </Button>

            {suppliers.length > 0 ? (
              <div className="text-xs pt-1" style={{ color: colors.muted }}
                      data-testid="ei-effective-cost-footer">
                Effective cost = {effectiveCost != null ? money(effectiveCost) : "—"} (min of {suppliers.filter((s) => Number.isFinite(Number(s.unit_cost))).length} suppliers with a set cost)
              </div>
            ) : null}
          </TabsContent>

          {/* CATEGORIES */}
          <TabsContent value="categories" className="px-6 py-5 space-y-4"
                          data-testid="tab-categories-panel">
            <CategoryAutocomplete
              label="Income category"
              testidPrefix="ei-income-cat"
              source={incomeSource}
              value={incomeCat}
              onChange={setIncomeCat}
            />
            <CategoryAutocomplete
              label="Service category"
              testidPrefix="ei-service-cat"
              source={serviceSource}
              value={serviceCat}
              onChange={setServiceCat}
            />
            <div className="text-xs" style={{ color: colors.muted }}>
              Typing a new name shows a <b>Create &ldquo;{"{name}"}&rdquo;</b> option
              at the bottom of the dropdown — new categories are created on save.
            </div>
          </TabsContent>
        </Tabs>

        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t"
                style={{ borderColor: colors.border, background: colors.surfaceSecondary }}>
          <Button variant="ghost" onClick={() => onOpenChange?.(false)}
                     data-testid="ei-cancel">Cancel</Button>
          <Button onClick={save} disabled={saving}
                     data-testid="ei-save"
                     style={{ background: colors.brandPrimary, color: colors.onBrandPrimary }}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
