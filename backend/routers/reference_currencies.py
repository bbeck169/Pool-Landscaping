"""Phase G1.6 · Feb-2026 — ISO 4217 currency catalog.

Reads the full ISO catalog from ``pycountry`` and exposes it as a
single cached list. Backed by the process-lifetime cache below (the
catalog changes only when ``pycountry`` is redeployed).

Symbols are curated for the top-30 most-used currencies (matching
the whitelist the Business tab exposes as a shortlist) and fall
back to the ISO code for the long tail.
"""
from __future__ import annotations

from typing import List, Dict, Any, Set

from fastapi import APIRouter, Depends

from utils import get_current_user


router = APIRouter(tags=["Reference"])


# Curated symbol map for the codes admins are actually likely to
# select. Any code not present here falls back to the ISO letters —
# perfectly acceptable for a Business tab dropdown, and mirrors what
# Stripe / QBO do for less-common currencies.
_SYMBOLS: Dict[str, str] = {
    "USD": "$",   "EUR": "€",   "GBP": "£",   "JPY": "¥",   "CNY": "¥",
    "AUD": "$",   "CAD": "$",   "CHF": "Fr",  "HKD": "$",   "NZD": "$",
    "SEK": "kr",  "KRW": "₩",   "SGD": "$",   "NOK": "kr",  "MXN": "$",
    "INR": "₹",   "RUB": "₽",   "ZAR": "R",   "TRY": "₺",   "BRL": "R$",
    "TWD": "NT$", "DKK": "kr",  "PLN": "zł",  "THB": "฿",   "IDR": "Rp",
    "HUF": "Ft",  "CZK": "Kč",  "ILS": "₪",   "CLP": "$",   "PHP": "₱",
    "AED": "د.إ", "SAR": "﷼",   "MYR": "RM",  "COP": "$",   "ARS": "$",
}


_CACHE: Dict[str, Any] = {"currencies": None, "codes": None}


def _build_catalog() -> Dict[str, Any]:
    """Return the pycountry currency catalog reshaped for the API.

    Falls back to the F1.1 shortlist if ``pycountry`` isn't importable
    (dep drift guard — the wider Business tab still boots)."""
    try:
        import pycountry
    except Exception:  # noqa: BLE001
        codes = ("USD", "EUR", "GBP", "CAD", "AUD")
        return {
            "codes": set(codes),
            "currencies": [
                {"code": c, "name": c, "symbol": _SYMBOLS.get(c, c)}
                for c in codes
            ],
        }
    rows: List[Dict[str, str]] = []
    codes: Set[str] = set()
    for c in pycountry.currencies:
        code = getattr(c, "alpha_3", None)
        if not code:
            continue
        name = getattr(c, "name", code)
        codes.add(code)
        rows.append({
            "code":   code,
            "name":   name,
            "symbol": _SYMBOLS.get(code, code),
        })
    rows.sort(key=lambda r: r["code"])
    return {"codes": codes, "currencies": rows}


def _cached() -> Dict[str, Any]:
    if _CACHE["currencies"] is None:
        _CACHE.update(_build_catalog())
    return _CACHE


def is_valid_iso_currency(code: str) -> bool:
    if not code:
        return False
    return code.strip().upper() in _cached()["codes"]


@router.get("/reference/currencies")
async def list_currencies(_user: dict = Depends(get_current_user)):
    return {"currencies": _cached()["currencies"]}
