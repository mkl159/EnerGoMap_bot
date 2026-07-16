"""Accès au flux instantané des prix des carburants (API ODS, JSON).

Une seule requête récupère toutes les stations du rayon ; le filtrage
(rupture, fraîcheur des prix) et le tri se font localement.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from .config import (
    FUELS,
    MAX_CANDIDATES,
    ODS_BASE,
    PRICE_MAX_AGE_DAYS,
    SEARCH_RADII,
    STATS_CACHE_TTL,
    Fuel,
)


@dataclass
class Station:
    sid: int
    name: str            # "adresse, ville"
    ville: str
    lat: float
    lon: float
    price: float
    price_date: datetime | None
    dist_air_km: float = 0.0
    dist_road_km: float | None = None   # rempli par le routage
    duration_min: float | None = None
    score: float = field(default=0.0)


@dataclass
class SearchResult:
    stations: list[Station]
    radius_km: int
    nearer_out_of_stock: int   # stations plus proches mais en rupture


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def fetch_candidates(lat: float, lon: float, fuel: Fuel) -> SearchResult:
    """Cherche les stations vendant `fuel` autour de (lat, lon).

    Élargit le rayon (5→30 km) tant que moins de 5 stations valides.
    Retourne au plus MAX_CANDIDATES stations triées par distance à vol
    d'oiseau + le nombre de stations plus proches en rupture.
    """
    now = datetime.now(timezone.utc)
    max_age = timedelta(days=PRICE_MAX_AGE_DAYS)

    async with httpx.AsyncClient(timeout=15) as client:
        for radius in SEARCH_RADII:
            params = {
                "where": f"distance(geom, geom'POINT({lon} {lat})', {radius}km)",
                "limit": "100",
                "select": (
                    "id, adresse, ville, geom, carburants_indisponibles, "
                    f"{fuel.price_col}, {fuel.maj_col}"
                ),
            }
            resp = await client.get(ODS_BASE, params=params)
            resp.raise_for_status()
            records = resp.json().get("results", [])

            valid: list[Station] = []
            out_of_stock: list[float] = []  # distances des stations en rupture
            for rec in records:
                geom = rec.get("geom") or {}
                slat, slon = geom.get("lat"), geom.get("lon")
                if slat is None or slon is None:
                    continue
                d_air = haversine_km(lat, lon, slat, slon)
                indispo = rec.get("carburants_indisponibles") or []
                price = rec.get(fuel.price_col)
                if fuel.ods_name in indispo or price is None:
                    if fuel.ods_name in indispo:
                        out_of_stock.append(d_air)
                    continue
                pdate = _parse_dt(rec.get(fuel.maj_col))
                if pdate and now - pdate > max_age:
                    continue  # prix périmé
                name = ", ".join(x for x in (rec.get("adresse"), rec.get("ville")) if x)
                valid.append(
                    Station(
                        sid=rec.get("id", 0),
                        name=name or "Station",
                        ville=rec.get("ville") or "",
                        lat=slat,
                        lon=slon,
                        price=float(price),
                        price_date=pdate,
                        dist_air_km=d_air,
                    )
                )

            if len(valid) >= 5 or radius == SEARCH_RADII[-1]:
                valid.sort(key=lambda s: s.dist_air_km)
                candidates = valid[:MAX_CANDIDATES]
                worst = candidates[-1].dist_air_km if candidates else 0.0
                nearer_oos = sum(1 for d in out_of_stock if d < worst)
                return SearchResult(candidates, radius, nearer_oos)

    return SearchResult([], SEARCH_RADII[-1], 0)


# --- Statistiques nationales (cache 10 min) --------------------------------

_stats_cache: dict[str, tuple[float, dict]] = {}


async def national_stats(fuel: Fuel) -> dict | None:
    """min / max / médiane nationale pour un carburant (cache STATS_CACHE_TTL)."""
    cached = _stats_cache.get(fuel.code)
    if cached and time.monotonic() - cached[0] < STATS_CACHE_TTL:
        return cached[1]
    col = fuel.price_col
    params = {
        "select": (
            f"min({col}) as mn, max({col}) as mx, "
            f"percentile({col}, 50) as med, count({col}) as n"
        ),
        "where": f"{col} > 0.4",
        "limit": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(ODS_BASE, params=params)
            resp.raise_for_status()
            results = resp.json().get("results", [])
    except httpx.HTTPError:
        return cached[1] if cached else None
    if not results:
        return None
    stats = results[0]
    _stats_cache[fuel.code] = (time.monotonic(), stats)
    return stats


async def all_national_stats() -> dict[str, dict]:
    """Stats nationales pour tous les carburants (pour /stats)."""
    out: dict[str, dict] = {}
    for fuel in FUELS.values():
        stats = await national_stats(fuel)
        if stats:
            out[fuel.code] = stats
    return out
