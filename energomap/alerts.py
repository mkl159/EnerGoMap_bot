"""🔔 Worker d'alertes prix : vérifie toutes les 15 min si une station
suivie est passée sous le seuil, notifie l'utilisateur puis supprime
l'alerte (une alerte = une notification)."""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from . import db
from .config import FUELS
from .fuel_api import fetch_prices_by_ids
from .keyboards import alert_nav_keyboard

log = logging.getLogger(__name__)

CHECK_INTERVAL = 900  # 15 min — le flux officiel est rafraîchi ~10 min


async def check_alerts(bot: Bot) -> None:
    alerts = await db.all_alerts()
    if not alerts:
        return
    prices = await fetch_prices_by_ids(sorted({a["station_id"] for a in alerts}))
    for alert in alerts:
        rec = prices.get(alert["station_id"])
        fuel = FUELS.get(alert["fuel"])
        if not rec or not fuel:
            continue
        price = rec.get(fuel.price_col)
        if price is None or float(price) > alert["threshold"]:
            continue
        text = (
            f"🔔 <b>Alerte prix !</b>\n\n"
            f"⛽ <b>{fuel.short}</b> à <b>{float(price):.3f} €</b> "
            f"(votre seuil : {alert['threshold']:.3f} €)\n"
            f"📍 {html.escape(alert['station_name'][:60])}\n\n"
            f"🧭 Lancez l'itinéraire :"
        )
        try:
            await bot.send_message(
                alert["tg_id"], text,
                reply_markup=alert_nav_keyboard(alert["lat"], alert["lon"]),
            )
        except TelegramAPIError:
            log.warning("Alerte %s : envoi impossible (utilisateur parti ?)",
                        alert["id"])
        await db.delete_alert(alert["id"])
        log.info("Alerte %s déclenchée (%s ≤ %.3f €)",
                 alert["id"], fuel.short, alert["threshold"])


async def alert_watcher(bot: Bot) -> None:
    """Boucle infinie du worker (lancée au démarrage du bot)."""
    log.info("Worker d'alertes prix démarré (intervalle %d s)", CHECK_INTERVAL)
    while True:
        try:
            await check_alerts(bot)
        except Exception:  # noqa: BLE001 — le worker ne doit jamais mourir
            log.exception("Erreur du worker d'alertes")
        await asyncio.sleep(CHECK_INTERVAL)
