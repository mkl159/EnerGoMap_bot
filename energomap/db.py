"""Persistance SQLite : profil utilisateur (carburant préféré uniquement).

La position GPS n'est JAMAIS stockée (RGPD).
"""
import aiosqlite

from .config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id      INTEGER PRIMARY KEY,
    fuel       TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id        INTEGER NOT NULL,
    station_id   INTEGER NOT NULL,
    station_name TEXT NOT NULL,
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    fuel         TEXT NOT NULL,
    threshold    REAL NOT NULL,
    created_at   TEXT DEFAULT (datetime('now'))
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


async def get_fuel(tg_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT fuel FROM users WHERE tg_id = ?", (tg_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_fuel(tg_id: int, fuel: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (tg_id, fuel) VALUES (?, ?)
               ON CONFLICT(tg_id) DO UPDATE SET fuel = excluded.fuel,
                                                updated_at = datetime('now')""",
            (tg_id, fuel),
        )
        await db.commit()


# --- Alertes prix ------------------------------------------------------------

async def add_alert(tg_id: int, station_id: int, station_name: str,
                    lat: float, lon: float, fuel: str, threshold: float) -> int:
    """Crée une alerte. Retourne le nombre d'alertes actives de l'utilisateur."""
    async with aiosqlite.connect(DB_PATH) as db:
        # une seule alerte par (utilisateur, station, carburant) : on remplace
        await db.execute(
            "DELETE FROM alerts WHERE tg_id = ? AND station_id = ? AND fuel = ?",
            (tg_id, station_id, fuel),
        )
        await db.execute(
            """INSERT INTO alerts (tg_id, station_id, station_name, lat, lon,
                                   fuel, threshold)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tg_id, station_id, station_name, lat, lon, fuel, threshold),
        )
        await db.commit()
        async with db.execute(
            "SELECT COUNT(*) FROM alerts WHERE tg_id = ?", (tg_id,)
        ) as cur:
            return (await cur.fetchone())[0]


async def count_alerts(tg_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM alerts WHERE tg_id = ?", (tg_id,)
        ) as cur:
            return (await cur.fetchone())[0]


async def list_alerts(tg_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM alerts WHERE tg_id = ? ORDER BY created_at", (tg_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def all_alerts() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM alerts") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def delete_alert(alert_id: int, tg_id: int | None = None) -> None:
    """Supprime une alerte (si tg_id fourni, vérifie qu'elle lui appartient)."""
    async with aiosqlite.connect(DB_PATH) as db:
        if tg_id is None:
            await db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        else:
            await db.execute("DELETE FROM alerts WHERE id = ? AND tg_id = ?",
                             (alert_id, tg_id))
        await db.commit()
