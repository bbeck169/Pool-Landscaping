"""Feb-2026 · Photos thumbnails + preview derivatives.

Pillow-based helpers used by:
  * ``POST /api/jobs/{jid}/photos`` (fresh upload dual-write)
  * ``POST /api/admin/migrations/migrate-photos-to-s3`` (Phase 2
    backfill of legacy base64 rows)

Produces two JPEG derivatives per photo, EXIF-stripped, aspect-
preserving:

  * ``thumb``    — max ``PHOTOS_THUMB_MAX_EDGE`` px (default 320)
  * ``preview``  — max ``PHOTOS_PREVIEW_MAX_EDGE`` px (default 1280)

Every function is safe to call on any input; failures return
``None`` and log a warning. Callers MUST guard on the return value
so a bad image never blocks the parent write.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# HEIC support — optional. If ``pillow-heif`` is present, register
# its opener so ``Image.open`` handles .heic/.heif. Otherwise HEIC
# uploads land in the 415-unsupported branch.
# ─────────────────────────────────────────────────────────────────
_HEIC_AVAILABLE = False
try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
    _HEIC_AVAILABLE = True
except Exception:
    _HEIC_AVAILABLE = False


def heic_available() -> bool:
    """Are ``.heic`` / ``.heif`` MIME types decodable?"""
    return _HEIC_AVAILABLE


# ─────────────────────────────────────────────────────────────────
# MIME allowlist — enforced by the upload guardrail.
# ─────────────────────────────────────────────────────────────────
_ALWAYS_ALLOWED_MIMES = frozenset({
    "image/jpeg", "image/jpg", "image/png", "image/webp",
})


def allowed_mimes() -> frozenset:
    """Env-driven mime allowlist. HEIC toggles automatically off
    when ``pillow-heif`` isn't installed, regardless of
    ``PHOTOS_ALLOW_HEIC``."""
    allow_heic = (os.environ.get("PHOTOS_ALLOW_HEIC") or "true").strip().lower() == "true"
    if allow_heic and _HEIC_AVAILABLE:
        return _ALWAYS_ALLOWED_MIMES | {"image/heic", "image/heif"}
    return _ALWAYS_ALLOWED_MIMES


def max_upload_bytes() -> int:
    """Cap for decoded upload payload. Default 5 MB."""
    try:
        v = int(os.environ.get("PHOTOS_MAX_UPLOAD_BYTES") or "5242880")
    except (TypeError, ValueError):
        v = 5_242_880
    # sanity clamp — never accept a runaway value
    return max(65_536, min(v, 50 * 1024 * 1024))


def _thumb_max_edge() -> int:
    try:
        return max(64, min(int(os.environ.get("PHOTOS_THUMB_MAX_EDGE") or "320"), 1024))
    except (TypeError, ValueError):
        return 320


def _preview_max_edge() -> int:
    try:
        return max(320, min(int(os.environ.get("PHOTOS_PREVIEW_MAX_EDGE") or "1280"), 4096))
    except (TypeError, ValueError):
        return 1280


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────
def is_allowed_mime(mime: Optional[str]) -> bool:
    if not mime or not isinstance(mime, str):
        return False
    return mime.strip().lower() in allowed_mimes()


def _resample_jpeg(blob: bytes, max_edge: int, quality: int) -> Optional[bytes]:
    """Load ``blob``, resize longest edge to ``max_edge`` (no upscale),
    strip EXIF, re-encode as JPEG at ``quality``. Returns ``None`` on
    any decode/encode failure; NEVER raises."""
    try:
        from PIL import Image  # local import so this module loads without PIL.
    except Exception as exc:
        logger.warning("[photos-deriv] PIL import failed: %s", exc)
        return None
    try:
        with Image.open(io.BytesIO(blob)) as im:
            # Normalize to RGB so JPEG encode never trips on palette /
            # alpha channels; alpha-composite over white.
            if im.mode in ("RGBA", "LA") or (
                im.mode == "P" and "transparency" in im.info
            ):
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            w, h = im.size
            longest = max(w, h)
            if longest > max_edge:
                scale = max_edge / float(longest)
                im = im.resize((max(1, int(w * scale)),
                                 max(1, int(h * scale))),
                                 Image.LANCZOS)
            out = io.BytesIO()
            # ``exif=b""`` strips any embedded EXIF including geotag.
            im.save(out, format="JPEG", quality=quality, optimize=True,
                     progressive=True, exif=b"")
            return out.getvalue()
    except Exception as exc:
        logger.warning("[photos-deriv] resample failed max_edge=%s q=%s err=%s",
                        max_edge, quality, exc)
        return None


def generate_derivatives(blob: bytes) -> Optional[Tuple[bytes, bytes]]:
    """Given the original decoded photo bytes, return
    ``(thumb_bytes, preview_bytes)`` — both JPEG, EXIF-stripped.
    Returns ``None`` when Pillow can't parse the input at all
    (e.g. HEIC without pillow-heif, corrupt bytes)."""
    thumb = _resample_jpeg(blob, _thumb_max_edge(), quality=78)
    if thumb is None:
        return None
    preview = _resample_jpeg(blob, _preview_max_edge(), quality=82)
    if preview is None:
        return None
    return thumb, preview
