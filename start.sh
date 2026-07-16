#!/usr/bin/env bash
# 🚀 EnerGoMap_bot — installation & lancement en une commande.
#
#   ./start.sh          installe ce qui manque (avec confirmation) puis lance
#   ./start.sh --check  lance uniquement le diagnostic (check.py)
#   ./start.sh --once   lance sans redémarrage automatique
set -euo pipefail
cd "$(dirname "$0")"

BLEU='\033[1;34m'; VERT='\033[1;32m'; ROUGE='\033[1;31m'; JAUNE='\033[1;33m'; FIN='\033[0m'
say()  { echo -e "${BLEU}▶${FIN} $*"; }
ok()   { echo -e "${VERT}✅${FIN} $*"; }
warn() { echo -e "${JAUNE}⚠️${FIN}  $*"; }
die()  { echo -e "${ROUGE}❌${FIN} $*"; exit 1; }

echo "⛽⚡ EnerGoMap_bot — démarrage"
echo "─────────────────────────────"

# 1. Python ───────────────────────────────────────────────────────────────
command -v python3 >/dev/null || die "python3 introuvable. Installez Python 3.10+ (sudo apt install python3 python3-venv)."
PYV=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "Python $PYV détecté — 3.10+ requis."
ok "Python $PYV"

# 2. Environnement virtuel ────────────────────────────────────────────────
if [ ! -d .venv ]; then
  say "Création de l'environnement virtuel (.venv)…"
  python3 -m venv .venv || die "Échec : installez python3-venv (sudo apt install python3-venv)."
fi
PY=.venv/bin/python
ok "Environnement virtuel prêt"

# 3. Dépendances ──────────────────────────────────────────────────────────
if ! $PY - << 'EOF' 2>/dev/null
import aiogram, httpx, staticmap, PIL, dotenv, aiosqlite
EOF
then
  warn "Des dépendances sont manquantes :"
  echo "   → $(tr '\n' ' ' < requirements.txt)"
  read -rp "📦 Les installer maintenant ? [O/n] " REP
  case "${REP:-O}" in
    [OoYy]*|"") say "Installation…"; $PY -m pip install -q --upgrade pip
                $PY -m pip install -q -r requirements.txt; ok "Dépendances installées" ;;
    *) die "Impossible de continuer sans les dépendances." ;;
  esac
else
  ok "Dépendances déjà installées"
fi

# 4. Configuration (.env) ─────────────────────────────────────────────────
if [ ! -f .env ]; then
  warn "Fichier .env absent."
  echo "   Créez un bot avec @BotFather sur Telegram (/newbot) pour obtenir un token."
  read -rp "🔑 Collez votre token Telegram : " TOKEN
  [ -n "$TOKEN" ] || die "Token vide."
  printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TOKEN" > .env
  chmod 600 .env
  ok "Fichier .env créé (jamais commité — protégé par .gitignore)"
else
  ok "Configuration .env trouvée"
fi

# 5. Mode diagnostic ──────────────────────────────────────────────────────
if [ "${1:-}" = "--check" ]; then
  exec $PY check.py
fi

# 6. Lancement ────────────────────────────────────────────────────────────
if [ "${1:-}" = "--once" ]; then
  say "Lancement du bot (Ctrl+C pour arrêter)…"
  exec $PY bot.py
fi

say "Lancement du bot avec redémarrage automatique (Ctrl+C pour arrêter)…"
trap 'echo; warn "Arrêt demandé."; exit 0' INT TERM
while true; do
  $PY bot.py && break
  warn "Le bot s'est arrêté anormalement — redémarrage dans 5 s…"
  sleep 5
done
