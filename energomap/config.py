"""Configuration centrale d'EnerGoMap_bot."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DB_PATH = os.getenv("DB_PATH", "energomap.sqlite3")

# API Opendatasoft du ministère de l'Économie (flux instantané v2)
ODS_BASE = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "prix-des-carburants-en-france-flux-instantane-v2/records"
)
# OSRM démo public (V1 ; auto-héberger en V2)
OSRM_TABLE = "https://router.project-osrm.org/table/v1/driving/"

# Tuiles CARTO Voyager (gratuites, attribution © OSM © CARTO)
TILE_URL = "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png"

# Rayons de recherche successifs (km) — élargis si < 5 stations trouvées
SEARCH_RADII = [5, 10, 20, 30]
MAX_CANDIDATES = 20          # candidates envoyées à OSRM (1 seule requête Matrix)
TOP_N = 5
STATS_CACHE_TTL = 600        # 10 min
PRICE_MAX_AGE_DAYS = 7       # prix plus vieux → ignorés
RATE_LIMIT_SECONDS = 3
DIST_WEIGHT = 0.5            # α du scoring : prix_norm + α * dist_norm


@dataclass(frozen=True)
class Fuel:
    code: str        # code interne / callback_data
    label: str       # libellé bouton
    short: str       # libellé court affichage
    price_col: str   # colonne prix dans le dataset ODS
    maj_col: str     # colonne date de mise à jour du prix
    ods_name: str    # nom dans carburants_indisponibles


FUELS: dict[str, Fuel] = {
    f.code: f
    for f in [
        Fuel("gazole", "⛽ Gazole", "Gazole", "gazole_prix", "gazole_maj", "Gazole"),
        Fuel("e10", "⛽ SP95-E10", "SP95-E10", "e10_prix", "e10_maj", "E10"),
        Fuel("sp95", "⛽ SP95", "SP95", "sp95_prix", "sp95_maj", "SP95"),
        Fuel("sp98", "⛽ SP98", "SP98", "sp98_prix", "sp98_maj", "SP98"),
        Fuel("e85", "⛽ E85", "E85", "e85_prix", "e85_maj", "E85"),
        Fuel("gplc", "⛽ GPLc", "GPLc", "gplc_prix", "gplc_maj", "GPLc"),
    ]
}
ELEC_CODE = "elec"  # ⚡ Électricité — mode annuaire prévu en V1.1
