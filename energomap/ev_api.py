"""Bornes de recharge électrique — dataset national IRVE (ODS, sans clé).

Source : `bornes-irve@reseaux-energies-rte` (consolidation IRVE data.gouv,
~227k points de charge). Le champ `coordonneesxy` est inversé (lon/lat) sur
une partie des enregistrements : on interroge donc les colonnes numériques
fiables `consolidated_latitude/longitude` via une bounding box, puis on
affine par Haversine. Agrégation par station (une ligne = un point de
charge) faite côté API avec group_by.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import httpx

from .config import MAX_CANDIDATES, SEARCH_RADII
from .fuel_api import haversine_km

IRVE_BASE = (
    "https://data.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
    "bornes-irve@reseaux-energies-rte/records"
)
POWER_WEIGHT = 0.3  # bonus puissance dans le scoring (0 = distance pure)


@dataclass
class EvStation:
    sid: str
    name: str
    operator: str
    lat: float
    lon: float
    pmax: float          # puissance max de la station (kW)
    npdc: int            # nombre de points de charge
    dist_air_km: float = 0.0
    dist_road_km: float | None = None
    duration_min: float | None = None
    score: float = field(default=0.0)


async def fetch_ev_candidates(lat: float, lon: float) -> tuple[list[EvStation], int]:
    """Stations de recharge autour de (lat, lon), rayon adaptatif 5→30 km.

    Retourne (candidates triées par distance, rayon utilisé).
    """
    async with httpx.AsyncClient(timeout=15) as client:
        for radius in SEARCH_RADII:
            dlat = radius / 111.0
            dlon = radius / (111.0 * max(math.cos(math.radians(lat)), 0.1))
            params = {
                "select": (
                    "max(puissance_nominale) as pmax, count(*) as npdc, "
                    "min(consolidated_latitude) as lat, "
                    "min(consolidated_longitude) as lon"
                ),
                "where": (
                    f"consolidated_latitude > {lat - dlat} and "
                    f"consolidated_latitude < {lat + dlat} and "
                    f"consolidated_longitude > {lon - dlon} and "
                    f"consolidated_longitude < {lon + dlon}"
                ),
                "group_by": "id_station_itinerance, nom_station, nom_operateur",
                "limit": "100",
            }
            resp = await client.get(IRVE_BASE, params=params)
            resp.raise_for_status()
            records = resp.json().get("results", [])

            stations: list[EvStation] = []
            for rec in records:
                slat, slon = rec.get("lat"), rec.get("lon")
                if slat is None or slon is None:
                    continue
                d_air = haversine_km(lat, lon, slat, slon)
                if d_air > radius:  # coin de la bbox hors rayon
                    continue
                stations.append(
                    EvStation(
                        sid=rec.get("id_station_itinerance") or "",
                        name=rec.get("nom_station") or "Borne de recharge",
                        operator=rec.get("nom_operateur") or "Opérateur inconnu",
                        lat=slat,
                        lon=slon,
                        pmax=float(rec.get("pmax") or 0),
                        npdc=int(rec.get("npdc") or 1),
                        dist_air_km=d_air,
                    )
                )

            stations = _dedup(stations)
            if len(stations) >= 5 or radius == SEARCH_RADII[-1]:
                stations.sort(key=lambda s: s.dist_air_km)
                return stations[:MAX_CANDIDATES], radius

    return [], SEARCH_RADII[-1]


def _dedup(stations: list[EvStation]) -> list[EvStation]:
    """Fusionne les doublons (certains opérateurs déclarent une « station »
    par prise) : même nom + position ~30 m → somme des prises, puissance max."""
    merged: dict[tuple, EvStation] = {}
    for s in stations:
        key = (s.name.lower(), round(s.lat, 4), round(s.lon, 4))
        if key in merged:
            kept = merged[key]
            kept.npdc += s.npdc
            kept.pmax = max(kept.pmax, s.pmax)
        else:
            merged[key] = s
    return list(merged.values())


def pick_top_ev(stations: list[EvStation], n: int = 5) -> list[EvStation]:
    """Top n : proximité d'abord, avec bonus pour les stations puissantes.

    score = dist_norm − POWER_WEIGHT × power_norm (croissant = meilleur).
    """
    if not stations:
        return []

    def dist(s: EvStation) -> float:
        return s.dist_road_km if s.dist_road_km is not None else s.dist_air_km

    dists = [dist(s) for s in stations]
    powers = [s.pmax for s in stations]
    d_min, d_max = min(dists), max(dists)
    p_min, p_max = min(powers), max(powers)
    for s in stations:
        d_norm = (dist(s) - d_min) / (d_max - d_min) if d_max > d_min else 0.0
        p_norm = (s.pmax - p_min) / (p_max - p_min) if p_max > p_min else 0.0
        s.score = d_norm - POWER_WEIGHT * p_norm
    top = sorted(stations, key=lambda s: s.score)[:n]
    top.sort(key=dist)
    return top
