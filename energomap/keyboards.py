"""Claviers Telegram (inline + reply) et URLs de navigation."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .config import ELEC_CODE, FUELS
from .fuel_api import Station


def fuel_keyboard() -> InlineKeyboardMarkup:
    """Choix du carburant — 2 boutons par ligne + électricité."""
    rows, row = [], []
    for fuel in FUELS.values():
        row.append(InlineKeyboardButton(text=fuel.label, callback_data=f"fuel:{fuel.code}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⚡ Électricité", callback_data=f"fuel:{ELEC_CODE}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def location_keyboard() -> ReplyKeyboardMarkup:
    """Bouton natif de partage de position."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Partager ma position", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Appuyez sur le bouton pour partager votre position",
    )


def results_keyboard(n: int) -> InlineKeyboardMarkup:
    """Boutons 1..n sous le message de résultats + relance."""
    digits = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    row = [
        InlineKeyboardButton(text=digits[i], callback_data=f"st:{i}")
        for i in range(n)
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row,
            [InlineKeyboardButton(text="🔄 Relancer ici", callback_data="redo")],
        ]
    )


def nav_urls(lat: float, lon: float) -> dict[str, str]:
    """Deep links d'itinéraire — ouvrables dans l'app de son choix."""
    return {
        "Google Maps": f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}",
        "Apple Plans": f"https://maps.apple.com/?daddr={lat},{lon}&dirflg=d",
        "Waze": f"https://waze.com/ul?ll={lat},{lon}&navigate=yes",
    }


def nav_keyboard(station: Station, alert_idx: int | None = None) -> InlineKeyboardMarkup:
    """Choix de l'app de navigation pour une station (boutons URL directs).

    `alert_idx` (index de la station dans les résultats) affiche en plus le
    bouton 🔔 d'alerte prix — carburants uniquement.
    """
    urls = nav_urls(station.lat, station.lon)
    rows = [
        [InlineKeyboardButton(text="🗺 Google Maps", url=urls["Google Maps"])],
        [InlineKeyboardButton(text="🍎 Apple Plans", url=urls["Apple Plans"])],
        [InlineKeyboardButton(text="🚗 Waze", url=urls["Waze"])],
        [InlineKeyboardButton(text="🔌 Tesla (bientôt)", callback_data="tesla")],
    ]
    if alert_idx is not None:
        rows.append([InlineKeyboardButton(
            text="🔔 M'alerter si le prix baisse", callback_data=f"al:{alert_idx}"
        )])
    rows.append([InlineKeyboardButton(text="← Retour à la liste", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def alert_threshold_keyboard(idx: int, price: float) -> InlineKeyboardMarkup:
    """Choix du seuil d'alerte à partir du prix actuel."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"≤ {price - delta:.3f} € (−{int(delta * 100)} ct)",
                callback_data=f"alset:{idx}:{price - delta:.3f}",
            )
        ]
        for delta in (0.02, 0.05, 0.10)
        if price - delta > 0.3
    ]
    rows.append([InlineKeyboardButton(text="✏️ Autre montant",
                                      callback_data=f"alcustom:{idx}")])
    rows.append([InlineKeyboardButton(text="← Retour", callback_data=f"st:{idx}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def alert_nav_keyboard(lat: float, lon: float) -> InlineKeyboardMarkup:
    """Boutons d'itinéraire d'une notification d'alerte."""
    urls = nav_urls(lat, lon)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗺 Google Maps", url=urls["Google Maps"])],
            [InlineKeyboardButton(text="🍎 Apple Plans", url=urls["Apple Plans"])],
            [InlineKeyboardButton(text="🚗 Waze", url=urls["Waze"])],
        ]
    )


def alerts_list_keyboard(alerts: list[dict]) -> InlineKeyboardMarkup:
    """Liste des alertes actives avec bouton de suppression."""
    rows = [
        [InlineKeyboardButton(
            text=f"🗑 {i}. {a['station_name'][:28]} ≤ {a['threshold']:.3f} €",
            callback_data=f"aldel:{a['id']}",
        )]
        for i, a in enumerate(alerts, start=1)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
