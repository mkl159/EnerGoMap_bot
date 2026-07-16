#!/usr/bin/env python3
"""🩺 Diagnostic complet d'EnerGoMap_bot.

Vérifie : dépendances, configuration, APIs externes (Telegram, carburants,
bornes IRVE, routage OSRM), génération de carte et base de données.

Usage : python check.py
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys

OK, KO, WARN = "✅", "❌", "⚠️ "
_failures = 0


def report(ok: bool, label: str, detail: str = "") -> bool:
    global _failures
    print(f"  {OK if ok else KO} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        _failures += 1
    return ok


def check_python() -> None:
    print("\n🐍 Python")
    v = sys.version_info
    report(v >= (3, 10), f"Python {v.major}.{v.minor}.{v.micro}",
           "3.10+ requis" if v < (3, 10) else "")


def check_deps() -> bool:
    print("\n📦 Dépendances")
    deps = ["aiogram", "httpx", "staticmap", "PIL", "dotenv", "aiosqlite"]
    all_ok = True
    for mod in deps:
        try:
            importlib.import_module(mod)
            report(True, mod)
        except ImportError:
            report(False, mod, "manquant → ./start.sh l'installera")
            all_ok = False
    return all_ok


def check_env() -> bool:
    print("\n🔑 Configuration")
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return report(False, "TELEGRAM_BOT_TOKEN",
                      "absent — copiez .env.example vers .env et remplissez-le")
    looks_valid = ":" in token and token.split(":")[0].isdigit()
    return report(looks_valid, "TELEGRAM_BOT_TOKEN",
                  "présent" if looks_valid else "format inattendu")


async def check_apis() -> None:
    import httpx

    from energomap.config import ODS_BASE, OSRM_TABLE
    from energomap.ev_api import IRVE_BASE

    print("\n🌐 APIs externes")
    async with httpx.AsyncClient(timeout=15) as client:
        # Telegram
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if token:
            try:
                r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
                data = r.json()
                report(data.get("ok", False), "Telegram getMe",
                       f"@{data['result']['username']}" if data.get("ok")
                       else data.get("description", ""))
            except httpx.HTTPError as e:
                report(False, "Telegram getMe", str(e))

        # Carburants (ODS)
        try:
            r = await client.get(ODS_BASE, params={
                "where": "distance(geom, geom'POINT(2.3522 48.8566)', 5km)",
                "limit": "1",
            })
            n = r.json().get("total_count", 0)
            report(r.status_code == 200 and n > 0,
                   "API carburants (data.economie.gouv.fr)", f"{n} stations à Paris 5 km")
        except httpx.HTTPError as e:
            report(False, "API carburants", str(e))

        # Bornes IRVE
        try:
            r = await client.get(IRVE_BASE, params={"limit": "1"})
            n = r.json().get("total_count", 0)
            report(r.status_code == 200 and n > 0,
                   "API bornes IRVE (opendatasoft)", f"{n} points de charge")
        except httpx.HTTPError as e:
            report(False, "API bornes IRVE", str(e))

        # OSRM
        try:
            r = await client.get(
                f"{OSRM_TABLE}2.3522,48.8566;2.36,48.86",
                params={"sources": "0", "annotations": "distance"},
            )
            report(r.json().get("code") == "Ok", "Routage OSRM (distances voiture)")
        except httpx.HTTPError as e:
            report(False, "Routage OSRM", str(e))


def check_mapgen() -> None:
    print("\n🗺  Génération de carte")
    try:
        from energomap.fuel_api import Station
        from energomap.mapgen import render_map
        png = render_map(48.8566, 2.3522, [
            Station(sid=1, name="Test", ville="Paris", lat=48.85, lon=2.34,
                    price=1.85, price_date=None),
        ])
        report(len(png) > 10_000, "Rendu PNG", f"{len(png) // 1024} Ko")
    except Exception as e:  # noqa: BLE001 — diagnostic
        report(False, "Rendu PNG", f"{type(e).__name__}: {e}")


async def check_db() -> None:
    print("\n💾 Base de données")
    try:
        from energomap import db
        await db.init_db()
        report(True, "SQLite initialisée", db.DB_PATH if hasattr(db, "DB_PATH") else "")
    except Exception as e:  # noqa: BLE001 — diagnostic
        report(False, "SQLite", str(e))


async def main() -> int:
    print("🩺 EnerGoMap_bot — diagnostic")
    print("=" * 40)
    check_python()
    if not check_deps():
        print(f"\n{KO} Dépendances manquantes : lancez ./start.sh")
        return 1
    env_ok = check_env()
    await check_apis() if env_ok else None
    check_mapgen()
    await check_db()
    print("\n" + "=" * 40)
    if _failures:
        print(f"{KO} {_failures} problème(s) détecté(s).")
        return 1
    print(f"{OK} Tout est opérationnel ! Lancez le bot : ./start.sh")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
