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


def nav_keyboard(station: Station) -> InlineKeyboardMarkup:
    """Choix de l'app de navigation pour une station (boutons URL directs)."""
    urls = nav_urls(station.lat, station.lon)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗺 Google Maps", url=urls["Google Maps"])],
            [InlineKeyboardButton(text="🍎 Apple Plans", url=urls["Apple Plans"])],
            [InlineKeyboardButton(text="🚗 Waze", url=urls["Waze"])],
            [InlineKeyboardButton(text="🔌 Tesla (bientôt)", callback_data="tesla")],
            [InlineKeyboardButton(text="← Retour à la liste", callback_data="back")],
        ]
    )
