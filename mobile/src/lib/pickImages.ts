/**
 * TD-88e · shared multi-select library picker.
 *
 * Opens the photo library with `allowsMultipleSelection` +
 * `selectionLimit = remainingCap` (each surface passes its own
 * `<cap> - <current count>`). `allowsEditing` is intentionally never
 * passed: it is ignored / mutually exclusive with multi-select.
 *
 * Returns `null` when nothing should happen — `remainingCap < 1` (the
 * picker is NOT opened; callers show their own "max reached" state),
 * permission denied, or the user canceled. Callers that need custom
 * denial UX (`canAskAgain` → Settings sheet / toast) keep their own
 * permission prompt before calling; re-requesting here is a no-op.
 *
 * `selectionLimit` is not honoured by the web picker (and some older
 * Android pickers), so results are also trimmed to `remainingCap`.
 * Camera capture stays single-shot at each call-site.
 */
import * as ImagePicker from "expo-image-picker";

export type PickImagesMultiOpts = {
  remainingCap: number;
  quality?: number;
  base64?: boolean;
  mediaTypes?: ImagePicker.MediaType[];
};

export async function pickImagesMulti(opts: PickImagesMultiOpts): Promise<ImagePicker.ImagePickerAsset[] | null> {
  const cap = Math.floor(Number(opts.remainingCap) || 0);
  if (cap < 1) return null;
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!perm?.granted) return null;
  const result = await ImagePicker.launchImageLibraryAsync({
    allowsMultipleSelection: true,
    selectionLimit: cap,
    orderedSelection: true,
    quality: opts.quality ?? 0.7,
    mediaTypes: opts.mediaTypes ?? ["images"],
    ...(opts.base64 ? { base64: true } : {}),
  });
  if (result.canceled) return null;
  const assets = (result.assets || []).filter((a) => !!a?.uri).slice(0, cap);
  return assets.length ? assets : null;
}
