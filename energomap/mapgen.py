"""Génération de la carte statique annotée (tuiles CARTO, marqueurs 1..5)."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont
from staticmap import CircleMarker, StaticMap
from staticmap.staticmap import _lat_to_y, _lon_to_x

from .config import TILE_URL
from .fuel_api import Station

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]

MARKER_R = 14  # rayon du badge numéroté (px)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_map(user_lat: float, user_lon: float, stations: list[Station]) -> bytes:
    """PNG 700×500 : position utilisateur (point bleu) + badges rouges 1..n."""
    m = StaticMap(700, 500, url_template=TILE_URL, padding_x=60, padding_y=60)

    # Marqueurs "fantômes" : servent uniquement au calcul de l'emprise.
    m.add_marker(CircleMarker((user_lon, user_lat), "#1a73e8", 0))
    for s in stations:
        m.add_marker(CircleMarker((s.lon, s.lat), "#d93025", 0))

    image = m.render()
    draw = ImageDraw.Draw(image)
    font = _font(18)

    def to_px(lat: float, lon: float) -> tuple[float, float]:
        return (
            m._x_to_px(_lon_to_x(lon, m.zoom)),
            m._y_to_px(_lat_to_y(lat, m.zoom)),
        )

    # Position utilisateur : point bleu cerclé de blanc
    ux, uy = to_px(user_lat, user_lon)
    draw.ellipse((ux - 10, uy - 10, ux + 10, uy + 10), fill="#ffffff")
    draw.ellipse((ux - 7, uy - 7, ux + 7, uy + 7), fill="#1a73e8")

    # Badges numérotés
    for i, s in enumerate(stations, start=1):
        x, y = to_px(s.lat, s.lon)
        r = MARKER_R
        draw.ellipse((x - r - 2, y - r - 2, x + r + 2, y + r + 2), fill="#ffffff")
        draw.ellipse((x - r, y - r, x + r, y + r), fill="#d93025")
        draw.text((x, y - 1), str(i), font=font, fill="#ffffff", anchor="mm")

    # Attribution (obligation OSM/CARTO)
    attribution = "© OpenStreetMap contributors © CARTO"
    small = _font(11)
    tw = draw.textlength(attribution, font=small)
    draw.rectangle((image.width - tw - 8, image.height - 16, image.width, image.height),
                   fill=(255, 255, 255, 200))
    draw.text((image.width - tw - 4, image.height - 14), attribution,
              font=small, fill="#555555")

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
