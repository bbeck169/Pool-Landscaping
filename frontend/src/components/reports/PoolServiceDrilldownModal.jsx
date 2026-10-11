/**
 * Feb-2026 · Pool Service Report — shared drill-down modal.
 *
 * Backs TC-A (bucket chip click), TC-B (per-tech row click) and
 * TC-C (Auto-Friday email delivery row click) from the Pool
 * Service Report. Fetches jobs/customers on open — never pre-
 * fetched with the summary — so the summary page stays light.
 *
 * Keyboard / click affordances come from the shared Shadcn
 * Dialog primitive (`@/components/ui/dialog`): ESC + backdrop
 * click + an explicit "Close" button all dismiss the modal.
 *
 * The modal is intentionally variant-driven (``variant="bucket"``
 * / ``"tech"`` / ``"delivery"``) so one component owns the three
 * shapes and the column schema switches internally. This keeps
 * the three parent click surfaces in ``PoolServiceReport.jsx``
 * minimal (parent passes variant + filter inputs, modal does
 * the rest).
 */
import React from "react";
import { ExternalLink } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogDescription, DialogFooter, DialogClose,
} from "@/components/ui/dialog";


function _fmtDate(iso) {
  if (!iso) return "—";
  // Accept either ``YYYY-MM-DD`` (scheduled_date) or a full ISO
  // timestamp (completed_at) — strip to the yyyy-mm-dd portion
  // for the drill-down table so the column stays narrow.
  return String(iso).slice(0, 10);
}


function _jobTypeLabel(row) {
  // Prefer ``work_class`` (``service`` / ``repair``) → human-
  // readable "Maintenance" / "Repair". Fall through to
  // ``service_type`` / ``job_type`` for the "Other" bucket where
  // ``work_class`` is null by definition.
  const wc = (row?.work_class || "").toLowerCase();
  if (wc === "service") return "Maintenance";
  if (wc === "repair")  return "Repair";
  return row?.service_type || row?.job_type || "Other";
}


const _BUCKET_TITLES = {
  maintenance: "Maintenance visits",
  repairs:     "Repairs completed",
  other:       "Other job types",
  unassigned:  "Unassigned pool jobs",
};


/**
 * Fetch + render the per-bucket OR per-tech drill-down table.
 * The ``variant`` controls both the fetch URL + the column
 * schema that renders.
 *
 * Props (unioned per variant):
 *   • variant   — "bucket" | "tech" | "delivery"
 *   • open      — controlled open-state
 *   • onClose   — Dialog onOpenChange(false) handler
 *   • dateFrom  — ISO date (bucket + tech variants)
 *   • dateTo    — ISO date (bucket + tech variants)
 *   • bucket    — "maintenance" | "repairs" | "other" | "unassigned"
 *   • techId    — tech id or "unassigned" sentinel
 *   • techName  — pre-resolved label for the modal title
 *   • deliveryId — email delivery id (variant="delivery")
 */
export default function PoolServiceDrilldownModal({
  variant,
  open,
  onClose,
  dateFrom,
  dateTo,
  bucket,
  techId,
  techName,
  deliveryId,
  deliveryTitle,
}) {
  const [loading, setLoading] = React.useState(false);
  const [error, setError]     = React.useState(null);
  const [data, setData]       = React.useState(null);

  // Reset state every time the modal opens so a prior fetch
  // doesn't flash through on re-open with new props.
  React.useEffect(() => {
    if (!open) return;
    let alive = true;
    setLoading(true);
    setError(null);
    setData(null);
    (async () => {
      try {
        let res;
        if (variant === "bucket") {
          res = await api.get(
            `/reports/pool-service/jobs?date_from=${encodeURIComponent(dateFrom)}` +
            `&date_to=${encodeURIComponent(dateTo)}` +
            `&bucket=${encodeURIComponent(bucket)}`,
          );
        } else if (variant === "tech") {
          res = await api.get(
            `/reports/pool-service/jobs?date_from=${encodeURIComponent(dateFrom)}` +
            `&date_to=${encodeURIComponent(dateTo)}` +
            `&tech_id=${encodeURIComponent(techId)}`,
          );
        } else if (variant === "delivery") {
          res = await api.get(
            `/reports/pool-service/email-history/${encodeURIComponent(deliveryId)}/contents`,
          );
        }
        if (alive) setData(res);
      } catch (e) {
        if (alive) setError(e?.message || "Failed to load drill-down");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [open, variant, dateFrom, dateTo, bucket, techId, deliveryId]);

  const title = React.useMemo(() => {
    if (variant === "bucket")   return _BUCKET_TITLES[bucket] || "Pool jobs";
    if (variant === "tech") {
      return techId === "unassigned"
        ? "Unassigned pool jobs"
        : `${techName || "Technician"} — pool jobs this week`;
    }
    if (variant === "delivery") return deliveryTitle || "Email delivery contents";
    return "Pool jobs";
  }, [variant, bucket, techId, techName, deliveryTitle]);

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose && onClose(); }}>
      <DialogContent
        className="max-w-4xl max-h-[85vh] overflow-hidden flex flex-col"
        data-testid="pool-service-drilldown-modal"
      >
        <DialogHeader>
          <DialogTitle data-testid="pool-service-drilldown-title">{title}</DialogTitle>
          <DialogDescription>
            {variant === "delivery"
              ? "Customers and jobs included in this Auto-Friday email delivery."
              : `Scheduled ${dateFrom} → ${dateTo}. Click a job to open it in a new tab.`}
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-auto -mx-6 px-6"
              data-testid="pool-service-drilldown-body">
          {loading ? (
            <div className="py-10 text-center text-sm"
                  style={{ color: colors.muted }}
                  data-testid="pool-service-drilldown-loading">
              Loading jobs…
            </div>
          ) : error ? (
            <div className="py-6 px-4 rounded-md text-sm"
                  style={{ background: "#FEF2F2", color: "#B91C1C",
                             border: "1px solid #FECACA" }}
                  data-testid="pool-service-drilldown-error">
              {error}
            </div>
          ) : variant === "delivery" ? (
            <_DeliveryContentsTable data={data} />
          ) : (
            <_JobsTable items={data?.items || []} variant={variant} />
          )}
        </div>

        <DialogFooter className="mt-2">
          <DialogClose asChild>
            <button
              type="button"
              className="px-4 py-1.5 rounded-md text-sm font-semibold"
              style={{
                background: colors.brand, color: "#fff",
                border: `1px solid ${colors.brand}`,
              }}
              data-testid="pool-service-drilldown-close"
            >
              Close
            </button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


function _JobsTable({ items, variant }) {
  if (!items.length) {
    return (
      <div className="py-10 text-center text-sm"
            style={{ color: colors.muted }}
            data-testid="pool-service-drilldown-empty">
        No jobs in this segment for the selected week.
      </div>
    );
  }
  return (
    <table className="w-full text-sm"
            data-testid="pool-service-drilldown-table">
      <thead>
        <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
          <th className="text-left px-3 py-2 text-[11px] font-semibold uppercase"
               style={{ color: colors.muted }}>Customer</th>
          <th className="text-left px-3 py-2 text-[11px] font-semibold uppercase"
               style={{ color: colors.muted }}>Job</th>
          {/* The tech-variant omits the "Tech" column — it's the
              implicit filter — and renders a Job Type column instead
              so admins can see maintenance vs repair at a glance. */}
          {variant === "tech" ? (
            <th className="text-left px-3 py-2 text-[11px] font-semibold uppercase"
                 style={{ color: colors.muted }}>Job type</th>
          ) : (
            <th className="text-left px-3 py-2 text-[11px] font-semibold uppercase"
                 style={{ color: colors.muted }}>Tech</th>
          )}
          <th className="text-left px-3 py-2 text-[11px] font-semibold uppercase"
               style={{ color: colors.muted }}>Date</th>
          <th className="text-left px-3 py-2 text-[11px] font-semibold uppercase"
               style={{ color: colors.muted }}>Status</th>
          <th className="text-right px-3 py-2 text-[11px] font-semibold uppercase"
               style={{ color: colors.muted }}>Open</th>
        </tr>
      </thead>
      <tbody>
        {items.map((r) => (
          <tr key={r.job_id}
               data-testid={`pool-service-drilldown-row-${r.job_id}`}
               style={{ borderBottom: `1px solid ${colors.border}` }}>
            <td className="px-3 py-2"
                 style={{ color: colors.onSurface }}>
              {r.customer_id ? (
                <a href={`/customers/${encodeURIComponent(r.customer_id)}`}
                   target="_blank" rel="noopener noreferrer"
                   className="font-semibold underline"
                   style={{ color: colors.brand }}
                   data-testid={`pool-service-drilldown-customer-${r.job_id}`}>
                  {r.customer_name || "—"}
                </a>
              ) : (r.customer_name || "—")}
            </td>
            <td className="px-3 py-2"
                 style={{ color: colors.onSurface }}>
              {r.title || "—"}
            </td>
            {variant === "tech" ? (
              <td className="px-3 py-2 text-xs"
                   style={{ color: colors.muted }}>
                {_jobTypeLabel(r)}
              </td>
            ) : (
              <td className="px-3 py-2 text-xs"
                   style={{ color: colors.muted }}>
                {r.technician_name
                  || (r.resolved_tech_id ? r.resolved_tech_id : "Unassigned")}
              </td>
            )}
            <td className="px-3 py-2 text-xs"
                 style={{ color: colors.muted }}>
              {_fmtDate(r.scheduled_date || r.completed_at)}
            </td>
            <td className="px-3 py-2 text-xs"
                 style={{ color: colors.muted }}>
              {(r.status || "").replace(/_/g, " ")}
            </td>
            <td className="px-3 py-2 text-right">
              <a href={`/jobs/${encodeURIComponent(r.job_id)}`}
                 target="_blank" rel="noopener noreferrer"
                 className="inline-flex items-center gap-1 text-xs font-semibold"
                 style={{ color: colors.brand }}
                 data-testid={`pool-service-drilldown-open-${r.job_id}`}>
                Open <ExternalLink size={11} />
              </a>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}


function _DeliveryContentsTable({ data }) {
  if (!data) return null;
  const customers = data.customers || [];
  if (!customers.length) {
    return (
      <div className="py-10 text-center text-sm"
            style={{ color: colors.muted }}
            data-testid="pool-service-drilldown-delivery-empty">
        No customers were included in this delivery.
      </div>
    );
  }
  return (
    <table className="w-full text-sm"
            data-testid="pool-service-drilldown-delivery-table">
      <thead>
        <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
          <th className="text-left px-3 py-2 text-[11px] font-semibold uppercase"
               style={{ color: colors.muted }}>Customer</th>
          <th className="text-left px-3 py-2 text-[11px] font-semibold uppercase"
               style={{ color: colors.muted }}>Jobs included</th>
          <th className="text-right px-3 py-2 text-[11px] font-semibold uppercase"
               style={{ color: colors.muted }}>Count</th>
        </tr>
      </thead>
      <tbody>
        {customers.map((c) => (
          <tr key={c.customer_id}
               data-testid={`pool-service-drilldown-delivery-row-${c.customer_id}`}
               style={{ borderBottom: `1px solid ${colors.border}` }}>
            <td className="px-3 py-2"
                 style={{ color: colors.onSurface }}>
              <a href={`/customers/${encodeURIComponent(c.customer_id)}`}
                 target="_blank" rel="noopener noreferrer"
                 className="font-semibold underline"
                 style={{ color: colors.brand }}
                 data-testid={`pool-service-drilldown-delivery-customer-${c.customer_id}`}>
                {c.customer_name || "—"}
              </a>
            </td>
            <td className="px-3 py-2 text-xs"
                 style={{ color: colors.muted }}>
              <ul className="list-disc pl-5">
                {(c.jobs || []).map((j) => (
                  <li key={j.job_id}>
                    <a href={`/jobs/${encodeURIComponent(j.job_id)}`}
                       target="_blank" rel="noopener noreferrer"
                       className="underline"
                       style={{ color: colors.brand }}
                       data-testid={`pool-service-drilldown-delivery-job-${j.job_id}`}>
                      {j.title || j.job_id}
                    </a>
                    <span style={{ color: colors.muted }}>
                      {" "}· {_fmtDate(j.scheduled_date)}
                    </span>
                  </li>
                ))}
              </ul>
            </td>
            <td className="px-3 py-2 text-right text-xs font-bold tabular-nums"
                 style={{ color: colors.onSurface }}>
              {(c.jobs || []).length}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
