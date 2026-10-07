# Sirène : buzzer de l'ESP32 piloté en MQTT par les alertes — design

Date : 2026-10-07
Statut : implémenté le 2026-10-07

## Objectif

Quand une alerte qui le mérite est ouverte, le buzzer de l'ESP32-S3 extérieur sonne ; il s'arrête
quand tout est résolu, ou quand quelqu'un coupe la sirène depuis le front pour un quart d'heure.
L'API publie l'**état** du buzzer sur un topic MQTT **retenu** : un ESP qui redémarre ou se
reconnecte reçoit l'état courant sans attendre la prochaine alerte.

Décisions prises avec l'utilisateur : comportement à état (pas un bip par alerte), déclencheurs
gaz et température haute, bouton « Couper 15 min » dans le front, contrat + exemple fournis à
l'équipe pour la partie ESP.

## Hors scope

- Motifs sonores différents selon la métrique (un seul état `on`/`off`).
- Acquittement des alertes, historique des coupures (la coupure est journalisée, pas stockée).
- Buzzer ou LED pilotés pour le digicode (c'est le firmware qui s'en charge localement).
- Authentification MQTT (le broker reste anonyme sur le LAN, comme aujourd'hui).

## Contrat MQTT (ce que l'ESP consomme)

- **Topic** : `sentinel/cmd/buzzer` — trois segments, donc **hors** du joker `sentinel/+` que l'API
  écoute pour les mesures : l'API ne lira jamais ses propres commandes comme des mesures.
- **QoS 1, message retenu** : le broker garde le dernier état, tout abonné le reçoit à la connexion.
- **Payload** JSON **compact** (sans espaces, `on` en premier ; présenté aéré ci-dessous) :

```json
{"on": true,  "reason": "gas",  "open": 2, "muted_until": null,                   "at": "2026-10-07T09:12:03Z"}
{"on": false, "reason": "gas",  "open": 1, "muted_until": "2026-10-07T09:27:03Z", "at": "2026-10-07T09:12:03Z"}
```

  - `on` : ce que le buzzer doit faire. C'est la seule clé que l'ESP doit lire.
  - `reason` : la métrique qui ferait sonner (`gas` prioritaire sur `temperature`), gardée pendant une
    coupure pour que le front puisse dire « coupée (gaz) » ; `null` quand rien ne correspond.
  - `open` : nombre d'alertes ouvertes toutes métriques confondues (information).
  - `muted_until` : fin de la coupure en cours, `null` sinon.
  - `at` : horodatage de la décision.

Règle : `on = (au moins une alerte ouverte dont la métrique et le sens figurent dans
BUZZER_TRIGGERS) et (pas de coupure en cours)`.

### Exemple côté ESP (Arduino, bibliothèque PubSubClient, à intégrer dans le firmware de NoAh)

```c
#include <WiFi.h>
#include <PubSubClient.h>

#define BUZZER_PIN 2                 // à adapter au câblage
const char* MQTT_HOST = "192.168.0.70";
const char* TOPIC_BUZZER = "sentinel/cmd/buzzer";

WiFiClient wifi;
PubSubClient mqtt(wifi);
bool sirene = false;

void onMessage(char* topic, byte* payload, unsigned int len) {
  // Copie locale terminée par \0 : le tampon de PubSubClient n'a pas de place pour ce \0.
  char buf[256];
  size_t n = len < sizeof buf - 1 ? len : sizeof buf - 1;
  memcpy(buf, payload, n);
  buf[n] = '\0';
  // L'API publie du JSON compact : {"on":true,...}. On tolère aussi un espace après le deux-points.
  sirene = strstr(buf, "\"on\":true") != nullptr || strstr(buf, "\"on\": true") != nullptr;
}

void mqttLoop() {
  if (!mqtt.connected()) {
    if (mqtt.connect("esp-exterieur")) mqtt.subscribe(TOPIC_BUZZER, 1);  // QoS 1 : l'état retenu arrive aussitôt
    else return;
  }
  mqtt.loop();
}

void buzzerLoop() {
  // Bips de 200 ms tant que la sirène est demandée, sans bloquer la caméra ni le digicode.
  static uint32_t t = 0; static bool etat = false;
  if (!sirene) { digitalWrite(BUZZER_PIN, LOW); etat = false; return; }
  if (millis() - t > 200) { t = millis(); etat = !etat; digitalWrite(BUZZER_PIN, etat); }
}

// setup(): pinMode(BUZZER_PIN, OUTPUT); mqtt.setServer(MQTT_HOST, 1883); mqtt.setCallback(onMessage);
// loop():  mqttLoop(); buzzerLoop();
```

Si le Wi-Fi ou le broker tombent, l'ESP garde le dernier état reçu ; au retour, le message retenu
le remet d'équerre.

## Réglages (`infrastructure/config.py`)

```python
mqtt_buzzer_topic: str = "sentinel/cmd/buzzer"
buzzer_triggers: str = "gas,temperature:high"   # "metric" ou "metric:low|high", séparés par des virgules
buzzer_mute_minutes: int = 15                   # durée d'une coupure depuis le front
```

Validation : chaque jeton de `buzzer_triggers` est une métrique connue, avec un sens optionnel ;
sinon l'API refuse de démarrer. Sans `MQTT_HOST`, la sirène est calculée et affichée mais rien
n'est publié (dev sur Mac).

## Domaine (`domain/siren.py`, fonctions pures)

```python
@dataclass(frozen=True, slots=True)
class Trigger:
    metric: Metric
    direction: Direction | None   # None = les deux sens

def parse_triggers(spec: str) -> tuple[Trigger, ...]        # "gas,temperature:high"

@dataclass(frozen=True, slots=True)
class SirenState:
    on: bool
    reason: Metric | None
    open: int
    muted_until: datetime | None

def decide(open_alerts: Sequence[Alert], triggers, muted_until, now) -> SirenState
```

`decide` : `open = len(open_alerts)` ; les alertes qui correspondent à un déclencheur donnent
`reason` (gaz avant température avant humidité) ; `on` vrai si une correspondance existe et que
`muted_until` est `None` ou dépassé ; `muted_until` recopié tel quel s'il est encore à venir,
`None` sinon.

## Application (`application/alerts/siren.py`)

```python
class SirenPublisher(Protocol):              # port
    async def publish(self, state: SirenState, at: datetime) -> None: ...

class Siren:
    def __init__(self, uow_factory, publisher: SirenPublisher | None, broadcaster,
                 triggers, mute_minutes: int, clock=utc_now) -> None
    async def refresh(self) -> SirenState     # relit les alertes ouvertes, publie si l'état change, diffuse
    async def mute(self, by: UUID) -> SirenState      # muted_until = now + mute_minutes, log "muted by <user>"
    async def unmute(self, by: UUID) -> SirenState
    @property
    def state(self) -> SirenState
```

- `refresh` publie quand `on` ou `reason` changent, **et** au premier appel (démarrage : le
  message retenu doit refléter la réalité après un redémarrage de l'API). Chaque publication est
  suivie d'un événement WebSocket `siren.state` avec le même JSON que le payload MQTT.
- `RecordReading` prend un paramètre optionnel `on_alerts_changed: Callable[[], Awaitable[None]]`,
  appelé après le `commit` et les événements d'alerte, seulement si au moins une alerte s'est
  ouverte ou fermée. L'API y branche `siren.refresh`. Le souscripteur MQTT et la route HTTP le
  reçoivent de la même façon que `thresholds`.
- Une tâche de fond (`asyncio.create_task`) dort jusqu'à `muted_until` puis appelle `refresh` :
  la sirène repart seule à la fin de la coupure si une alerte est encore ouverte. La tâche est
  remplacée à chaque `mute` et annulée à l'arrêt.
- Toute erreur de publication est journalisée, l'état reste calculé et affiché ; la prochaine
  `refresh` retentera.

## Infrastructure (`infrastructure/mqtt/publisher.py`)

```python
class MqttSirenPublisher:
    def __init__(self, host: str, port: int, topic: str) -> None
    async def publish(self, state: SirenState, at: datetime) -> None
```

Une connexion `aiomqtt.Client` **ouverte à la demande** pour chaque publication (`async with`),
`qos=1`, `retain=True`, identifiant `sentinel-x-siren`. Les publications sont rares (changement
d'état, coupure, démarrage) : pas de connexion permanente à maintenir, pas de reconnexion à gérer.

## API (`presentation/http/alerts.py`, JWT requis)

- `GET /alerts/siren` → `{"on": …, "reason": …, "open": …, "muted_until": …}`.
- `POST /alerts/siren/mute` → coupe pour `buzzer_mute_minutes` ; renvoie l'état. Journal :
  `siren muted until <t> by <user_id>`.
- `DELETE /alerts/siren/mute` → lève la coupure ; renvoie l'état.

## WebSocket

`{"type": "siren.state", "data": {"on": …, "reason": …, "open": …, "muted_until": …, "at": …}}`
à chaque changement, coupure ou levée de coupure.

## Front

- `features/alerts/siren-api.ts` : type `SirenState`, chemins, `sirenLabel(state, nowMs)` →
  « Sirène active : gaz » / « Sirène coupée jusqu'à 09:27 » / « Sirène au repos ».
- `use-siren.ts` : `GET /alerts/siren` puis événements `siren.state` (même schéma que
  `useAlerts` : attente, récupération, resynchronisation après reconnexion).
- `siren-bar.tsx` : une barre fine au-dessus de la carte « Alertes » du Dashboard et sous la
  synthèse de `/alertes` : icône `BellRing` rouge qui pulse quand `on`, `BellOff` grise quand
  coupée, `Bell` neutre au repos ; texte `sirenLabel` ; bouton **« Couper 15 min »** quand `on`,
  **« Réactiver »** quand coupée. La barre est en dehors du lien de la carte (un lien ne contient
  pas de bouton). Le bouton appelle `POST`/`DELETE /alerts/siren/mute` et met l'état à jour avec
  la réponse, l'événement WebSocket confirmant ensuite.
- Le Dashboard monte `useSiren` une fois et le partage avec la barre.

## Tests

Backend :
- `tests/unit/test_siren_domain.py` : `parse_triggers` (valides, sens optionnel, jeton inconnu
  → `ValueError`) ; `decide` : aucune alerte, humidité seule (pas de sirène), température basse
  seule (pas de sirène avec `temperature:high`), gaz ouvert (on, reason gas), gaz + température
  (reason gas), coupure en cours (off, `muted_until` recopié), coupure expirée (on, `muted_until`
  None).
- `tests/unit/test_siren.py` : `refresh` publie au premier appel puis seulement aux changements ;
  `mute` publie off et programme la reprise ; la reprise republie on si une alerte reste ouverte ;
  `unmute` ; échec de publication journalisé sans exception ; `RecordReading` appelle
  `on_alerts_changed` seulement quand une alerte s'ouvre ou se ferme.
- `tests/unit/test_settings.py` : défauts, `BUZZER_TRIGGERS` invalide refusé.
- `tests/integration/test_siren_http.py` : 401 ; état initial off ; mesure gaz en alerte →
  `GET /alerts/siren` on avec `reason: gas` et événement `siren.state` sur `/ws` après
  `alert.opened` ; `POST mute` → off avec `muted_until` ; `DELETE mute` → on ; mesure normale →
  off.
- `tests/unit/test_mqtt_publisher.py` : topic, `retain=True`, `qos=1`, payload JSON avec
  `"on"` en premier (fake client).

Frontend :
- `siren-api.test.ts` : `sirenLabel` dans les trois états.
- `use-siren.test.tsx` : chargement, événement, récupération.
- `siren-bar.test.tsx` : trois rendus, clic « Couper 15 min » appelle `POST` et affiche la
  coupure, clic « Réactiver » appelle `DELETE`.
- `dashboard.test.tsx` : la barre est présente au-dessus de la carte Alertes, hors du lien.

## README

Section « Alertes » : paragraphe « Sirène » avec le topic, le payload, les réglages, la coupure, et
un renvoi vers l'exemple ESP de ce spec.
