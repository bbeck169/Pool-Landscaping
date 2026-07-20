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

# Phase 56.2 (bug fix Feb-2026) — identity is the only hard requirement.
# Missing address parts (street/city/state/postal) are stored as null and
# reported as row-level warnings instead of aborting the import — real-world
# CSVs frequently omit these for prospects, service-address-pending accounts,
# or landscaping-only customers with no fixed job site.
REQUIRED_NEW = {"first name", "last name"}

# Legacy header aliases → canonical new-header key. Hitting one of
# these still flips ``is_legacy=True`` because the presence of a truly
# old-style column (``Name``, ``Address``, ``Zip``) means the caller
# probably uploaded a pre-Phase-56 export and deserves the deprecation
# nudge in the response payload.
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

# Modern header aliases → canonical new-header key. These are variant
# spellings of columns that already exist in the Phase-56 12-column
# template (e.g. ``Tag`` vs ``Tags``, ``First`` vs ``First Name``).
# Resolving one of these does NOT flip ``is_legacy`` because the CSV
# is structurally the new shape, just with a slightly different label.
MODERN_ALIAS: dict[str, str] = {
    # Tag / tags — CSV exporters split ~50/50 on plural vs. singular.
    "tag": "tags",
    # Name variants
    "first": "first name",
    "given name": "first name",
    "last": "last name",
    "family name": "last name",
    "surname": "last name",
    # Address / postal variants that are just wording differences.
    "service address": "service address street",
    "service address line 1": "service address street",
    "address line 1": "service address street",
    "address1": "service address street",
    "postal": "postal code",
    # Phone variant
    "cell phone": "mobile",
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
    return _parse_customer_since_impl(raw)[0]


def parse_customer_since_verbose(raw: Optional[str]) -> tuple[Optional[str], bool]:
    """Like ``parse_customer_since`` but also returns whether the parsed
    date is in the future (relative to today, UTC calendar day). Callers
    that surface warnings use this variant; the classic ``parse_customer_since``
    stays intact for anything else in the codebase."""
    return _parse_customer_since_impl(raw)


def _parse_customer_since_impl(raw: Optional[str]) -> tuple[Optional[str], bool]:
    """Return ``(iso_date, is_future)``. ``is_future`` — parsed date is
    after today (UTC). See ``parse_customer_since_verbose_partial`` when
    the caller also needs the "year only" partial-parse flag."""
    parsed, is_future, _partial = _parse_customer_since_impl_verbose(raw)
    return parsed, is_future


def _parse_customer_since_impl_verbose(raw: Optional[str]) -> tuple[Optional[str], bool, bool]:
    if raw is None:
        return None, False, False
    s = str(raw).strip().replace(",", " ")  # Phase 56.1 — kill embedded commas
    s = re.sub(r"\s+", " ", s)
    if not s:
        return None, False, False
    this_year = datetime.utcnow().year
    parsed: Optional[str] = None
    partial_year_only = False

    # ISO first.
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(s, fmt).date().isoformat()
            break
        except ValueError:
            pass

    # US MDY (with or without year).
    if parsed is None:
        m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", s)
        if m:
            mo, dy, yr = int(m.group(1)), int(m.group(2)), m.group(3)
            y = int(yr) if yr else this_year
            if y < 100: y += 2000
            try:
                parsed = date(y, mo, dy).isoformat()
            except ValueError:
                parsed = None

    # Feb-2026 real-world CSV fix — bare year (e.g. "2023").
    # A caller who wrote just the year has no way to convey a specific
    # day, so we assume Jan 1 of that year. Callers surface this via
    # the "partial — assumed Jan 1" warning (see build_customer_doc).
    if parsed is None:
        m = re.fullmatch(r"(\d{4})", s)
        if m:
            y = int(m.group(1))
            if 1900 <= y <= 2100:
                try:
                    parsed = date(y, 1, 1).isoformat()
                    partial_year_only = True
                except ValueError:
                    parsed = None

    # Month-name variants — tokens now guaranteed comma-free above.
    if parsed is None:
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
            try:
                parsed = date(y, mo, dy).isoformat()
            except ValueError:
                parsed = None

    if parsed is None:
        return None, False, False
    try:
        is_future = date.fromisoformat(parsed) > date.today()
    except Exception:
        is_future = False
    return parsed, is_future, partial_year_only


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
        if nk in MODERN_ALIAS:
            out[MODERN_ALIAS[nk]] = ("" if v is None else str(v).strip())
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
                        normalize_phone) -> tuple[Optional[dict], Optional[str], list[str]]:
    """Turn a canonicalized row into a customer document.

    Returns ``(doc, error, warnings)``. When ``error`` is set the doc is
    ``None`` and the row is skipped; ``warnings`` is a list of human-
    readable strings describing recoverable issues (future customer_since
    date, missing address components, invalid state, unparseable date).

    Only identity (first + last name) is hard-required. Missing service-
    address parts are stored as null and reported as warnings so real-
    world CSVs — landscape-only accounts, prospects, address-pending
    customers — still import cleanly.
    """
    warnings: list[str] = []

    # Identity guard — need at least a first and last name to have any
    # hope of matching this record to a human. Everything else is soft.
    first = (canon.get("first name") or "").strip()
    last = (canon.get("last name") or "").strip()
    if not first and not last:
        return None, "missing required: first name and last name", warnings
    if not first:
        return None, "missing required: first name", warnings
    if not last:
        return None, "missing required: last name", warnings
    # "0" (or similar sentinels) → keep verbatim. Do NOT coerce to blank
    # or reject: the CSV author put it there intentionally, we surface it.
    if last == "0" or first == "0":
        warnings.append("name field contains '0' — kept verbatim")

    # State — 2-letter code required only when a value is supplied.
    state_raw = (canon.get("state") or "").strip()
    state: Optional[str] = None
    if state_raw:
        state = _upper_state(state_raw)
        if not state:
            warnings.append(f"state '{state_raw}' is not a 2-letter code — kept verbatim")
            state = state_raw
    else:
        warnings.append("state missing — stored as null")

    email = (canon.get("email") or "").strip()
    if email and not _valid_email(email):
        warnings.append(f"email {email!r} failed validation — kept verbatim")

    phone_home_raw = _strip_phone_noise(canon.get("phone"))
    phone_mobile_raw = _strip_phone_noise(canon.get("mobile"))
    # Feb-2026 real-world CSV fix — when Phone column is blank but Mobile
    # is set, promote Mobile into the "phone" role too. Reason: downstream
    # matchers (SMS inbound, invoice merge fields, comm-token substitution)
    # historically look at both ``phone`` scalar and ``phones[type=home]``.
    # Duplicating the number preserves match parity when the CSV only
    # carries a mobile.
    phone_promoted_from_mobile = False
    if not phone_home_raw and phone_mobile_raw:
        phone_home_raw = phone_mobile_raw
        phone_promoted_from_mobile = True
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
    if phone_promoted_from_mobile:
        warnings.append("phone column blank — mobile value promoted to phone")

    full_name = f"{first} {last}".strip()

    since_raw = (canon.get("customer since") or "").strip()
    since, since_is_future, since_partial = _parse_customer_since_impl_verbose(since_raw)
    if since_raw and not since:
        warnings.append(f"customer_since {since_raw!r} unparseable — raw value preserved")
    if since_is_future:
        warnings.append(f"customer_since {since} is in the future — preserved as-is")
    if since_partial:
        warnings.append(f"customer_since {since_raw!r} partial — assumed Jan 1")

    street = (canon.get("service address street") or "").strip()
    city = (canon.get("city") or "").strip()
    state_final = state  # normalized 2-letter or raw preserved above
    postal = (canon.get("postal code") or "").strip()  # preserves leading zeros
    if not street:
        warnings.append("service address street missing — stored as null")
    if not city:
        warnings.append("city missing — stored as null")
    if not postal:
        warnings.append("postal code missing — stored as null")

    # Feb-2026 real-world CSV fix — populate the flat ``address`` string
    # that CustomersList / CustomerDetail render. Without this, imported
    # rows show a blank address column even though the parts are stored
    # under ``service_address``. We keep the nested block for newer
    # consumers (comm_tokens, google.py) and add flat + top-level fields
    # for legacy display + comm-token substitution.
    address_parts = [p for p in (street, city, state_final, postal) if p]
    address_flat = ", ".join(address_parts)

    doc = {
        "tenant_id": tenant_id,
        "first_name": first,
        "last_name": last,
        "name": full_name,
        "email": email.lower() if email else "",
        "phones": phones,
        # keep scalar `phone` field for legacy consumers (RC matcher, invoices).
        "phone": phone_mobile or phone_home or "",
        # Raw phone values preserved for audit / re-parsing without touching
        # phones[] which downstream consumers already depend on.
        "phone_raw": phone_home_raw or None,
        "mobile_raw": phone_mobile_raw or None,
        # Feb-2026 real-world CSV fix — flat + top-level address fields
        # so CustomersList / CustomerDetail render populated rows and
        # comm-token substitution (customer.address_line1) resolves
        # without an extra service_address lookup.
        "address": address_flat,
        "address_line1": street or None,
        "city": city or None,
        "state": state_final or None,
        "postal_code": postal or None,
        "service_address": {
            "street": street or None,
            "city": city or None,
            "state": state_final or None,
            "postal_code": postal or None,
        },
        "customer_since": since,
        "customer_since_raw": since_raw or None,
        "tags": _parse_tags(canon.get("tags") or ""),
        "notes": _clean_notes(canon.get("notes") or ""),
    }
    return doc, None, warnings


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
