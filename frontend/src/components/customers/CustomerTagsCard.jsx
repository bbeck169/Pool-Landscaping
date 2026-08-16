/**
 * Queue Item 3 · Feb-2026 — Customer detail Tags section (web only).
 *
 * A labeled Overview card that hosts the existing
 * ``CustomerTagPicker`` so tags get a dedicated, prominent home on
 * the customer detail page — in addition to the compact chip picker
 * in the header row. Empty-state copy nudges the user toward the
 * inline "Create new: <query>" affordance already baked into the
 * picker's popover.
 */
import React from "react";
import { Tag as TagIcon } from "lucide-react";
import { colors } from "@/theme";
import CustomerTagPicker from "@/components/customers/CustomerTagPicker";

export default function CustomerTagsCard({ customer, onChange }) {
  if (!customer) return null;
  const tags = Array.isArray(customer.tags) ? customer.tags : [];
  return (
    <div
      className="rounded-xl p-4 space-y-3"
      style={{
        backgroundColor: colors.surfaceSecondary,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="customer-tags-section"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TagIcon size={14} style={{ color: colors.onSurface }} />
          <div
            className="font-bold text-sm"
            style={{ color: colors.onSurface }}
            data-testid="customer-tags-section-title"
          >
            Tags
          </div>
          <span
            className="text-[11px] font-semibold px-1.5 py-0.5 rounded-full"
            style={{
              backgroundColor: colors.surfaceTertiary,
              color: colors.onSurfaceSecondary,
            }}
            data-testid="customer-tags-section-count"
          >
            {tags.length}
          </span>
        </div>
      </div>
      {tags.length === 0 ? (
        <p
          className="text-xs"
          style={{ color: colors.muted }}
          data-testid="customer-tags-section-empty"
        >
          No tags yet. Click{" "}
          <span className="font-semibold">+ Tag</span> below to attach an
          existing one or create a new one on the fly.
        </p>
      ) : null}
      <CustomerTagPicker
        customerId={customer.id}
        value={tags}
        onChange={onChange}
      />
    </div>
  );
}
