/**
 * Business Settings API helpers.
 *
 * Routes:
 *   GET    /api/tenants/me/business-settings
 *   PATCH  /api/tenants/me/business-settings
 *   POST   /api/tenants/me/logo   (multipart)
 *   DELETE /api/tenants/me/logo
 */
import { api, api_base, getAuthToken } from "@/src/api";

export type BusinessSettingsStored = {
  company_display_name?: string | null;
  mailing_address?: string | null;
  phone?: string | null;
  website?: string | null;
  email?: string | null;
  brand_primary_hex?: string | null;
  brand_secondary_hex?: string | null;
  footer_note?: string | null;
  tax_id?: string | null;
  logo_url?: string | null;
  /**
   * Feb-2026 · Routing Traffic-Aware phase — per-tenant opt-in for
   * the Google Routes API v2 ``TRAFFIC_AWARE`` routing preference.
   * Default OFF. Admin-only field; NOT exposed on the public branding
   * endpoint. No mobile edit UI exists today (mobile is technician-
   * facing); the type is mirrored so a future admin-mobile surface
   * can consume it without further backend work.
   */
  routing_traffic_aware?: boolean | null;
};

export type BusinessSettingsEffective = BusinessSettingsStored & {
  /** Resolved logo URL (stored override or tenant fallback). */
  logo_url?: string | null;
};

export type BusinessSettingsResponse = {
  stored: BusinessSettingsStored;
  effective: BusinessSettingsEffective;
};

export const getBusinessSettings = (): Promise<BusinessSettingsResponse> =>
  api.get("/tenants/me/business-settings");

export const patchBusinessSettings = (
  patch: Partial<BusinessSettingsStored>,
): Promise<BusinessSettingsResponse> =>
  api.patch("/tenants/me/business-settings", patch);

/**
 * Upload a logo image via multipart form-data.
 * Uses raw fetch because api.post() JSON-stringifies the body.
 */
export const uploadLogo = async (
  fileUri: string,
  fileName: string,
  mimeType: string,
): Promise<{ logo_url: string }> => {
  const token = await getAuthToken();
  const fd = new FormData();
  fd.append("logo", {
    uri: fileUri,
    name: fileName,
    type: mimeType,
  } as any);
  const res = await fetch(`${api_base()}/tenants/me/logo`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: fd,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Upload failed (${res.status})`);
  }
  return res.json();
};

export const deleteLogo = (): Promise<void> =>
  api.del("/tenants/me/logo");
