"""Phase 56 · Customer CSV importer & template. Phase 56.1 · real-world hardening.
See CAUSES 1-10 in HANDOFF (semicolon delimiter, comma-in-date, phone noise,
HTML in notes, tags-with-commas, etc.).
"""
from __future__ import annotations

import csv
import html as _html
import io
import re
from datetime import date, datetime
from typing import Optional

from utils import new_id, now_iso

# ─── Column normalization ──────────────────────────────────────────────
NEW_HEADERS = [
    "customer since", "email", "service address street", "city", "state",
    "postal code", "phone", "mobile", "first name", "last name", "tags", "notes",
]

REQUIRED_NEW = {
    "service address street", "city", "state", "postal code",
    "first name", "last name",
}

# Legacy header aliases → canonical new-header key.
LEGACY_ALIAS: dict[str, str] = {
    "address": "service address street",
    "street": "service address street",
    "zip": "postal code",
    "zip code": "postal code",
    "zipcode": "postal code",
    "cell": "mobile",
    "mobile phone": "mobile",
    "cellphone": "mobile",
    "home phone": "phone",
    "landline": "phone",
    "notes/memo": "notes",
    "memo": "notes",
}


def _norm_key(k: str) -> str:
    """Lowercase + collapse whitespace for header comparison."""
    return re.sub(r"\s+", " ", (k or "").strip().lower())


# ─── Tolerant date parser ─────────────────────────────────────────────
_MONTHS: dict[str, int] = {
    m.lower(): i for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
}
_MONTHS_FULL: dict[str, int] = {
    m.lower(): i for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"], 1)
}


def parse_customer_since(raw: Optional[str]) -> Optional[str]:
    """Accepts "Jul 01 2026", "Jul 01, 2026" (Phase 56.1 · comma variant),
    "Jun 23", "6/23/2026", "2026-06-23", "23 Jun 2026", "July 1, 2026".
    Returns ISO ``YYYY-MM-DD`` or None on failure. Year defaults to
    the current calendar year when omitted."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", " ")  # Phase 56.1 — kill embedded commas
    s = re.sub(r"\s+", " ", s)
    if not s:
        return None
    this_year = datetime.utcnow().year

    # ISO first.
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass

    # US MDY (with or without year).
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", s)
    if m:
        mo, dy, yr = int(m.group(1)), int(m.group(2)), m.group(3)
        y = int(yr) if yr else this_year
        if y < 100: y += 2000
        try: return date(y, mo, dy).isoformat()
        except ValueError: return None

    # Month-name variants — tokens now guaranteed comma-free above.
    tokens = [t for t in s.split(" ") if t]
    mo = dy = yr = None
    for t in tokens:
        tl = t.lower().rstrip(".")
        if tl in _MONTHS:        mo = _MONTHS[tl]
        elif tl in _MONTHS_FULL: mo = _MONTHS_FULL[tl]
        elif t.isdigit():
            n = int(t)
            if n > 31 and yr is None:  yr = n
            elif dy is None and 1 <= n <= 31: dy = n
            elif yr is None: yr = n
    if mo and dy:
        y = yr if yr else this_year
        if y and y < 100: y += 2000
        try: return date(y, mo, dy).isoformat()
        except ValueError: return None
    return None


# ─── Field validators ─────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _valid_email(v: str) -> bool:
    return bool(_EMAIL_RE.match(v or ""))


def _upper_state(v: str) -> Optional[str]:
    s = (v or "").strip().upper()
    if len(s) != 2 or not s.isalpha():
        return None
    return s


def _parse_tags(v: str) -> list[str]:
    if not v: return []
    parts = [p.strip() for p in v.split(",")]
    return [p for p in parts if p]


# ─── Phase 56.1 · phone-noise stripper ────────────────────────────────
_PHONE_NOISE = re.compile(
    r"\b(?:land\s*line|cell(?:\s*phone)?|home(?:\s*phone)?|mobile|work|"
    r"office|fax|primary|secondary|main|day|evening|night)\b",
    re.IGNORECASE,
)


def _strip_phone_noise(raw: Optional[str]) -> str:
    """Remove trailing/inline words like 'Land Line', 'Cell', etc. from a
    phone string BEFORE handing to the E.164 normalizer. Leaves digits +
    punctuation. Empty input → ``""``."""
    if not raw: return ""
    s = _PHONE_NOISE.sub(" ", str(raw))
    return re.sub(r"\s+", " ", s).strip()


# ─── Phase 56.1 · HTML notes cleaner ──────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_notes(raw: Optional[str]) -> str:
    """Decode HTML entities → strip tags → collapse whitespace → cap
    at 2000 chars. Handles Excel/RTF exports that leak `<p>`, `&nbsp;`,
    `&apos;`, etc. into the Notes column."""
    if not raw: return ""
    s = _html.unescape(str(raw))
    s = _TAG_RE.sub(" ", s)
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:2000]


# ─── Row normalization ────────────────────────────────────────────────
def _canon_row(raw: dict[str, str]) -> tuple[dict[str, str], bool]:
    """Map any CSV row's keys to the canonical new-header space.

    Returns ``(canonical_dict, is_legacy)`` — ``is_legacy`` is True if
    any legacy alias was resolved.
    """
    out: dict[str, str] = {}
    is_legacy = False
    for k, v in (raw or {}).items():
        nk = _norm_key(k)
        if nk in NEW_HEADERS:
            out[nk] = ("" if v is None else str(v).strip())
            continue
        if nk in LEGACY_ALIAS:
            out[LEGACY_ALIAS[nk]] = ("" if v is None else str(v).strip())
            is_legacy = True
            continue
        # Un-mapped header — carry through under its raw key so admin
        # sees it in errors if it was required.
        out[nk] = ("" if v is None else str(v).strip())
    return out, is_legacy


# ─── Row → customer doc ───────────────────────────────────────────────
def build_customer_doc(canon: dict[str, str], tenant_id: str,
                        normalize_phone) -> tuple[Optional[dict], Optional[str]]:
    """Turn a canonicalized row into a customer document or return an
    error string.

    ``normalize_phone`` is passed in so the caller controls which
    normalizer to use — we reuse Phase 54's ``_normalize_phone_e164``
    from ``routers.ringcentral`` per the phase brief.
    """
    missing = [f for f in REQUIRED_NEW if not (canon.get(f) or "").strip()]
    if missing:
        return None, "missing required: " + ", ".join(sorted(missing))

    state = _upper_state(canon.get("state") or "")
    if not state:
        return None, "state must be a 2-letter code"

    email = (canon.get("email") or "").strip()
    if email and not _valid_email(email):
        return None, f"invalid email: {email!r}"

    phone_home_raw = _strip_phone_noise(canon.get("phone"))
    phone_mobile_raw = _strip_phone_noise(canon.get("mobile"))
    phone_home = normalize_phone(phone_home_raw) if phone_home_raw else None
    phone_mobile = normalize_phone(phone_mobile_raw) if phone_mobile_raw else None

    phones: list[dict] = []
    if phone_home_raw:
        phones.append({"type": "home", "number": phone_home or phone_home_raw,
                        "raw": phone_home_raw if not phone_home else None,
                        "e164": phone_home})
    if phone_mobile_raw:
        phones.append({"type": "mobile", "number": phone_mobile or phone_mobile_raw,
                        "raw": phone_mobile_raw if not phone_mobile else None,
                        "e164": phone_mobile})

    first = canon["first name"].strip()
    last = canon["last name"].strip()
    full_name = f"{first} {last}".strip()

    since = parse_customer_since(canon.get("customer since"))

    doc = {
        "tenant_id": tenant_id,
        "first_name": first,
        "last_name": last,
        "name": full_name,
        "email": email.lower() if email else "",
        "phones": phones,
        # keep scalar `phone` field for legacy consumers (RC matcher, invoices).
        "phone": phone_mobile or phone_home or "",
        "service_address": {
            "street": canon["service address street"].strip(),
            "city": canon["city"].strip(),
            "state": state,
            "postal_code": canon["postal code"].strip(),  # preserves leading zeros
        },
        "customer_since": since,
        "tags": _parse_tags(canon.get("tags") or ""),
        "notes": _clean_notes(canon.get("notes") or ""),
    }
    return doc, None


# ─── CSV reader (tolerant · Phase 56.1 semicolon-aware) ───────────────
def _detect_delimiter(sample: str) -> str:
    """Prefer whichever of ``,`` / ``;`` / ``\\t`` shows up more often on
    the first non-empty line, outside of quoted regions. Falls back to
    csv.Sniffer if the naive count is a tie."""
    first = ""
    for line in sample.splitlines():
        if line.strip():
            first = line
            break
    if not first: return ","
    unquoted = re.sub(r'"[^"]*"', "", first)
    counts = {c: unquoted.count(c) for c in (",", ";", "\t")}
    best, best_n = max(counts.items(), key=lambda x: x[1])
    if best_n > 0:
        return best
    try:
        return csv.Sniffer().sniff(sample[:2048], delimiters=",;\t").delimiter
    except Exception:
        return ","


def read_csv(text: str) -> list[dict[str, str]]:
    if not text: return []
    text = text.lstrip("\ufeff")
    delim = _detect_delimiter(text[:4096])
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    rows: list[dict[str, str]] = []
    for raw in reader:
        # Drop the sentinel empty-string key that DictReader inserts when
        # the row has more fields than the header (trailing ";" columns).
        cleaned = {k: v for k, v in raw.items() if k not in (None, "")}
        if any((v or "").strip() for v in cleaned.values() if isinstance(v, str)):
            rows.append(cleaned)
    return rows


# ─── Template ─────────────────────────────────────────────────────────
TEMPLATE_HEADERS = [
    "Customer Since", "Email", "Service address Street", "City", "State",
    "Postal Code", "Phone", "Mobile", "First Name", "Last Name", "Tags", "Notes",
]

TEMPLATE_SAMPLE_ROW = [
    "Jul 01 2026", "aduganahemiah@gmail.com", "12474 West Forest Pleasant Place",
    "Peoria", "AZ", "85383", "", "4804505020", "Nehemiah", "Abuga",
    "One Time Job", "",
]


def render_template_csv() -> str:
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(TEMPLATE_HEADERS)
    w.writerow(TEMPLATE_SAMPLE_ROW)
    return buf.getvalue()
