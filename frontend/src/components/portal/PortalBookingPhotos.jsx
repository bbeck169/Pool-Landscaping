/**
 * Phase F2c.1 · Feb 2026 — Customer portal booking-request photos.
 *
 * Renders on the confirmation panel of ``PortalBook.jsx`` AFTER the
 * appointment has been created (so we have a real
 * ``portal_appointment`` id to attach to). Pre-submit upload is
 * intentionally skipped: it would require reserving a client-side
 * temp id + a backend contract change, which is out of scope.
 *
 * Storage strategy:
 *   purpose             = "portal_booking_photo"
 *   linked_entity_type  = "portal_appointment"
 *   linked_entity_id    = <appointment_id>
 *
 * The customer can remove their own uploads via the F0 delete gate
 * (uploader-owned). Techs / admins see these on the appointment
 * record when they review the request.
 */
import React, { useCallback, useState } from "react";
import { Camera } from "lucide-react";
import { FileUpload } from "@/components/files/FileUpload";
import { FileList } from "@/components/files/FileList";

const PURPOSE = "portal_booking_photo";
const ACCEPT = "image/*,video/mp4";

export function PortalBookingPhotos({ appointmentId }) {
  const [nonce, setNonce] = useState(0);
  const onUploaded = useCallback(() => setNonce((n) => n + 1), []);
  if (!appointmentId) return null;
  return (
    <div
      className="mt-4 rounded-2xl p-5 text-left"
      style={{ backgroundColor: "#FFFFFF", border: "1px solid #E4E4E7" }}
      data-testid="portal-booking-photos"
    >
      <div className="flex items-center gap-2 mb-2">
        <Camera size={16} style={{ color: "#71717A" }} />
        <div className="text-sm font-semibold" style={{ color: "#18181B" }}>
          Add photos (optional)
        </div>
      </div>
      <p className="text-xs mb-3" style={{ color: "#71717A" }}>
        Share photos of your pool, yard, or the issue you&apos;re reporting.
        We&apos;ll review before your visit.
      </p>
      <FileUpload
        purpose={PURPOSE}
        linkedEntityType="portal_appointment"
        linkedEntityId={appointmentId}
        accept={ACCEPT}
        multiple
        maxFiles={5}
        onUploaded={onUploaded}
        buttonLabel="Attach photos or MP4"
      />
      <div className="mt-3">
        <FileList
          key={nonce}
          linkedEntityType="portal_appointment"
          linkedEntityId={appointmentId}
          purpose={PURPOSE}
          canDelete
          emptyLabel="No photos attached."
        />
      </div>
    </div>
  );
}

export default PortalBookingPhotos;
