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
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_SCHEMA)
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
