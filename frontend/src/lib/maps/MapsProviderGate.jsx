/**
 * Phase K39a · Feb-2026 — Top-level provider gate.
 *
 * Reads ``REACT_APP_MAPS_PROVIDER`` (via :func:`useMapsProvider`) and
 * wraps ``children`` in either the Google adapter's ``APIProvider``
 * (default) or the HERE adapter's no-op wrapper.  Consumers mount
 * this once at the shell (``AppLayout``) — the K37
 * ``PortalErrorBoundary`` still sits **above** this gate exactly as
 * before K39a.
 */
import React from "react";
import { useMapsProvider } from "./provider";
import { MapsProviderGate as GoogleGate } from "./googleAdapter";
import { MapsProviderGate as HereGate } from "./hereAdapter";

export default function MapsProviderGate({
  apiKey,
  libraries,
  children,
}) {
  const provider = useMapsProvider();
  if (provider === "here") return <HereGate>{children}</HereGate>;
  return (
    <GoogleGate apiKey={apiKey} libraries={libraries}>
      {children}
    </GoogleGate>
  );
}
