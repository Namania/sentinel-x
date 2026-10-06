# Mesures capteurs (température, humidité, gaz) — design

Date : 2026-10-06
Statut : en attente de relecture

## Objectif

Recevoir les mesures de l'ESP32 intérieur (DHT11 : température et humidité ; MQ-2 : gaz),
les stocker, les exposer par l'API REST pour l'historique et les pousser en temps réel sur le
WebSocket existant, puis les afficher dans le front sous plusieurs formes de graphiques.

MQTT viendra plus tard : l'ingestion se fait pour l'instant par une route HTTP protégée par
une clé d'appareil. L'abonné MQTT réutilisera le même cas d'usage `RecordReading`, sans toucher
au stockage, au WebSocket ni au front.

## Hors scope

- Broker MQTT et abonné (lot suivant).
- Capteur de mouvement (PIR), digicode, alertes physiques (buzzer, LED).
- Rétention ou purge automatique des mesures.
- Seuils d'alerte configurables côté serveur (le seuil gaz vient de l'ESP : `mostGaz`).
- Export CSV, notifications.

## Format d'entrée (contrat avec l'ESP, d'après la note « data ESP32 »)

```json
{
  "device_id": "esp-interieur",
  "recorded_at": "2026-10-06T09:12:03Z",
  "gaz": { "mostGaz": false, "quantity": 412 },
  "temperature": { "humidity": 48.5, "temp": 22.9 }
}
```

- `device_id` : identifiant stable de l'ESP, 1 à 64 caractères `[a-z0-9-]`. Obligatoire.
- `recorded_at` : optionnel ; horodatage côté serveur si absent (l'ESP n'a pas d'horloge fiable).
- `gaz` et `temperature` : chacun optionnel (un capteur en panne n'empêche pas l'autre).
- `quantity` en ppm, entier ≥ 0 ; `temp` en °C dans [-40, 125] ; `humidity` en % dans [0, 100].
  Hors bornes → 422.

## Modèle

### Domaine (`backend/src/app/domain/sensor_reading.py`)

```python
@dataclass(frozen=True, slots=True)
class SensorReading:
    id: UUID
    device_id: str
    recorded_at: datetime          # UTC
    temperature_c: float | None
    humidity_pct: float | None
    gas_ppm: int | None
    gas_alert: bool                # mostGaz de l'ESP

    @classmethod
    def create(cls, device_id, recorded_at, temperature_c, humidity_pct, gas_ppm, gas_alert)
        # valide device_id et les bornes ; lève InvalidReading (DomainError)
```

Une ligne par message reçu (format « large ») : c'est la forme du message, elle se requête
simplement, et une ligne regroupe les trois métriques prises au même instant. Si d'autres
capteurs arrivent plus tard (PIR), ils auront leur propre entité.

### Dépôt (`domain/repositories.py`)

```python
class SensorReadingRepository(ABC):
    async def add(self, reading: SensorReading) -> None
    async def list(self, device_id, since, until, limit) -> list[SensorReading]   # ordre chronologique
    async def latest(self) -> list[SensorReading]                                  # la dernière de chaque appareil
    async def aggregate(self, device_id, since, until, bucket_seconds) -> list[ReadingBucket]
```

`ReadingBucket` (dataclass) : `bucket_start`, `count`, puis `avg/min/max` pour `temperature_c`,
`humidity_pct`, `gas_ppm`, et `gas_alerts` (nombre de lectures en alerte). L'agrégation se fait
en SQL (`to_timestamp(floor(extract(epoch from recorded_at) / b) * b)`), portable Postgres.

### Base (`infrastructure/db`, migration `0002_create_sensor_readings`)

Table `sensor_readings` : `id uuid pk`, `device_id varchar(64)`, `recorded_at timestamptz`,
`temperature_c double precision null`, `humidity_pct double precision null`, `gas_ppm integer
null`, `gas_alert boolean not null`. Index `(device_id, recorded_at)`.

`UnitOfWork` gagne `readings: SensorReadingRepository`.

## Cas d'usage (`application/sensors/`)

| Cas d'usage | Entrée | Sortie | Effet |
|---|---|---|---|
| `RecordReading` | `ReadingInput` (le JSON ci-dessus, aplati) | `ReadingOutput` | persiste, commit, puis `broadcaster.broadcast({"type": "sensor.reading", "data": ReadingOutput})` |
| `GetReadings` | device_id, since, until, bucket_seconds ou None, limit | `list[ReadingOutput]` ou `list[BucketOutput]` | lecture seule |
| `GetLatestReadings` | — | `list[ReadingOutput]` | lecture seule |

`ReadingOutput` est le modèle « plat » : `id, device_id, recorded_at, temperature_c,
humidity_pct, gas_ppm, gas_alert`. C'est aussi la charge utile de l'événement WebSocket.

## API

| Méthode | Route | Auth | Réponse |
|---|---|---|---|
| POST | `/sensors/readings` | en-tête `X-Device-Key` = `DEVICE_API_KEY` | 201 `ReadingOutput` ; 401 clé absente/fausse ; 422 corps invalide ; 503 si `DEVICE_API_KEY` non configurée |
| GET | `/sensors/readings?device_id=&from=&to=&bucket=` | utilisateur (Bearer) | 200 liste de `ReadingOutput` (sans `bucket`) ou de `BucketOutput` (`bucket` ∈ `1m,5m,15m,1h`) ; `from` défaut = maintenant − 1 h ; max 2000 lignes brutes |
| GET | `/sensors/latest` | utilisateur | 200 liste de `ReadingOutput`, une par appareil |
| GET | `/sensors/devices` | utilisateur | 200 `[{device_id, last_seen}]` (dérivé des mesures) |

Réglage : `DEVICE_API_KEY` (optionnel, ≥ 16 caractères sinon refus au démarrage comme
`JWT_SECRET`), ajouté à `.env.example`. Le front ne la connaît jamais.

## WebSocket

Canal `/ws` existant : à chaque mesure enregistrée, le hub diffuse à tous les utilisateurs
connectés `{"type": "sensor.reading", "data": ReadingOutput}`. Pas d'abonnement par appareil
pour l'instant (un seul ESP) ; le front filtre côté client.

## Outil de développement : `simulate-sensors`

Commande `uv run simulate-sensors [--base-url http://localhost:8000] [--device esp-interieur]
[--interval 2] [--count N]` : envoie des mesures plausibles (marche aléatoire bornée,
pic de gaz occasionnel avec `mostGaz=true`) sur `POST /sensors/readings` avec la clé lue dans
`.env`. Permet de voir les graphiques sans matériel ; la génération est testée unitairement.

## Front : page « Mesures » (`/metrics`)

Entrée « Mesures » dans la sidebar (icône `Activity`), titre « Mesures · sentinel-x ».

### Données

- `useReadings(deviceId, range)` : charge l'historique via `authFetch`
  (`/sensors/readings?device_id&from&bucket`) avec `bucket` selon la plage : 15 min → brut ;
  1 h → `1m` ; 6 h → `5m` ; 24 h → `15m`.
- `useSensorStream(onReading)` : ouvre `ws(s)://<host>/ws?token=<accessToken>`, parse les
  messages `sensor.reading`, reconnexion avec attente croissante (1 s → 30 s) ; se referme au
  démontage ; se rouvre si le token change (le WS n'authentifie qu'à la connexion).
- En direct (interrupteur « Direct », actif par défaut) : les nouvelles mesures de l'appareil
  sélectionné s'ajoutent aux séries (dans le dernier bucket si agrégé) et mettent à jour les
  tuiles ; la plage glisse.

### Mise en page (méthode dataviz : forme d'abord, couleur ensuite, une seule échelle par graphique)

1. **Filtres** sur une ligne : appareil (`/sensors/devices`), plage (15 min · 1 h · 6 h · 24 h),
   interrupteur Direct, bascule « Graphiques / Tableau ».
2. **Tuiles** (dernière mesure) : Température (°C), Humidité (%), Gaz (ppm), chacune avec la
   variation depuis la mesure précédente et l'heure ; la tuile Gaz porte un badge d'état
   « Alerte gaz » (couleur d'état + icône + texte) quand `gas_alert` est vrai.
3. **Température** — courbe (ligne 2 px, marqueurs ≥ 8 px au survol, réticule + info-bulle).
4. **Humidité** — aire (même anatomie, remplissage à 20 %).
5. **Gaz** — barres par bucket (moyenne), extrémités arrondies 4 px, 2 px d'espace ; les buckets
   contenant une alerte sont marqués par un point d'état au-dessus de la barre (pas par la
   couleur seule).
6. **Jauge gaz** — radial pour la dernière valeur par rapport au maximum de la plage, hors
   couleur sémantique.
7. **Tableau** : les mêmes données (brutes ou buckets) en table accessible, pour la lecture
   sans graphique et pour les tests.

Un graphique = une métrique = une échelle ; jamais deux axes. Le titre nomme la série, pas de
légende pour une série unique. Les valeurs textuelles utilisent les couleurs de texte du thème,
jamais la couleur de la série.

### Couleurs

Trois teintes fixes, une par métrique, déclarées dans `index.css` (`--metric-temperature`,
`--metric-humidity`, `--metric-gas`) en clair et en sombre, validées avec le script
`validate_palette.js` du skill dataviz (séparation daltonisme, contraste sur la surface).
État « Alerte gaz » : `--destructive` du thème avec icône et texte.

### Composants

`src/features/metrics/` : `metrics-api.ts` (types, chemins, `bucketFor(range)`),
`use-readings.ts`, `use-sensor-stream.ts`, `metric-tiles.tsx`, `temperature-chart.tsx`,
`humidity-chart.tsx`, `gas-chart.tsx`, `gas-gauge.tsx`, `readings-table.tsx`,
`metrics-filters.tsx` ; page `src/pages/metrics.tsx`. Composants shadcn ajoutés : `chart`
(Recharts), `select`, `switch`, `table`, `toggle-group`.

### Tests

- Backend : entité (bornes, device_id), use cases avec fakes (enregistrement + diffusion),
  dépôt SQL (list / latest / aggregate), routes (201, 401 clé, 422, 503 sans clé ; GET brut et
  agrégé, `from` par défaut), WS (une mesure postée arrive sur un client WS connecté),
  `simulate-sensors` (générateur borné).
- Front : hook WS (msw `ws`) : connexion avec token, parsing, reconnexion ; `useReadings`
  (bucket selon plage) ; page : tuiles avec valeurs et badge d'alerte, bascule tableau avec les
  lignes, filtres (changement de plage recharge), mise à jour en direct d'une tuile à la
  réception d'un message WS. Les SVG Recharts ne se mesurent pas sous jsdom : les tests passent
  par les tuiles, le tableau et les titres.

## README

Section « Capteurs » : format du POST, clé `DEVICE_API_KEY`, `simulate-sensors`, page Mesures.
