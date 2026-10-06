# Alertes capteurs : bornes, liste persistée, temps réel — design

Date : 2026-10-06
Statut : validé, à implémenter

## Objectif

Quand une mesure d'un ESP sort des bornes (température ou humidité hors plage, gaz en alerte),
ouvrir une alerte, la stocker, la pousser en temps réel au front et la fermer d'elle-même quand la
mesure revient dans les bornes. Le Dashboard montre les alertes ouvertes et les dernières
résolues ; une page `/alertes` tient l'historique complet.

Les bornes sont des réglages serveur, identiques pour tous les appareils. Pas d'interface de
configuration, pas d'acquittement : l'alerte vit seule, de sa première mesure hors bornes à son
retour à la normale.

## Hors scope

- Seuils par appareil, édition des seuils dans le front.
- Acquittement, commentaires, assignation.
- Notifications externes (mail, Slack, buzzer).
- Alerte sur capteur muet (valeur manquante ou appareil silencieux).
- Purge des alertes résolues (une commande de plus le jour où la table pèse).

## Bornes (`infrastructure/config.py`)

```python
alert_temperature_min_c: float = 10.0
alert_temperature_max_c: float = 30.0
alert_humidity_min_pct: float = 20.0
alert_humidity_max_pct: float = 70.0
alert_gas_max_mv: int | None = None   # None → seul l'état « alerte » de l'ESP compte
```

Variables d'environnement correspondantes : `ALERT_TEMPERATURE_MIN_C`, `ALERT_TEMPERATURE_MAX_C`,
`ALERT_HUMIDITY_MIN_PCT`, `ALERT_HUMIDITY_MAX_PCT`, `ALERT_GAS_MAX_MV`. Validation : min < max,
sinon l'API refuse de démarrer.

Les bornes sont portées par un objet de valeur du domaine, construit par l'API depuis les settings :

```python
@dataclass(frozen=True, slots=True)
class Thresholds:
    temperature: tuple[float, float]   # (min, max) °C
    humidity: tuple[float, float]      # (min, max) %
    gas_max: int | None                # mV, None = désactivé
```

## Domaine (`domain/alert.py`)

```python
Metric = Literal["temperature", "humidity", "gas"]
Direction = Literal["low", "high"]

@dataclass(frozen=True, slots=True)
class Alert:
    id: UUID
    device_id: str
    metric: Metric
    direction: Direction
    threshold: float          # la borne franchie (pour le gaz avec drapeau ESP seul : 0)
    opened_at: datetime
    opened_value: float       # la première valeur hors bornes
    peak_value: float         # la pire valeur vue (max pour « high », min pour « low »)
    resolved_at: datetime | None
    resolved_value: float | None

    @classmethod
    def open(cls, *, device_id, metric, direction, threshold, at: datetime, value: float) -> Alert
    @property
    def is_open(self) -> bool: ...
    def worsen(self, value: float) -> Alert        # nouvel Alert si `value` est pire, sinon self
    def resolve(self, at: datetime, value: float) -> Alert
```

### Évaluation (`domain/alert.py`, fonctions pures)

```python
@dataclass(frozen=True, slots=True)
class Violation:
    metric: Metric
    direction: Direction
    threshold: float
    value: float

def violations(reading: SensorReading, t: Thresholds) -> dict[Metric, Violation | None]
def back_in_range(alert: Alert, reading: SensorReading, t: Thresholds) -> bool
```

- `violations` : température < min → `low`, > max → `high` ; idem humidité ; gaz : `gas_alert`
  vrai → `high` avec `threshold = t.gas_max or 0` et `value = gas_level or 0` ; sinon si
  `t.gas_max` est défini et `gas_level > gas_max` → `high`. Une valeur `None` donne `None`
  (pas de violation, pas de résolution : on ne sait pas).
- `back_in_range` (hystérésis, pour fermer une alerte ouverte) :
  - température : `high` → valeur ≤ max − 0,5 ; `low` → valeur ≥ min + 0,5 ;
  - humidité : `high` → valeur ≤ max − 2 ; `low` → valeur ≥ min + 2 ;
  - gaz : drapeau `gas_alert` faux **et** (`gas_max` indéfini ou `gas_level` ≤ 0,95 × `gas_max`).
  - valeur manquante → `False` (on garde l'alerte ouverte).

Les marges sont des constantes du domaine (`TEMPERATURE_MARGIN_C = 0.5`, `HUMIDITY_MARGIN_PCT = 2.0`,
`GAS_MARGIN_RATIO = 0.05`), pas des réglages.

## Dépôt (`domain/repositories.py`, `UnitOfWork.alerts`)

```python
class AlertRepository(ABC):
    async def add(self, alert: Alert) -> None
    async def save(self, alert: Alert) -> None                     # mise à jour par id
    async def open_for(self, device_id: str, metric: Metric) -> Alert | None
    async def list(self, status: Literal["open", "resolved", "all"], device_id: str | None,
                   limit: int) -> list[Alert]
    """Ouvertes d'abord, puis par opened_at décroissant, au plus `limit`."""
    async def count_open(self) -> int
```

Table `alerts` (migration `0004_create_alerts`) :

| colonne          | type                     |
|------------------|--------------------------|
| id               | uuid pk                  |
| device_id        | varchar(64) not null     |
| metric           | varchar(16) not null     |
| direction        | varchar(4) not null      |
| threshold        | float not null           |
| opened_at        | timestamptz not null     |
| opened_value     | float not null           |
| peak_value       | float not null           |
| resolved_at      | timestamptz null         |
| resolved_value   | float null               |

Index : `ix_alerts_opened_at` sur `opened_at` ; **unique partiel** `uq_alerts_open_per_metric` sur
(`device_id`, `metric`) `WHERE resolved_at IS NULL` : une seule alerte ouverte par appareil et
métrique, garanti par la base même en cas de double ingestion.

## Cas d'usage : `RecordReading` évalue les alertes

`RecordReading(uow, broadcaster, thresholds, clock)` : après `uow.readings.add(reading)` et avant
`commit`, pour chaque métrique :

```
open = await uow.alerts.open_for(device, metric)
v = violations[metric]
if v and open is None:        new = Alert.open(...)   → add ; events.append(("alert.opened", new))
elif v and open:              worse = open.worsen(v.value) ; if worse is not open: save (pas d'événement)
elif open and back_in_range:  done = open.resolve(at=reading.recorded_at, value) → save ;
                              events.append(("alert.resolved", done))
```

Un seul `commit` couvre la mesure et ses alertes. Les événements partent après le commit :
d'abord `sensor.reading` (inchangé), puis chaque événement d'alerte. `opened_at` et `resolved_at`
prennent `reading.recorded_at` (l'heure plausible déjà calculée), pas l'heure de traitement.

Le souscripteur MQTT et la route HTTP passent tous deux par `RecordReading` : rien à changer chez
eux à part le paramètre `thresholds` injecté depuis `app.state.thresholds`.

## API (`presentation/http/alerts.py`, tag `alerts`, JWT requis)

`GET /alerts?status=open|resolved|all&device_id=…&limit=100` (défaut `all`, `limit` 1–500) :

```json
[
  {
    "id": "…", "device_id": "esp-interieur", "metric": "temperature", "direction": "high",
    "threshold": 30.0, "opened_at": "2026-10-06T09:12:03Z", "opened_value": 30.4,
    "peak_value": 31.2, "resolved_at": null, "resolved_value": null
  }
]
```

`GET /alerts/summary` → `{"open": 2}` (pour le badge de la nav sans charger la liste).

## WebSocket

Deux événements sur `/ws`, mêmes clés que la réponse REST, dates en `…Z` :

```json
{ "type": "alert.opened",   "data": { "…": "alerte" } }
{ "type": "alert.resolved", "data": { "…": "alerte" } }
```

## Simulateur

`simulate-sensors --spike` : après 5 mesures normales, 6 mesures hors bornes puis retour à la
normale, et s'arrête. `--spike-metric temperature|humidity|gas` (défaut `temperature`) : 33 °C,
78 % ou drapeau `mostGaz` à vrai, valeurs au-delà des bornes par défaut (le simulateur ne connaît
pas les settings de l'API ; avec des bornes personnalisées, ajuster ou s'en passer). Permet de voir une alerte
s'ouvrir puis se fermer sans matériel.

## Front

### `features/alerts/`

- `alerts-api.ts` : type `Alert` (miroir du JSON), `ALERTS_PATH`, `ALERTS_SUMMARY_PATH`,
  `METRIC_LABELS` (« Température », « Humidité », « Gaz »), `UNITS` (« °C », « % », « mV »),
  `describe(alert)` → « Température 31,2 °C > 30 °C » (pic et borne, symbole `>` pour `high`, `<`
  pour `low` ; gaz sans borne → « Gaz : alerte ESP »), `upsert(list, alert)` (remplace par id,
  réordonne ouvertes d'abord puis `opened_at` décroissant), `durationLabel(alert, now)` →
  « depuis 4 min » (ouverte) ou « 12 min » (résolue, durée totale).
- `use-alerts.ts` : charge `GET /alerts?limit=…` puis applique `alert.opened` / `alert.resolved`
  via `useEventStream`. Mêmes règles que `useServerHealth` : événement reçu pendant le chargement
  gardé puis fusionné, récupération sur le premier événement si la requête a échoué. Retourne
  `{ status, alerts, open, connected }` où `open = alerts.filter(a => !a.resolved_at)`.
- `alert-row.tsx` : une ligne : pastille (rouge ouverte, grise résolue), appareil, `describe`,
  heure d'ouverture, `durationLabel`. `role="listitem"`.
- `alerts-card.tsx` : `Link to="/alertes"` (`aria-label="Alertes, voir l'historique"`) → `Card`
  « Alertes » avec un `Badge` destructive « 2 ouvertes » (ou « Aucune alerte » en gris), liste
  des ouvertes puis des 5 dernières résolues. État `loading` → `Skeleton`, `error` → « Alertes
  indisponibles ».
- `alerts-page-content.tsx` (`/alertes`) : titre « Alertes », filtres état (Toutes / Ouvertes /
  Résolues) et appareil (liste venant de `GET /sensors/devices`), tableau : état, appareil,
  métrique, valeur / borne, ouverte à, résolue à, durée. Vide → « Aucune alerte ».

### Intégration

- `pages/dashboard.tsx` : la carte « Alertes » prend toute la largeur entre la rangée
  caméra/serveur et la section capteurs.
- `pages/alerts.tsx` + route `/alertes` + `TITLES` + entrée de nav « Alertes » (icône
  `BellRing`) avec un badge rouge du nombre d'ouvertes (`GET /alerts/summary` puis événements).
  Le badge est aussi lisible en mode replié (petit point rouge avec le nombre).
- `features/metrics/metric-tiles.tsx` : prop `openAlerts: Alert[]` ; une tuile dont la métrique a
  une alerte ouverte pour l'appareil affiché porte le badge destructive « Alerte » (le badge
  « Alerte gaz » actuel, piloté par `gas_alert`, est remplacé par ce mécanisme : la liste des
  alertes est la seule source de vérité).
- `MetricsSection` reçoit `openAlerts` du Dashboard (le hook `useAlerts` est monté une fois dans
  la page et partagé par la carte et les tuiles).

### Couleurs

Ouverte : `--destructive` (pastille, badge) avec le mot « Ouverte » ; résolue : `--muted-foreground`
et « Résolue ». Jamais la couleur seule.

## Tests

Backend :

- `tests/unit/test_alert_domain.py` : `violations` pour chaque métrique et direction, valeurs
  manquantes, gaz par drapeau et par borne ; `back_in_range` avec hystérésis (juste sous la borne
  → toujours ouverte, sous la marge → fermée) ; `worsen`, `resolve`.
- `tests/unit/test_record_reading.py` (étendre) : ouverture → événement `alert.opened` après
  `sensor.reading` ; mesure pire → pic mis à jour sans événement ; retour dans la marge → pas
  d'événement ; retour sous la marge → `alert.resolved` avec `resolved_value` ; valeur manquante →
  rien ne change ; deux métriques hors bornes → deux alertes.
- `tests/unit/test_settings.py` : défauts, min ≥ max refusé.
- `tests/integration/test_alert_repository.py` : `open_for`, `list` (ordre, filtres, limite),
  `count_open`, contrainte unique partielle (deux ouvertes → `IntegrityError`).
- `tests/integration/test_alerts_http.py` : 401, liste vide, une mesure hors bornes postée → une
  alerte ouverte dans la liste et `summary.open == 1`, puis une mesure normale → résolue ;
  événements reçus sur `/ws` dans l'ordre.
- `tests/unit/test_simulate_sensors.py` (étendre) : `--spike` produit la séquence annoncée.

Frontend :

- `alerts-api.test.ts` : `describe`, `durationLabel`, `upsert` (ordre, remplacement).
- `use-alerts.test.tsx` : chargement puis `alert.opened` ajoute, `alert.resolved` remplace ;
  événement pendant le chargement ; erreur puis récupération.
- `alerts-card.test.tsx` : badge « 2 ouvertes », lignes, lien `/alertes`, « Aucune alerte ».
- `alerts-page-content.test.tsx` : filtres état et appareil, tableau.
- `metric-tiles` via `metrics-section.test.tsx` : badge « Alerte » sur la tuile température
  quand une alerte température est ouverte ; plus de badge piloté par `gas_alert` seul.
- `app-sidebar.test.tsx` : entrée « Alertes » et badge de compte.
- `dashboard.test.tsx` : la carte « Alertes » présente, clic → `/alertes`.

## README

Section « Alertes » : bornes et variables d'env, cycle de vie avec hystérésis, routes, événements,
`simulate-sensors --spike`.
