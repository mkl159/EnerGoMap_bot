# 📋 Cahier des charges révisé — EnerGoMap_bot

> Version annotée du cahier des charges initial (2026-07-14), avec réflexion
> critique, corrections, ajouts et sources de données étendues.
> Bot cible : [@EnerGoMap_bot](https://t.me/EnerGoMap_bot)

---

## 0. Réflexion critique sur la demande initiale

Le cahier des charges initial est solide et bien pensé (UX par boutons,
distance routière, carte annotée, message composite unique). Points corrigés
ou nuancés :

| # | Point initial | Correction / nuance |
|---|---|---|
| 1 | **Token dans le document** | 🔴 Le token a circulé en clair → à **régénérer via BotFather (`/revoke`)** avant la prod. Stocké ici dans `.env` (gitignoré), jamais en dur dans le code. |
| 2 | **Intégration Tesla en V1** | L'API Tesla ("Fleet API") exige un compte développeur payant, une app enregistrée, un flux OAuth complet et une clé virtuelle installée sur le véhicule. Coût/complexité disproportionnés → **reporter en V2**. En V1, un bouton "Tesla" peut afficher un message "bientôt disponible" ou être masqué. |
| 3 | **PostgreSQL ou Redis dès le départ** | Surdimensionné pour un MVP. **SQLite suffit** (profils utilisateurs + cache prix). Migration Postgres/Redis triviale plus tard si le trafic le justifie. |
| 4 | **OSRM auto-hébergé** | Le graphe routier France demande ~8-16 Go de RAM au pré-traitement. Alternatives V1 : (a) serveur OSRM public `router.project-osrm.org` (démo, OK pour MVP faible trafic), (b) **OpenRouteService** (clé gratuite, 2000 req/j, endpoint Matrix), (c) auto-hébergement OSRM en V2. **Optimisation clé** : pré-filtrer ~20 stations candidates par Haversine, puis une **seule requête Matrix** (1 origine × 20 destinations) pour les distances voiture. |
| 5 | **Mapbox/Google Static Maps** | Les deux exigent clé API + carte bancaire. Alternative gratuite et sans clé : **générer la carte côté serveur** avec la lib Python `py-staticmaps`/`staticmap` sur tuiles OSM (attribution obligatoire), ou l'API **Geoapify Static Maps** (tier gratuit 3000 req/j, marqueurs numérotés natifs). Recommandation V1 : génération locale (zéro dépendance de facturation). |
| 6 | **Médiane nationale électricité** | ⚠️ Il n'existe **pas de flux temps réel des tarifs de recharge** publics : chaque opérateur (Ionity, Tesla, Electra…) a sa grille, souvent absente de l'open data. En V1, pour l'électricité : afficher les bornes proches (puissance, connecteurs, disponibilité si dispo) **sans prétendre à un comparatif de prix fiable**. Le header stats ne s'applique qu'aux carburants. |
| 7 | **Parse du XML toutes les 10-15 min** | Le flux instantané officiel n'est mis à jour que ~toutes les 10 min ; inutile de tirer plus vite. Mieux : utiliser l'**API JSON d'Opendatasoft** (voir §5.1) qui permet des requêtes géo directes sans télécharger tout le XML — le "worker" devient optionnel en V1. |
| 8 | **Apple Plans pour tous** | Le lien `maps.apple.com` s'ouvre aussi sur Android (redirigé vers Google Maps) donc pas bloquant, mais ajouter **Waze** (`https://waze.com/ul?ll=lat,lng&navigate=yes`) — très utilisé en France. |
| 9 | **RGPD / position** | La position GPS est une donnée personnelle sensible : la traiter **en mémoire uniquement**, ne jamais la persister (ou alors arrondie à ~1 km avec consentement). À mentionner dans la description du bot. |
| 10 | **Pondération distance/prix non définie** | Proposition concrète : `score = prix_normalisé + α × distance_normalisée` avec `α = 0,5` par défaut ; normalisation min-max sur les ~20 candidates. Trier par score croissant, garder 5. Simple, explicable, ajustable. |

**Ajouts proposés** (absents du cahier initial) :

- **Commande `/aide`** (help) et gestion des messages non compris.
- **Rayon de recherche adaptatif** : partir de 5 km, élargir automatiquement
  (10, 20, 30 km) si < 5 stations valides trouvées, et l'indiquer dans le
  message ("rayon élargi à 20 km").
- **Horodatage des prix** dans la liste ("prix relevé il y a 2 h") — la
  fraîcheur est un argument de confiance.
- **Bouton "🔄 Relancer ici"** sous les résultats pour refaire la recherche
  au même endroit avec un autre carburant.
- **Anti-spam / rate limiting** par utilisateur (ex. 1 recherche / 5 s).
- **Healthcheck & logs** : endpoint ou commande admin `/ping`, logs structurés.

---

## 1. Vision et principes UX *(inchangé)*

- **Zéro friction** : boutons inline + partage de position natif, pas de saisie texte.
- **Temps réel** : données fraîches, messages d'attente dynamiques.
- **Visuel premium** : carte statique annotée, message composite unique.

## 2. Parcours utilisateur

```
/start (ID inconnu)
   └─► Bienvenue + "Que cherchez-vous à comparer ?"
        [⚡ Électricité] [⛽ SP95-E10] [⛽ SP98] [⛽ Gazole] [⛽ E85] [⛽ GPLc]
   └─► Choix persisté ─► Demande de position (Reply Keyboard request_location)
   └─► Position reçue ─► "🔍 Recherche en cours…" (message édité)
   └─► Message composite : carte (photo) + stats nationales + top 5 + boutons [1..5]
   └─► Clic [n] ─► editMessage : "Où envoyer l'itinéraire ?"
                    [Google Maps] [Apple Plans] [Waze] [Tesla (V2)] [← Retour]
```

## 3. Fonctionnalités détaillées

### 3.1 Onboarding et profilage
- Machine à états (FSM aiogram) : `NEW → CHOOSING_FUEL → READY`.
- Carburants proposés = ceux du flux officiel : **Gazole, SP95, SP95-E10,
  SP98, E85, GPLc** + ⚡ Électricité (mode dégradé, cf. §0.6).
- Persistance du choix en **SQLite** (`users(id, fuel, created_at, updated_at)`).

### 3.2 Localisation
- Reply Keyboard avec `request_location: true`, retirée après réception
  (`ReplyKeyboardRemove`).
- La position n'est **pas stockée** (RGPD, cf. §0.9).
- Feedback immédiat : message "🔍 Recherche des meilleures stations en cours…"
  puis **remplacé** par le résultat (editMessage / delete+send photo).

### 3.3 Recherche et affichage
1. **Header — stats nationales** (carburants uniquement) : min, max, médiane,
   calculées sur le dataset national et **mises en cache 10 min**.
2. **Filtrage** :
   - exclure stations fermées / en rupture pour le carburant demandé
     (le flux officiel expose les balises `rupture` avec date de début) ;
   - exclure les prix « périmés » (> 7 jours) ;
   - pré-sélection ~20 candidates par Haversine → distances **voiture** via
     une requête Matrix (OSRM/ORS) → scoring prix/distance (cf. §0.10) → top 5 ;
   - rayon adaptatif 5→30 km si résultats insuffisants.
3. **Carte statique** : générée localement (py-staticmaps, tuiles OSM,
   attribution « © OpenStreetMap ») : position utilisateur (point bleu) +
   5 marqueurs numérotés. Envoyée en `sendPhoto` avec la liste en `caption`
   (limite caption : 1024 caractères — rester concis).
4. **Body** : `[1] Nom station — 1.72 € — 3.4 km 🚗 — prix relevé il y a 2 h`.
5. **Footer pénuries** : « ⚠️ N stations plus proches sont en rupture de stock. »

### 3.4 Navigation / deep linking
- Boutons `[1][2][3][4][5]` + `[🔄 Relancer ici]`.
- Au clic : édition du message → choix de la cible :
  - Google Maps : `https://www.google.com/maps/dir/?api=1&destination=LAT,LNG`
  - Apple Plans : `http://maps.apple.com/?daddr=LAT,LNG`
  - **Waze** : `https://waze.com/ul?ll=LAT,LNG&navigate=yes`
  - Tesla : **V2** (Fleet API, OAuth — cf. §0.2)
- Bouton `[← Retour]` pour revenir à la liste (nouvelle édition du message).

## 4. Commandes globales (à enregistrer via BotFather `setMyCommands`)

| Commande | Action |
|---|---|
| `/start` | Onboarding ou menu principal |
| `/carburant` | Changer le carburant par défaut (inline keyboard) |
| `/stats` | Tableau des min/max/médianes nationales pour **tous** les carburants |
| `/position` | Redemander le partage de localisation |
| `/aide` | Aide + rappel du fonctionnement + mention RGPD |

## 5. Sources de données (France) — **section étendue**

### 5.1 Carburants — source principale ⭐
**API Opendatasoft du ministère de l'Économie** (recommandée en V1) :
- Dataset : `prix-des-carburants-en-france-flux-instantane-v2`
- Base : `https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/records`
- Avantages : **JSON natif**, filtres géo intégrés
  (`where=distance(geom, geom'POINT(lng lat)', 10km)`), tri, pagination,
  champs rupture/horaires inclus, pas de worker nécessaire, gratuit, sans clé.
- Limite : 100 enregistrements/requête (suffisant : on demande un rayon).
- Pour les **stats nationales** : agrégations via `group_by`/export, mises en
  cache 10 min côté bot.

### 5.2 Carburants — sources secondaires / repli
| Source | Format | Usage |
|---|---|---|
| `https://donnees.roulez-eco.fr/opendata/instantane` | ZIP → XML (flux officiel prix-carburants.gouv.fr) | Repli si l'API ODS est indisponible ; worker qui télécharge/parse toutes les 10 min |
| `https://donnees.roulez-eco.fr/opendata/jour` | ZIP → XML (quotidien) | Historique / stats journalières |
| data.gouv.fr — « Prix des carburants en France » | Miroir des flux ci-dessus | Redondance |
| API tankerkoenig (DE) | JSON | ⚠️ Allemagne uniquement — utile si extension frontalière future |

### 5.3 Électricité (bornes de recharge)
| Source | Contenu | Limite |
|---|---|---|
| **Open Charge Map** (`api.openchargemap.io/v3/poi`) | Bornes mondiales, connecteurs, puissance | Clé gratuite ; prix rarement renseigné |
| **IRVE consolidé — data.gouv.fr / transport.data.gouv.fr** | Fichier national officiel des bornes (localisation, puissance, opérateur, tarification textuelle) | Statique (maj quotidienne), champ tarif non structuré |
| Gireve / Chargemap Business | Dispo temps réel + tarifs | Clés commerciales — **V2+** |

> Décision V1 : électricité en **mode annuaire** (bornes proches + puissance +
> opérateur, distance voiture), sans classement par prix.

### 5.4 Routage (distance voiture)
1. **V1** : OpenRouteService Matrix (clé gratuite, 2000 req/j) **ou** OSRM
   démo public (`router.project-osrm.org/table/v1/driving/...`) — 1 requête
   par recherche grâce au pré-filtrage Haversine.
2. **V2** : OSRM auto-hébergé (extrait France de Geofabrik, profil `car`).

### 5.5 Carte statique
1. **V1** : rendu local `py-staticmaps` sur tuiles OSM (gratuit, pas de clé).
2. Repli : Geoapify Static Maps (3000 req/j gratuit, marqueurs numérotés).
3. V2+ : Mapbox Static Images si besoin d'un rendu plus premium.

## 6. Architecture technique recommandée

```
┌─────────────┐   long polling    ┌──────────────────────────────┐
│  Telegram    │ ◄───────────────► │  Bot (Python 3.12, aiogram 3)│
└─────────────┘                    │  ├─ FSM onboarding           │
                                   │  ├─ handlers (position, cb)  │
                                   │  ├─ services/                │
                                   │  │   ├─ fuel_api (ODS)       │
                                   │  │   ├─ routing (ORS/OSRM)   │
                                   │  │   ├─ mapgen (staticmaps)  │
                                   │  │   └─ stats (cache 10 min) │
                                   │  └─ SQLite (users, cache)    │
                                   └──────────────────────────────┘
```

- **Stack proposé** : Python 3.12 + `aiogram` 3 (FSM natif, async),
  `httpx` (appels API), `py-staticmaps` + `Pillow` (carte), `aiosqlite`.
- **Long polling** en V1 (zéro infra) ; webhook + reverse proxy en V2.
- **Secrets** : `.env` (déjà en place, gitignoré) chargé via `python-dotenv`.
- **Tests** : unitaires sur le scoring, le parsing ODS et la génération de liens.

## 7. Phasage

| Phase | Contenu |
|---|---|
| **MVP (V1)** | Onboarding FSM, carburants (API ODS), top 5 + carte locale + deep links Google/Apple/Waze, /start /carburant /stats /position /aide, SQLite, rayon adaptatif, footer pénuries |
| **V1.1** | Électricité mode annuaire (Open Charge Map + IRVE), bouton "Relancer ici" |
| **V2** | Tesla Fleet API (OAuth), OSRM auto-hébergé, webhook, Postgres/Redis, alertes prix ("préviens-moi si < 1,65 €") |

## 8. Sécurité & conformité

- 🔴 **Régénérer le token BotFather** (`/revoke`) avant la prod — il a circulé en clair.
- Token uniquement via variable d'environnement.
- Position GPS jamais persistée ; profil = ID Telegram + carburant préféré.
- Mention d'attribution « © OpenStreetMap contributors » sur les cartes.
- Rate limiting par utilisateur ; validation stricte des callback_data.
