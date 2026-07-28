/**
 * F2f · Feb-2026 — Staff/user "My Profile" page.
 *
 * Lets any authenticated user update their own profile photo (via F0
 * upload → PATCH /api/users/me → ``profile_photo_url`` stored as the
 * F0 download URL ``/api/files/{id}/download``). Emoji or initial-badge
 * fallback when no photo is set.
 *
 * Design intent: this is the smallest possible "settings tile" —
 * dedicated page can be replaced with an inline settings section
 * later without touching the underlying wiring.
 */
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { User as UserIcon } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { FileUpload } from "@/components/files/FileUpload";
import { AuthedImage } from "@/components/files/AuthedImage";

// Exported for Vitest — mirrors the persona helper for consistency.
export function buildStaffPhotoUrl(fileId) {
  if (!fileId) return "";
  return `/api/files/${fileId}/download`;
}

function InitialBadge({ name, size = 96 }) {
  const initial = String(name || "?").trim().slice(0, 1).toUpperCase();
  return (
    <div
      className="rounded-full bg-zinc-200 text-zinc-700 flex items-center justify-center font-bold"
      style={{ width: size, height: size, fontSize: size / 2.5 }}
      data-testid="profile-initial-badge"
    >
      {initial || <UserIcon size={size / 2} />}
    </div>
  );
}

export default function MyProfilePage() {
  const { user: ctxUser } = useAuth();
  const [me, setMe] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/auth/me").then(setMe).catch(() => setMe(ctxUser || null));
  }, []);

  const patch = async (fields) => {
    setSaving(true);
    try {
      const res = await api.patch("/users/me", fields);
      setMe(res.user || me);
      // Also refresh cached user in localStorage so header avatars pick it up.
      try {
        const stored = localStorage.getItem("user");
        if (stored) {
          const parsed = JSON.parse(stored);
          localStorage.setItem("user", JSON.stringify({ ...parsed, ...res.user }));
        }
      } catch { /* nvm */ }
      toast.success("Profile updated.");
    } catch (e) { toast.error(e?.message || "Update failed."); }
    finally { setSaving(false); }
  };

  const onUploaded = (payload) => {
    const id = payload?.id || payload?.file_id;
    if (!id) { toast.error("Upload succeeded but no id returned."); return; }
    patch({ profile_photo_url: buildStaffPhotoUrl(id) });
  };

  const onRemove = () => patch({ profile_photo_url: null });

  if (!me) {
    return <div className="p-8 text-sm text-zinc-500">Loading…</div>;
  }
  const photoUrl = me.profile_photo_url;
  const fileIdMatch = photoUrl?.match(/^\/api\/files\/([^/?#]+)\/download/);
  const fileId = fileIdMatch ? fileIdMatch[1] : null;

  return (
    <div className="max-w-2xl mx-auto p-6" data-testid="my-profile-page">
      <h1 className="text-2xl font-bold mb-1">My Profile</h1>
      <p className="text-sm text-zinc-500 mb-6">
        Update your display photo and basic info. Changes are visible to your team.
      </p>

      <div
        className="rounded-2xl p-6 bg-white border border-zinc-200"
        data-testid="profile-photo-card"
      >
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 mb-4">
          Profile Photo
        </h2>
        <div className="flex items-start gap-6">
          <div className="shrink-0" data-testid="profile-current-photo">
            {fileId
              ? <AuthedImage fileId={fileId} size={96} className="rounded-full" testid="profile-photo-img" />
              : <InitialBadge name={me.name || me.email} size={96} />}
          </div>
          <div className="flex-1">
            <FileUpload
              purpose="staff_profile_photo"
              linkedEntityType="user"
              linkedEntityId={me.id}
              accept="image/png,image/jpeg,image/webp"
              multiple={false}
              maxFiles={1}
              onUploaded={onUploaded}
              buttonLabel="Upload profile photo (PNG/JPG/WebP, max 5MB)"
              disabled={saving}
            />
            <p className="text-xs text-zinc-500 mt-2">
              Recommended: 400×400px square, under 5 MB.
            </p>
            {photoUrl ? (
              <button
                type="button"
                onClick={onRemove}
                disabled={saving}
                className="text-xs font-semibold text-red-600 hover:text-red-800 mt-3 disabled:opacity-50"
                data-testid="profile-remove-photo"
              >
                Remove photo
              </button>
            ) : null}
          </div>
        </div>
      </div>

      <div
        className="mt-4 rounded-2xl p-6 bg-white border border-zinc-200"
        data-testid="profile-identity-card"
      >
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 mb-4">
          Identity
        </h2>
        <dl className="text-sm space-y-2">
          <div className="flex justify-between"><dt className="text-zinc-500">Name</dt><dd data-testid="profile-name">{me.name || "—"}</dd></div>
          <div className="flex justify-between"><dt className="text-zinc-500">Email</dt><dd data-testid="profile-email">{me.email}</dd></div>
          <div className="flex justify-between"><dt className="text-zinc-500">Role</dt><dd data-testid="profile-role">{me.role}</dd></div>
        </dl>
      </div>
    </div>
  );
}

export { InitialBadge };
