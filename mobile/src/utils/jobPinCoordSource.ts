/**
 * Phase 4 multi-property map pins — mobile parity for web 723e28204.
 *
 * The /api/jobs coord resolver (backend jobs.py, K58 ladder) stamps
 * `coord_source` ("job" | "property" | "customer" | null) plus
 * `property_id` / `property_label`, and already puts the resolved coords
 * in `location_lat/lng` — so a "property" rung job pins at the property.
 *
 *   coord_source "customer" + property_id → APPROXIMATE (property attached
 *     but had no usable coords; fell back to customer service address).
 *   coord_source "property"               → normal pin + property chip.
 *   everything else ("customer" alone, "job", null) → normal pin.
 */
import type { ViewStyle } from "react-native";
import { deriveDarker } from "@/src/components/maps/TeardropPin";

export interface JobCoordSourceFields {
  coord_source?: "job" | "property" | "customer" | string | null;
  property_id?: string | null;
  property_label?: string | null;
}

export type JobPinVariant = "approximate" | "property" | "normal";

export function jobPinVariant(job: JobCoordSourceFields | null | undefined): JobPinVariant {
  if (job?.coord_source === "customer" && job?.property_id) return "approximate";
  if (job?.coord_source === "property") return "property";
  return "normal";
}

export function isApproximatePin(job: JobCoordSourceFields | null | undefined): boolean {
  return jobPinVariant(job) === "approximate";
}

/** Property label for the callout — only on the property rung (web parity). */
export function propertyChipLabel(job: JobCoordSourceFields | null | undefined): string | null {
  return job?.coord_source === "property" && job?.property_label ? job.property_label : null;
}

/**
 * Wrapper style around the TeardropPin. Approximate → dashed darker ring
 * + 70% opacity. Others get a 2px transparent solid ring so the box size
 * is identical in both states (no anchor jump when a pin flips).
 */
export function jobPinWrapStyle(job: JobCoordSourceFields | null | undefined, fillHex: string): ViewStyle {
  const approx = isApproximatePin(job);
  return {
    borderWidth: 2,
    borderStyle: approx ? "dashed" : "solid",
    borderColor: approx ? deriveDarker(fillHex) : "transparent",
    borderRadius: 999,
    padding: 1,
    opacity: approx ? 0.7 : 1,
  };
}
