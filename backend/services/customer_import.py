"""Phase 56 · Customer CSV importer & template.

12-column spec (case-insensitive, tolerates leading/trailing whitespace
in headers). Order below is authoritative for the template download but
importer accepts any column order.

| # | Header                    | Type    |
|---|---------------------------|---------|
| 1 | Customer Since            | date    |
| 2 | Email                     | email   |
| 3 | Service address Street    | text*   |
| 4 | City                      | text*   |
| 5 | State                     | text*   |
| 6 | Postal Code               | text*   |
| 7 | Phone                     | phone   |
| 8 | Mobile                    | phone   |
| 9 | First Name                | text*   |
| 10| Last Name                 | text*   |
| 11| Tags                      | csv-list|
| 12| Notes                     | text    |

`*` = required. Rejecting a row still returns an itemized error message
in the response so admins can fix and re-upload.

Back-compat: if the CSV uses the OLD single-address / single-phone /
name column headers (e.g., ``Name``, ``Address``, ``Phone``), the
importer falls back to the legacy mapper for that upload and returns
``deprecation_warnings`` so the frontend can nudge the admin to
migrate.
"""
from __future__ import annotations

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
    """Accepts "Jul 01 2026", "Jun 23", "6/23/2026", "2026-06-23",
    "23 Jun 2026", "July 1, 2026". Returns ISO ``YYYY-MM-DD`` or None
    on failure. Year defaults to the current calendar year when
    omitted."""
    if raw is None:
        return None
    s = str(raw).strip()
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

    # "Jul 01 2026" / "Jul 01" / "July 1, 2026" / "23 Jun 2026".
    tokens = [t for t in re.split(r"[,\s]+", s) if t]
    mo = dy = yr = None
    for t in tokens:
        tl = t.lower().rstrip(",.")
        if tl in _MONTHS:      mo = _MONTHS[tl]
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

    phone_home = normalize_phone(canon.get("phone")) if canon.get("phone") else None
    phone_mobile = normalize_phone(canon.get("mobile")) if canon.get("mobile") else None
    if canon.get("phone") and not phone_home:
        return None, f"invalid phone: {canon.get('phone')!r}"
    if canon.get("mobile") and not phone_mobile:
        return None, f"invalid mobile: {canon.get('mobile')!r}"

    phones: list[dict] = []
    if phone_home:
        phones.append({"type": "home", "number": phone_home})
    if phone_mobile:
        phones.append({"type": "mobile", "number": phone_mobile})

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
        "notes": (canon.get("notes") or "").strip(),
    }
    return doc, None


# ─── CSV reader (tolerant) ────────────────────────────────────────────
def read_csv(text: str) -> list[dict[str, str]]:
    import csv
    if not text: return []
    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader if any((v or "").strip() for v in row.values())]


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
