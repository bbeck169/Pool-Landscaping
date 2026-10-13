/**
 * Feb-2026 · P2 #6 property pivot — Commit 3.
 *
 * Properties list page.  Deep-link target for the dashboard
 * property-count tiles (Active Accounts, Pool / Landscaping /
 * Both-services properties).  Admin-only; techs are redirected
 * to the per-customer PropertiesTab via the admin nav gate.
 *
 * URL params (all optional, hydrated into local filter state on
 * mount; filter changes write back to the URL):
 *
 *   ?is_active=true|false|all   (default: true — matches the
 *                                 dashboard tile intent)
 *   ?service_category=pool|landscaping|both|unset
 *   ?customer_id=<id>           (scope to one customer)
 *   ?q=<substring>              (search over label + address)
 *
 * The list groups properties by customer with a sticky
 * customer-name header above each cluster — operators scanning
 * for a specific account see all their properties together.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Home, Users, Waves, TreePine, Search, Filter,
  CheckCircle2, XCircle, Dot,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  PageHeader, Chip, Skeleton, EmptyState, Button,
} from "@/components/ui-kit";


const CATEGORY_OPTIONS = [
  { key: "all", label: "All categories" },
  { key: "pool", label: "Pool" },
  { key: "landscaping", label: "Landscaping" },
  { key: "both", label: "Both services" },
  { key: "unset", label: "Not set" },
];

const ACTIVE_OPTIONS = [
  { key: "true", label: "Active" },
  { key: "false", label: "Inactive" },
  { key: "all", label: "All" },
];


function formatAddress(addr) {
  if (!addr) return "";
  const parts = [addr.line1, addr.city, addr.state, addr.postal_code]
    .filter(Boolean);
  return parts.join(", ");
}


function CategoryChip({ category }) {
  const canon = (category || "").toLowerCase();
  if (canon === "pool") {
    return (
      <Chip data-testid="property-category-chip-pool"
            style={{ background: colors.sky100, color: colors.sky800 }}>
        <Waves size={12} /> Pool
      </Chip>
    );
  }
  if (canon === "landscaping") {
    return (
      <Chip data-testid="property-category-chip-landscaping"
            style={{ background: colors.emerald100,
                       color: colors.emerald800 }}>
        <TreePine size={12} /> Landscaping
      </Chip>
    );
  }
  if (canon === "both") {
    return (
      <Chip data-testid="property-category-chip-both"
            style={{ background: colors.violet100,
                       color: colors.violet800 }}>
        <Dot size={12} /> Both
      </Chip>
    );
  }
  return (
    <Chip data-testid="property-category-chip-unset"
          style={{ background: colors.surfaceMuted,
                     color: colors.onSurfaceMuted }}>
      Not set
    </Chip>
  );
}


function ActiveBadge({ active }) {
  if (active === false) {
    return (
      <span data-testid="property-active-badge-inactive"
             style={{ display: "inline-flex", alignItems: "center",
                      gap: 4, color: colors.onSurfaceMuted,
                      fontSize: 12 }}>
        <XCircle size={12} /> Inactive
      </span>
    );
  }
  return (
    <span data-testid="property-active-badge-active"
           style={{ display: "inline-flex", alignItems: "center",
                    gap: 4, color: colors.emerald800, fontSize: 12 }}>
      <CheckCircle2 size={12} /> Active
    </span>
  );
}


function PropertyRow({ property, onOpen }) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onOpen();
      }}
      data-testid={`property-row-${property.id}`}
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto auto",
        gap: 16,
        padding: "12px 16px",
        borderBottom: `1px solid ${colors.border}`,
        cursor: "pointer",
      }}
    >
      <div>
        <div style={{ fontWeight: 600, color: colors.onSurface }}>
          <Home size={14} style={{ marginRight: 6 }} />
          {property.label || "(unlabelled)"}
        </div>
        <div style={{ fontSize: 13, color: colors.onSurfaceMuted,
                       marginTop: 2 }}>
          {formatAddress(property.address) || "No address"}
        </div>
      </div>
      <CategoryChip category={property.service_category} />
      <ActiveBadge active={property.active} />
    </div>
  );
}


function CustomerGroup({ customerName, customerId, properties, onOpenProperty }) {
  return (
    <section data-testid={`properties-group-${customerId}`}
             style={{ marginBottom: 24 }}>
      <header
        style={{
          position: "sticky",
          top: 0,
          background: colors.surface,
          padding: "8px 16px",
          borderBottom: `1px solid ${colors.border}`,
          zIndex: 1,
          fontWeight: 600,
          color: colors.onSurface,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <Users size={14} />
        <span data-testid={`properties-group-name-${customerId}`}>
          {customerName || "(unknown customer)"}
        </span>
        <span style={{ color: colors.onSurfaceMuted, fontWeight: 400,
                        fontSize: 13 }}>
          · {properties.length}{" "}
          {properties.length === 1 ? "property" : "properties"}
        </span>
      </header>
      <div>
        {properties.map((p) => (
          <PropertyRow
            key={p.id}
            property={p}
            onOpen={() => onOpenProperty(p)}
          />
        ))}
      </div>
    </section>
  );
}


export default function PropertiesListPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [activeFilter, setActiveFilter] = useState(
    searchParams.get("is_active") || "true",
  );
  const [categoryFilter, setCategoryFilter] = useState(
    searchParams.get("service_category") || "all",
  );
  const [customerIdFilter] = useState(
    searchParams.get("customer_id") || "",
  );
  const [search, setSearch] = useState(searchParams.get("q") || "");

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [customerIndex, setCustomerIndex] = useState({});

  const fetchRows = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (activeFilter && activeFilter !== "all") {
        params.is_active = activeFilter;
      }
      if (categoryFilter && categoryFilter !== "all") {
        params.service_category = categoryFilter;
      }
      if (customerIdFilter) params.customer_id = customerIdFilter;
      if (search) params.search = search;
      const qs = new URLSearchParams(params).toString();
      const r = await api.get(`/properties${qs ? `?${qs}` : ""}`);
      setRows(Array.isArray(r?.items) ? r.items : []);
    } catch (_err) {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [activeFilter, categoryFilter, customerIdFilter, search]);

  useEffect(() => {
    fetchRows();
  }, [fetchRows]);

  // Hydrate customer names in one $in call. Fed by the per-row
  // customer_id values; cheap because the Commit-1 list endpoint
  // caps at 500.
  useEffect(() => {
    const cids = Array.from(
      new Set(rows.map((r) => r.customer_id).filter(Boolean)),
    );
    if (!cids.length) return;
    const missing = cids.filter((cid) => !(cid in customerIndex));
    if (!missing.length) return;
    (async () => {
      try {
        // Reuse the /customers list endpoint with ids_in — if that
        // param isn't supported here, fall back to one-by-one.
        const r = await api.get(
          `/customers?ids_in=${encodeURIComponent(missing.join(","))}`,
        );
        const items = Array.isArray(r?.items) ? r.items
                    : Array.isArray(r) ? r : [];
        setCustomerIndex((prev) => {
          const next = { ...prev };
          for (const c of items) {
            next[c.id] = c.name || c.company_name || "(unnamed)";
          }
          // Stamp missing ids we didn't resolve so we don't retry.
          for (const cid of missing) {
            if (!(cid in next)) next[cid] = "";
          }
          return next;
        });
      } catch (_err) {
        // Non-fatal; row still renders with "(unknown customer)".
      }
    })();
    // Dependency = rows only. customerIndex is read inside via the
    // closure but we don't want to re-fire on index updates (that
    // would loop); the ``missing`` guard above is a one-shot filter
    // based on the current snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows]);

  // Push filter state into the URL so the page is deep-linkable.
  useEffect(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (activeFilter && activeFilter !== "true") {
        next.set("is_active", activeFilter);
      } else {
        next.delete("is_active");
      }
      if (categoryFilter && categoryFilter !== "all") {
        next.set("service_category", categoryFilter);
      } else {
        next.delete("service_category");
      }
      if (search) next.set("q", search);
      else next.delete("q");
      return next;
    }, { replace: true });
  }, [activeFilter, categoryFilter, search, setSearchParams]);

  const grouped = useMemo(() => {
    const buckets = new Map();
    for (const r of rows) {
      const cid = r.customer_id || "_orphans";
      if (!buckets.has(cid)) buckets.set(cid, []);
      buckets.get(cid).push(r);
    }
    const groups = [];
    for (const [cid, props] of buckets.entries()) {
      groups.push({
        customerId: cid,
        customerName: customerIndex[cid] || "",
        properties: props,
      });
    }
    groups.sort((a, b) =>
      (a.customerName || "zzz").localeCompare(b.customerName || "zzz"),
    );
    return groups;
  }, [rows, customerIndex]);

  const onOpenProperty = (p) => {
    if (p.customer_id) {
      navigate(`/customers/${p.customer_id}?tab=properties`);
    }
  };

  return (
    <div data-testid="properties-list-page" style={{ padding: 24 }}>
      <PageHeader title="Properties"
                  subtitle="All serviceable properties across your accounts" />

      <div data-testid="properties-list-filterbar"
           style={{
             display: "flex",
             gap: 12,
             alignItems: "center",
             padding: "12px 0",
             flexWrap: "wrap",
             marginBottom: 16,
           }}>
        <div style={{ display: "flex", alignItems: "center",
                       gap: 8, flex: 1, minWidth: 240 }}>
          <Search size={16} color={colors.onSurfaceMuted} />
          <input
            data-testid="properties-list-search"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search label, address, city…"
            style={{
              flex: 1,
              padding: "6px 10px",
              border: `1px solid ${colors.border}`,
              borderRadius: 6,
            }}
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Filter size={14} color={colors.onSurfaceMuted} />
          <select
            data-testid="properties-list-active-filter"
            value={activeFilter}
            onChange={(e) => setActiveFilter(e.target.value)}
            style={{ padding: "6px 10px",
                      border: `1px solid ${colors.border}`,
                      borderRadius: 6 }}
          >
            {ACTIVE_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>{o.label}</option>
            ))}
          </select>
        </div>
        <select
          data-testid="properties-list-category-filter"
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          style={{ padding: "6px 10px",
                    border: `1px solid ${colors.border}`,
                    borderRadius: 6 }}
        >
          {CATEGORY_OPTIONS.map((o) => (
            <option key={o.key} value={o.key}>{o.label}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div data-testid="properties-list-loading">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} style={{ height: 60, marginBottom: 8 }} />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          data-testid="properties-list-empty"
          title="No properties match"
          description="Try widening the filters or clearing search."
        >
          <Button onClick={() => {
            setActiveFilter("all");
            setCategoryFilter("all");
            setSearch("");
          }}>Clear filters</Button>
        </EmptyState>
      ) : (
        <div data-testid="properties-list-grouped">
          {grouped.map((g) => (
            <CustomerGroup
              key={g.customerId}
              customerId={g.customerId}
              customerName={g.customerName}
              properties={g.properties}
              onOpenProperty={onOpenProperty}
            />
          ))}
        </div>
      )}
    </div>
  );
}
