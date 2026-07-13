import httpx
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional

from utils import get_current_user

router = APIRouter()

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

# WMO weather code -> (short label, Ionicons name)
WMO = {
    0: ("Clear", "sunny-outline"),
    1: ("Mostly clear", "partly-sunny-outline"),
    2: ("Partly cloudy", "partly-sunny-outline"),
    3: ("Overcast", "cloud-outline"),
    45: ("Fog", "cloud-outline"),
    48: ("Fog", "cloud-outline"),
    51: ("Light drizzle", "rainy-outline"),
    53: ("Drizzle", "rainy-outline"),
    55: ("Heavy drizzle", "rainy-outline"),
    56: ("Freezing drizzle", "rainy-outline"),
    57: ("Freezing drizzle", "rainy-outline"),
    61: ("Light rain", "rainy-outline"),
    63: ("Rain", "rainy-outline"),
    65: ("Heavy rain", "rainy-outline"),
    66: ("Freezing rain", "rainy-outline"),
    67: ("Freezing rain", "rainy-outline"),
    71: ("Light snow", "snow-outline"),
    73: ("Snow", "snow-outline"),
    75: ("Heavy snow", "snow-outline"),
    77: ("Snow grains", "snow-outline"),
    80: ("Rain showers", "rainy-outline"),
    81: ("Rain showers", "rainy-outline"),
    82: ("Heavy showers", "thunderstorm-outline"),
    85: ("Snow showers", "snow-outline"),
    86: ("Snow showers", "snow-outline"),
    95: ("Thunderstorm", "thunderstorm-outline"),
    96: ("Thunderstorm", "thunderstorm-outline"),
    99: ("Thunderstorm", "thunderstorm-outline"),
}


@router.get("/weather/forecast")
async def forecast(lat: float = Query(...), lng: float = Query(...),
                   days: int = Query(14, ge=1, le=16),
                   user: dict = Depends(get_current_user)):
    """Daily forecast (high/low, rain %, condition) for scheduling. Uses Open-Meteo (keyless)."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(OPEN_METEO, params={
                "latitude": lat,
                "longitude": lng,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                "temperature_unit": "fahrenheit",
                "timezone": "auto",
                "forecast_days": days,
            })
    except httpx.HTTPError:
        raise HTTPException(424, "Could not reach the weather service")
    if r.status_code >= 400:
        raise HTTPException(424, "Weather service error")
    d = (r.json() or {}).get("daily") or {}
    times = d.get("time") or []
    out = {}
    for i, day in enumerate(times):
        code = (d.get("weather_code") or [])[i] if i < len(d.get("weather_code") or []) else 0
        label, icon = WMO.get(code, ("—", "cloud-outline"))
        out[day] = {
            "date": day,
            "high": round((d.get("temperature_2m_max") or [None])[i]) if i < len(d.get("temperature_2m_max") or []) and d["temperature_2m_max"][i] is not None else None,
            "low": round((d.get("temperature_2m_min") or [None])[i]) if i < len(d.get("temperature_2m_min") or []) and d["temperature_2m_min"][i] is not None else None,
            "precip": (d.get("precipitation_probability_max") or [None])[i] if i < len(d.get("precipitation_probability_max") or []) else None,
            "code": code,
            "label": label,
            "icon": icon,
        }
    return {"days": out}
