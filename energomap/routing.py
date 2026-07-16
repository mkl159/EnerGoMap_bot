"""Distances routières (voiture) via OSRM Table — 1 requête par recherche."""
from __future__ import annotations

import httpx

from .config import DIST_WEIGHT, OSRM_TABLE, TOP_N
from .fuel_api import Station


async def add_road_distances(lat: float, lon: float, stations: list[Station]) -> bool:
    """Complète dist_road_km / duration_min. Retourne False si OSRM échoue
    (les distances à vol d'oiseau restent alors la référence)."""
    if not stations:
        return True
    coords = ";".join([f"{lon},{lat}"] + [f"{s.lon},{s.lat}" for s in stations])
    url = f"{OSRM_TABLE}{coords}"
    params = {"sources": "0", "annotations": "distance,duration"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != "Ok":
            return False
        distances = data["distances"][0][1:]
        durations = data["durations"][0][1:]
    except (httpx.HTTPError, KeyError, IndexError):
        return False
    for station, dist_m, dur_s in zip(stations, distances, durations):
        if dist_m is not None:
            station.dist_road_km = dist_m / 1000
        if dur_s is not None:
            station.duration_min = dur_s / 60
    return True


def pick_top(stations: list[Station], n: int = TOP_N) -> list[Station]:
    """Scoring pondéré prix/distance : score = prix_norm + α × dist_norm.

    Normalisation min-max sur les candidates ; distance voiture si dispo,
    sinon vol d'oiseau. Tri croissant, top n, puis réordonné par distance
    pour une numérotation naturelle sur la carte.
    """
    if not stations:
        return []

    def dist(s: Station) -> float:
        return s.dist_road_km if s.dist_road_km is not None else s.dist_air_km

    prices = [s.price for s in stations]
    dists = [dist(s) for s in stations]
    p_min, p_max = min(prices), max(prices)
    d_min, d_max = min(dists), max(dists)
    for s in stations:
        p_norm = (s.price - p_min) / (p_max - p_min) if p_max > p_min else 0.0
        d_norm = (dist(s) - d_min) / (d_max - d_min) if d_max > d_min else 0.0
        s.score = p_norm + DIST_WEIGHT * d_norm
    top = sorted(stations, key=lambda s: s.score)[:n]
    top.sort(key=dist)
    return top
