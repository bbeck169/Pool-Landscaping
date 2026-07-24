/**
 * BreadcrumbBar — self-contained breadcrumb strip for screens
 * that use a custom header instead of the shared <Header> component.
 *
 * Usage: import BreadcrumbBar and render it below your custom header.
 * It auto-derives breadcrumbs from the current route + user role.
 */
import React from "react";
import { useBreadcrumbs } from "@/src/hooks/useBreadcrumbs";
import Breadcrumbs from "@/src/components/nav/Breadcrumbs";

export default function BreadcrumbBar({ title }: { title?: string }) {
  const crumbs = useBreadcrumbs(title);
  if (crumbs.length === 0) return null;
  return <Breadcrumbs items={crumbs} />;
}
