"""Handlers Telegram : onboarding, recherche, résultats, navigation."""
from __future__ import annotations

import html
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
)

from . import db
from .config import ELEC_CODE, FUELS, MAX_ALERTS_PER_USER, RATE_LIMIT_SECONDS, TOP_N
from .ev_api import EvStation, fetch_ev_candidates, pick_top_ev
from .fuel_api import Station, all_national_stats, fetch_candidates, national_stats
from .keyboards import (
    alert_threshold_keyboard,
    alerts_list_keyboard,
    fuel_keyboard,
    location_keyboard,
    nav_keyboard,
    results_keyboard,
)


class AlertForm(StatesGroup):
    """Saisie libre du seuil d'alerte prix."""
    amount = State()
from .mapgen import render_map
from .routing import add_road_distances, pick_top

log = logging.getLogger(__name__)
router = Router()

# Résultats en mémoire (jamais persistés — RGPD) : "chat:msg" → contexte
_RESULTS: OrderedDict[str, dict] = OrderedDict()
_RESULTS_MAX = 500

_last_search: dict[int, float] = {}  # anti-spam : tg_id → monotonic


def _store(chat_id: int, message_id: int, ctx: dict) -> None:
    key = f"{chat_id}:{message_id}"
    _RESULTS[key] = ctx
    while len(_RESULTS) > _RESULTS_MAX:
        _RESULTS.popitem(last=False)


async def _status(waiting: Message, text: str) -> None:
    """Met à jour le message d'attente sans jamais faire échouer le pipeline."""
    try:
        await waiting.edit_text(text)
    except TelegramBadRequest:
        pass


async def _safe_edit(message: Message, text: str, markup=None) -> None:
    """edit_text/edit_caption qui ignore « message is not modified »
    (double-clic sur le même bouton)."""
    try:
        if message.photo:
            await message.edit_caption(caption=text, reply_markup=markup)
        else:
            await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


def _age_str(dt: datetime | None) -> str:
    if not dt:
        return ""
    delta = datetime.now(timezone.utc) - dt
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"il y a {max(minutes, 1)} min"
    hours = minutes // 60
    if hours < 24:
        return f"il y a {hours} h"
    return f"il y a {hours // 24} j"


def _dist_str(s: Station) -> str:
    if s.dist_road_km is not None:
        txt = f"{s.dist_road_km:.1f} km 🚗"
        if s.duration_min is not None:
            txt += f" {round(s.duration_min)} min"
        return txt
    return f"{s.dist_air_km:.1f} km (vol d'oiseau)"


def _build_caption(fuel_code: str, stations: list[Station], radius: int,
                   nearer_oos: int, stats: dict | None) -> str:
    fuel = FUELS[fuel_code]
    digits = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    lines = [f"⛽ <b>{fuel.short}</b> — top {len(stations)} autour de vous"]
    if stats:
        lines.append(
            f"🇫🇷 National : min <b>{stats['mn']:.3f} €</b> · "
            f"médiane <b>{stats['med']:.3f} €</b> · max <b>{stats['mx']:.3f} €</b>"
        )
    lines.append("")
    for i, s in enumerate(stations):
        name = html.escape(s.name[:38])
        lines.append(
            f"{digits[i]} {name}\n"
            f"     <b>{s.price:.3f} €</b> — {_dist_str(s)} — {_age_str(s.price_date)}"
        )
    if radius > 5:
        lines.append(f"\n🔎 Rayon élargi à {radius} km.")
    if nearer_oos:
        plural = "s" if nearer_oos > 1 else ""
        lines.append(
            f"⚠️ {nearer_oos} station{plural} plus proche{plural} "
            f"actuellement en rupture de stock."
        )
    lines.append("\n👇 Touchez un numéro pour lancer la navigation.")
    caption = "\n".join(lines)
    return caption[:1024]


# --- Commandes ---------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    fuel = await db.get_fuel(message.from_user.id)
    if fuel:
        label = FUELS[fuel].label if fuel in FUELS else "⚡ Électricité"
        await message.answer(
            f"👋 Rebonjour ! Votre énergie par défaut : <b>{label}</b>.\n\n"
            "📍 Partagez votre position pour trouver les meilleures stations, "
            "ou /carburant pour changer d'énergie.",
            reply_markup=location_keyboard(),
        )
    else:
        await message.answer(
            "👋 Bienvenue sur <b>EnerGoMap</b> !\n\n"
            "Je trouve pour vous les stations les <b>moins chères</b> et les "
            "<b>plus proches</b> (distance en voiture 🚗), carte à l'appui.\n\n"
            "⚡ <b>Que cherchez-vous à comparer ?</b>",
            reply_markup=fuel_keyboard(),
        )


@router.message(Command("carburant"))
async def cmd_carburant(message: Message) -> None:
    await message.answer(
        "⚡ <b>Quelle énergie voulez-vous comparer ?</b>",
        reply_markup=fuel_keyboard(),
    )


@router.message(Command("position"))
async def cmd_position(message: Message) -> None:
    await message.answer(
        "📍 Partagez votre position avec le bouton ci-dessous :",
        reply_markup=location_keyboard(),
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    waiting = await message.answer("📊 Calcul des statistiques nationales…")
    stats = await all_national_stats()
    if not stats:
        await waiting.edit_text("😕 Statistiques indisponibles pour le moment.")
        return
    lines = ["📊 <b>Prix nationaux — instant T</b>\n"]
    lines.append("<pre>Carburant   min   médiane   max</pre>")
    rows = []
    for code, s in stats.items():
        fuel = FUELS[code]
        rows.append(
            f"{fuel.short:<9} {s['mn']:>5.3f}   {s['med']:>5.3f}  {s['mx']:>5.3f}"
        )
    lines[-1] = "<pre>" + "Carburant    min   médiane   max\n" + "\n".join(rows) + "</pre>"
    lines.append("Source : prix-carburants.gouv.fr (maj ~10 min)")
    await waiting.edit_text("\n".join(lines))


@router.message(Command("aide"))
async def cmd_aide(message: Message) -> None:
    await message.answer(
        "ℹ️ <b>EnerGoMap — aide</b>\n\n"
        "1. /carburant : choisissez votre énergie.\n"
        "2. /position : partagez votre position 📍.\n"
        "3. Je vous montre le <b>top 5</b> des stations (prix + distance "
        "voiture) sur une carte.\n"
        "4. Touchez un numéro pour ouvrir l'itinéraire dans Google Maps, "
        "Apple Plans ou Waze.\n"
        "5. 🔔 Sur la fiche d'une station, créez une <b>alerte prix</b> : je "
        "vous préviens quand elle passe sous votre seuil.\n\n"
        "/stats : prix nationaux de tous les carburants.\n"
        "/alertes : gérer vos alertes prix.\n\n"
        "🔒 Votre position n'est <b>jamais enregistrée</b>.\n"
        "Données : prix-carburants.gouv.fr · Cartes © OpenStreetMap/CARTO"
    )


# --- Choix du carburant -------------------------------------------------------

@router.callback_query(F.data.startswith("fuel:"))
async def cb_fuel(callback: CallbackQuery) -> None:
    code = callback.data.split(":", 1)[1]
    if code == ELEC_CODE:
        await db.set_fuel(callback.from_user.id, ELEC_CODE)
        await callback.answer("⚡ Électricité enregistrée ✅")
        await _safe_edit(
            callback.message,
            "✅ Énergie par défaut : <b>⚡ Électricité</b>.\n"
            "Je vous montrerai les bornes de recharge proches (puissance, "
            "nb de prises, opérateur).\n"
            "💶 <i>Les tarifs de recharge ne sont pas publiés en open data — "
            "vérifiez le prix dans l'app de l'opérateur.</i>",
        )
        await callback.message.answer(
            "📍 Partagez maintenant votre position :",
            reply_markup=location_keyboard(),
        )
        return
    if code not in FUELS:
        await callback.answer("Choix inconnu", show_alert=True)
        return
    await db.set_fuel(callback.from_user.id, code)
    await callback.answer(f"{FUELS[code].short} enregistré ✅")
    await _safe_edit(
        callback.message, f"✅ Énergie par défaut : <b>{FUELS[code].label}</b>."
    )
    await callback.message.answer(
        "📍 Partagez maintenant votre position :",
        reply_markup=location_keyboard(),
    )


# --- Réception de la position → recherche ------------------------------------

@router.message(F.location)
async def on_location(message: Message) -> None:
    uid = message.from_user.id
    now = time.monotonic()
    if now - _last_search.get(uid, 0) < RATE_LIMIT_SECONDS:
        await message.answer("⏳ Une seconde… recherche déjà en cours.")
        return
    _last_search[uid] = now

    fuel_code = await db.get_fuel(uid)
    if not fuel_code or (fuel_code not in FUELS and fuel_code != ELEC_CODE):
        await message.answer(
            "⚡ Choisissez d'abord votre énergie :", reply_markup=fuel_keyboard()
        )
        return

    lat, lon = message.location.latitude, message.location.longitude
    if fuel_code == ELEC_CODE:
        await _run_search_ev(message, uid, lat, lon)
    else:
        await _run_search(message, uid, fuel_code, lat, lon)


async def _run_search(message: Message, uid: int, fuel_code: str,
                      lat: float, lon: float) -> None:
    """Pipeline complet : recherche → routage → carte → message composite."""
    fuel = FUELS[fuel_code]
    # ⚠️ pas de ReplyKeyboardRemove ici : un message envoyé avec un
    # reply markup de ce type devient inéditable (limitation Telegram).
    waiting = await message.answer(
        "🔍 <b>Recherche des meilleures stations en cours…</b>"
    )
    try:
        result = await fetch_candidates(lat, lon, fuel)
        if not result.stations:
            await _status(
                waiting,
                f"😕 Aucune station {fuel.short} trouvée à moins de "
                f"{result.radius_km} km, ou toutes en rupture.",
            )
            return

        await _status(waiting, "🚗 <b>Calcul des distances en voiture…</b>")
        osrm_ok = await add_road_distances(lat, lon, result.stations)
        if not osrm_ok:
            log.warning("OSRM indisponible, repli vol d'oiseau")
        top = pick_top(result.stations, TOP_N)

        await _status(waiting, "🗺 <b>Génération de la carte…</b>")
        stats = await national_stats(fuel)
        try:
            png = render_map(lat, lon, top)
        except Exception:  # tuiles indisponibles → message texte seul
            log.exception("Échec génération carte")
            png = None

        caption = _build_caption(fuel_code, top, result.radius_km,
                                 result.nearer_out_of_stock, stats)
        keyboard = results_keyboard(len(top))
        try:
            await waiting.delete()
        except TelegramBadRequest:
            pass
        if png:
            sent = await message.answer_photo(
                BufferedInputFile(png, filename="energomap.png"),
                caption=caption,
                reply_markup=keyboard,
            )
        else:
            sent = await message.answer(caption, reply_markup=keyboard)

        _store(sent.chat.id, sent.message_id, {
            "kind": "fuel",
            "fuel": fuel_code,
            "stations": top,
            "caption": caption,
            "lat": lat,
            "lon": lon,
            "uid": uid,
        })
    except Exception:
        log.exception("Erreur pendant la recherche")
        await _status(
            waiting,
            "💥 Oups, une erreur est survenue. Réessayez dans un instant "
            "(/position).",
        )


def _build_caption_ev(stations: list[EvStation], radius: int) -> str:
    digits = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    lines = [f"⚡ <b>Bornes de recharge</b> — top {len(stations)} autour de vous", ""]
    for i, s in enumerate(stations):
        name = html.escape(s.name[:38])
        op = html.escape(s.operator[:24])
        lines.append(
            f"{digits[i]} {name}\n"
            f"     <b>{s.pmax:g} kW</b> · {s.npdc} prise{'s' if s.npdc > 1 else ''} "
            f"· {op} — {_dist_str(s)}"
        )
    if radius > 5:
        lines.append(f"\n🔎 Rayon élargi à {radius} km.")
    lines.append(
        "\n💶 <i>Tarifs selon opérateur (non publiés en open data).</i>\n"
        "👇 Touchez un numéro pour lancer la navigation."
    )
    return "\n".join(lines)[:1024]


async def _run_search_ev(message: Message, uid: int, lat: float, lon: float) -> None:
    """Pipeline électricité : bornes IRVE → routage → carte → composite."""
    waiting = await message.answer(
        "🔍 <b>Recherche des bornes de recharge en cours…</b>"
    )
    try:
        stations, radius = await fetch_ev_candidates(lat, lon)
        if not stations:
            await _status(
                waiting,
                f"😕 Aucune borne de recharge trouvée à moins de {radius} km.\n"
                "ℹ️ Le service couvre la France (données IRVE data.gouv.fr).",
            )
            return

        await _status(waiting, "🚗 <b>Calcul des distances en voiture…</b>")
        osrm_ok = await add_road_distances(lat, lon, stations)
        if not osrm_ok:
            log.warning("OSRM indisponible, repli vol d'oiseau")
        top = pick_top_ev(stations, TOP_N)

        await _status(waiting, "🗺 <b>Génération de la carte…</b>")
        try:
            png = render_map(lat, lon, top)
        except Exception:
            log.exception("Échec génération carte")
            png = None

        caption = _build_caption_ev(top, radius)
        keyboard = results_keyboard(len(top))
        try:
            await waiting.delete()
        except TelegramBadRequest:
            pass
        if png:
            sent = await message.answer_photo(
                BufferedInputFile(png, filename="energomap.png"),
                caption=caption,
                reply_markup=keyboard,
            )
        else:
            sent = await message.answer(caption, reply_markup=keyboard)

        _store(sent.chat.id, sent.message_id, {
            "kind": "ev",
            "stations": top,
            "caption": caption,
            "lat": lat,
            "lon": lon,
            "uid": uid,
        })
    except Exception:
        log.exception("Erreur pendant la recherche de bornes")
        await _status(
            waiting,
            "💥 Oups, une erreur est survenue. Réessayez dans un instant "
            "(/position).",
        )


# --- Sélection d'une station → choix de l'app de navigation -------------------

@router.callback_query(F.data.startswith("st:"))
async def cb_station(callback: CallbackQuery) -> None:
    key = f"{callback.message.chat.id}:{callback.message.message_id}"
    ctx = _RESULTS.get(key)
    if not ctx:
        await callback.answer(
            "Résultats expirés — relancez une recherche via /position.",
            show_alert=True,
        )
        return
    idx = int(callback.data.split(":", 1)[1])
    stations = ctx["stations"]
    if idx >= len(stations):
        await callback.answer("Station inconnue", show_alert=True)
        return
    s = stations[idx]
    await callback.answer()
    if ctx.get("kind") == "ev":
        detail = (
            f"{s.pmax:g} kW · {s.npdc} prise{'s' if s.npdc > 1 else ''} · "
            f"{html.escape(s.operator[:30])} — {_dist_str(s)}"
        )
        alert_idx = None  # pas de prix élec en open data → pas d'alerte
    else:
        detail = f"{s.price:.3f} € — {_dist_str(s)}"
        alert_idx = idx
    caption = (
        f"🧭 <b>[{idx + 1}] {html.escape(s.name[:60])}</b>\n"
        f"{detail}\n\n"
        "<b>Où voulez-vous envoyer cet itinéraire ?</b>"
    )
    await _safe_edit(callback.message, caption, nav_keyboard(s, alert_idx))


@router.callback_query(F.data == "back")
async def cb_back(callback: CallbackQuery) -> None:
    key = f"{callback.message.chat.id}:{callback.message.message_id}"
    ctx = _RESULTS.get(key)
    if not ctx:
        await callback.answer("Résultats expirés — /position pour relancer.",
                              show_alert=True)
        return
    await callback.answer()
    await _safe_edit(
        callback.message, ctx["caption"], results_keyboard(len(ctx["stations"]))
    )


@router.callback_query(F.data == "redo")
async def cb_redo(callback: CallbackQuery) -> None:
    key = f"{callback.message.chat.id}:{callback.message.message_id}"
    ctx = _RESULTS.get(key)
    if not ctx:
        await callback.answer("Résultats expirés — /position pour relancer.",
                              show_alert=True)
        return
    fuel_code = await db.get_fuel(callback.from_user.id)
    if not fuel_code or (fuel_code not in FUELS and fuel_code != ELEC_CODE):
        await callback.answer("Choisissez une énergie d'abord (/carburant).",
                              show_alert=True)
        return
    await callback.answer("Recherche relancée 🔄")
    if fuel_code == ELEC_CODE:
        await _run_search_ev(callback.message, callback.from_user.id,
                             ctx["lat"], ctx["lon"])
    else:
        await _run_search(callback.message, callback.from_user.id, fuel_code,
                          ctx["lat"], ctx["lon"])


# --- Alertes prix (🔔) ---------------------------------------------------------

def _fuel_station_from_ctx(callback: CallbackQuery, idx: int):
    """Récupère (ctx, station) d'un message résultats carburant, ou None."""
    key = f"{callback.message.chat.id}:{callback.message.message_id}"
    ctx = _RESULTS.get(key)
    if not ctx or ctx.get("kind") != "fuel" or idx >= len(ctx["stations"]):
        return None, None
    return ctx, ctx["stations"][idx]


@router.callback_query(F.data.startswith("al:"))
async def cb_alert(callback: CallbackQuery) -> None:
    idx = int(callback.data.split(":", 1)[1])
    ctx, s = _fuel_station_from_ctx(callback, idx)
    if not s:
        await callback.answer("Résultats expirés — /position pour relancer.",
                              show_alert=True)
        return
    if await db.count_alerts(callback.from_user.id) >= MAX_ALERTS_PER_USER:
        await callback.answer(
            f"Limite de {MAX_ALERTS_PER_USER} alertes atteinte — "
            "supprimez-en via /alertes.", show_alert=True)
        return
    await callback.answer()
    fuel = FUELS[ctx["fuel"]]
    await _safe_edit(
        callback.message,
        f"🔔 <b>Alerte prix — {html.escape(s.name[:50])}</b>\n"
        f"{fuel.short} actuellement à <b>{s.price:.3f} €</b>.\n\n"
        "<b>Me prévenir si le prix passe sous :</b>",
        alert_threshold_keyboard(idx, s.price),
    )


async def _create_alert(uid: int, ctx: dict, s: Station, threshold: float) -> str:
    await db.add_alert(uid, s.sid, s.name, s.lat, s.lon, ctx["fuel"], threshold)
    fuel = FUELS[ctx["fuel"]]
    return (
        f"🔔 <b>Alerte créée !</b>\n"
        f"Je vous préviens si <b>{fuel.short}</b> passe sous "
        f"<b>{threshold:.3f} €</b> à :\n📍 {html.escape(s.name[:60])}\n\n"
        f"<i>Vérification toutes les 15 min · gérez vos alertes avec /alertes</i>"
    )


@router.callback_query(F.data.startswith("alset:"))
async def cb_alert_set(callback: CallbackQuery) -> None:
    _, idx_str, thr_str = callback.data.split(":", 2)
    idx = int(idx_str)
    ctx, s = _fuel_station_from_ctx(callback, idx)
    if not s:
        await callback.answer("Résultats expirés — /position pour relancer.",
                              show_alert=True)
        return
    text = await _create_alert(callback.from_user.id, ctx, s, float(thr_str))
    await callback.answer("Alerte créée ✅")
    await callback.message.answer(text)
    # retour à la fiche station
    await _safe_edit(callback.message, ctx["caption"],
                     results_keyboard(len(ctx["stations"])))


@router.callback_query(F.data.startswith("alcustom:"))
async def cb_alert_custom(callback: CallbackQuery, state: FSMContext) -> None:
    idx = int(callback.data.split(":", 1)[1])
    ctx, s = _fuel_station_from_ctx(callback, idx)
    if not s:
        await callback.answer("Résultats expirés — /position pour relancer.",
                              show_alert=True)
        return
    await callback.answer()
    await state.set_state(AlertForm.amount)
    await state.update_data(sid=s.sid, name=s.name, lat=s.lat, lon=s.lon,
                            fuel=ctx["fuel"], price=s.price)
    await callback.message.answer(
        f"✏️ Envoyez le prix seuil en euros (ex : <b>{s.price - 0.03:.2f}</b>).\n"
        "Tapez /annuler pour abandonner."
    )


@router.message(Command("annuler"), StateFilter(AlertForm.amount))
async def cmd_annuler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Création d'alerte annulée.")


@router.message(F.text, StateFilter(AlertForm.amount))
async def msg_alert_amount(message: Message, state: FSMContext) -> None:
    raw = message.text.replace(",", ".").replace("€", "").strip()
    try:
        threshold = float(raw)
    except ValueError:
        await message.answer("🤔 Je n'ai pas compris. Envoyez un prix comme "
                             "<b>1.65</b> (ou /annuler).")
        return
    if not 0.3 <= threshold <= 3.5:
        await message.answer("⚠️ Prix hors limites (0.30 – 3.50 €). Réessayez "
                             "(ou /annuler).")
        return
    data = await state.get_data()
    await state.clear()
    fake_ctx = {"fuel": data["fuel"]}
    s = Station(sid=data["sid"], name=data["name"], ville="", lat=data["lat"],
                lon=data["lon"], price=data["price"], price_date=None)
    text = await _create_alert(message.from_user.id, fake_ctx, s, threshold)
    await message.answer(text)


@router.message(Command("alertes"))
async def cmd_alertes(message: Message) -> None:
    alerts = await db.list_alerts(message.from_user.id)
    if not alerts:
        await message.answer(
            "🔕 Aucune alerte active.\n\nPour en créer une : faites une "
            "recherche (📍 /position), touchez un numéro puis "
            "« 🔔 M'alerter si le prix baisse »."
        )
        return
    lines = ["🔔 <b>Vos alertes actives</b> (touchez pour supprimer) :\n"]
    for i, a in enumerate(alerts, start=1):
        fuel = FUELS.get(a["fuel"])
        lines.append(
            f"{i}. {html.escape(a['station_name'][:40])}\n"
            f"     {fuel.short if fuel else a['fuel']} ≤ <b>{a['threshold']:.3f} €</b>"
        )
    await message.answer("\n".join(lines), reply_markup=alerts_list_keyboard(alerts))


@router.callback_query(F.data.startswith("aldel:"))
async def cb_alert_delete(callback: CallbackQuery) -> None:
    alert_id = int(callback.data.split(":", 1)[1])
    await db.delete_alert(alert_id, callback.from_user.id)
    alerts = await db.list_alerts(callback.from_user.id)
    await callback.answer("Alerte supprimée 🗑")
    if alerts:
        lines = ["🔔 <b>Vos alertes actives</b> (touchez pour supprimer) :\n"]
        for i, a in enumerate(alerts, start=1):
            fuel = FUELS.get(a["fuel"])
            lines.append(
                f"{i}. {html.escape(a['station_name'][:40])}\n"
                f"     {fuel.short if fuel else a['fuel']} ≤ <b>{a['threshold']:.3f} €</b>"
            )
        await _safe_edit(callback.message, "\n".join(lines),
                         alerts_list_keyboard(alerts))
    else:
        await _safe_edit(callback.message, "🔕 Aucune alerte active.")


@router.callback_query(F.data == "tesla")
async def cb_tesla(callback: CallbackQuery) -> None:
    await callback.answer(
        "🔌 L'envoi direct vers votre Tesla arrive en V2 (connexion au compte "
        "Tesla requise). En attendant, utilisez Google Maps / Waze.",
        show_alert=True,
    )


# --- Fallback : tout autre message --------------------------------------------

@router.message(F.text, StateFilter(None))
async def fallback(message: Message) -> None:
    fuel = await db.get_fuel(message.from_user.id)
    if not fuel:
        await cmd_start(message)
    else:
        await message.answer(
            "🤖 Utilisez les boutons ou les commandes :\n"
            "📍 /position — chercher autour de vous\n"
            "⛽ /carburant — changer d'énergie\n"
            "📊 /stats — prix nationaux\n"
            "🔔 /alertes — mes alertes prix\n"
            "ℹ️ /aide — aide",
        )
