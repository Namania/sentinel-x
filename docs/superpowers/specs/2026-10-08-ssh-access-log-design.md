# Accès SSH : journal des connexions au Pi et alertes sur les refus — design

Date : 2026-10-08
Statut : validé en discussion le 2026-10-08, à implémenter

## Objectif

Voir dans l'interface web qui s'est connecté en SSH au Raspberry Pi, et qui a essayé sans y
arriver. Une connexion acceptée est affichée avec le **mail de la clé** (le commentaire de la clé
dans `~/.ssh/authorized_keys`, par exemple `mael.namania@gmail.com`). Une connexion refusée est
affichée avec l'utilisateur tenté, l'IP et la raison, et ouvre une **alerte** de métrique `ssh`,
une par IP, qui se ferme seule après dix minutes de calme.

Décisions prises avec l'utilisateur : les refus sont de vraies alertes (frise, carte du
dashboard, badge, sirène possible) ; toutes les connexions, acceptées et refusées, sont listées sur
une **page dédiée** « Accès SSH » dans la sidebar ; la sirène ne sonne pas par défaut sur `ssh`.

## Hors scope

- Blocage des IP (fail2ban reste une décision de durcissement à part).
- Connexions autres que SSH (Dokploy, Mosquitto, interface web elle-même).
- Rétention : comme les alertes, tout est gardé ; l'interface charge les 500 plus récentes.
- Notification par mail ou push.

## Contraintes vérifiées sur le Pi (2026-10-08)

- Debian 13, pas de `/var/log/auth.log` : sshd journalise dans journald, unité `ssh.service`,
  identifiant `sshd-session`. Le journal est lisible par `sentinel-x` sans sudo (groupe `adm`).
- Une connexion acceptée est journalisée avec l'empreinte de la clé, pas son commentaire :
  `Accepted publickey for sentinel-x from 192.168.0.18 port 49513 ssh2: ED25519 SHA256:Wqjh…`.
  `ssh-keygen -lf ~/.ssh/authorized_keys` donne `256 SHA256:Wqjh… claude-audit@mac-namania (ED25519)`
  par ligne, options comprises : c'est le croisement empreinte → commentaire.
- Un refus est journalisé sans empreinte au niveau de log par défaut (`INFO`) : on ne saura pas
  quelle clé a été tentée, seulement l'utilisateur, l'IP et la raison.
- Le conteneur API ne peut pas lire le journal : en Docker rootless, les groupes hôte (`adm`) ne
  sont pas mappés dans le conteneur. D'où un agent sur l'hôte.
- `loginctl show-user sentinel-x` → `Linger=no` : les services utilisateur (dont le Docker
  rootless) s'arrêtent à la fin de la dernière session. L'installation de l'agent active le linger.

## Vue d'ensemble

```
journald (ssh.service) ──journalctl -f -o json──▶ scripts/ssh-log-agent.py (hôte, systemd --user)
                                                        │  empreinte → commentaire (authorized_keys)
                                                        │  POST /api/ssh/events  (X-Device-Key)
                                                        ▼
                                   API : table ssh_events, événement WS ssh.event,
                                         alerte `ssh` par IP sur refus (ouvre / incrémente / résout)
                                                        ▼
                                   Front : page /ssh (journal), métrique `ssh` dans les alertes
```

## 1. Agent hôte — `scripts/ssh-log-agent.py`

Python 3 standard (3.13 sur le Pi), aucune dépendance. Un seul fichier, testable : la lecture du
journal, l'analyse des lignes, le croisement des clés et l'envoi sont des fonctions séparées.

### Réglages (variables d'environnement)

| Variable | Défaut | Rôle |
|---|---|---|
| `SENTINEL_API_URL` | `http://127.0.0.1:8080/api` | base de l'API (nginx du conteneur `web`) |
| `DEVICE_API_KEY` | obligatoire | même clé que les ESP, en-tête `X-Device-Key` |
| `SENTINEL_AUTHORIZED_KEYS` | `~/.ssh/authorized_keys` | fichier des clés autorisées |
| `SENTINEL_STATE_DIR` | `~/.local/state/sentinel-x` | curseur journald (`ssh-log.cursor`) |
| `SENTINEL_JOURNAL_UNIT` | `ssh` | unité systemd suivie |
| `SENTINEL_FIRST_RUN_SINCE` | `-24h` | historique rejoué au tout premier démarrage |

### Lecture du journal

`journalctl -u ssh -o json -f --no-pager` plus `--after-cursor <cursor>` si un curseur est
mémorisé, sinon `--since -24h`. Chaque ligne JSON fournit `MESSAGE`, `__CURSOR` (unique, repris
tel quel comme `journal_id`), `__REALTIME_TIMESTAMP` (microsecondes, → `occurred_at` UTC) et
`_PID`. Si `journalctl` se termine, l'agent le relance après 5 s depuis le dernier curseur.

### Lignes reconnues (tout le reste est ignoré)

| Ligne sshd (`MESSAGE`) | Événement |
|---|---|
| `Accepted <method> for <user> from <ip> port <port> ssh2[: <type> SHA256:<fp>]` | `accepted`, `method` ∈ publickey, password, keyboard-interactive ; `key_fingerprint` si présent |
| `Connection closed by authenticating user <user> <ip> port <port> [preauth]` | `refused`, `reason = key_rejected` (aucune clé offerte n'a été acceptée) |
| `Connection closed by invalid user <user> <ip> port <port> [preauth]` | `refused`, `reason = unknown_user` |
| `Failed password for [invalid user ]<user> from <ip> port <port> ssh2` | `refused`, `reason = bad_password`, `method = password` |
| `Disconnecting [invalid user \|authenticating user ]<user> <ip> port <port>: Too many authentication failures [preauth]` | `refused`, `reason = too_many_attempts` |

Ignorées en particulier : `Invalid user … from …` (la ligne « Connection closed by invalid user »
qui suit porte la même information), `pam_unix … session opened/closed`, `Received disconnect`,
`Disconnected from user …` (fin de session), et les sondes sans authentification (`banner exchange`,
`Connection closed by <ip> port <n> [preauth]` sans utilisateur, `Unable to negotiate`).

**Un refus par connexion.** Une connexion peut produire plusieurs lignes de refus (`Failed
password` puis `Connection closed by authenticating user`). L'agent garde en mémoire les couples
`(ip, port)` déjà signalés pendant 120 s et ne renvoie pas un second refus pour le même couple. Une
acceptation n'est jamais filtrée.

`username` est tronqué à 64 caractères, `ip` à 45 (IPv6), avant envoi.

### Empreinte → commentaire

Au démarrage et chaque fois que la date de modification d'`authorized_keys` change, l'agent lance
`ssh-keygen -lf <fichier>` et construit `{ "SHA256:…": "commentaire" }` (le `(TYPE)` final est
retiré ; un commentaire vide donne `None`). `make ssh-add` est donc pris en compte sans redémarrer
l'agent. Une empreinte inconnue (clé retirée entre-temps) donne `key_comment = None`, et le front
affiche l'empreinte.

### Envoi

`POST {SENTINEL_API_URL}/ssh/events`, JSON, en-tête `X-Device-Key`, délai 5 s, `urllib`.

```json
{
  "journal_id": "s=…;i=…;b=…;m=…;t=…;x=…",
  "occurred_at": "2026-10-08T07:37:35.412Z",
  "outcome": "accepted",
  "username": "sentinel-x",
  "ip": "192.168.0.18",
  "port": 49513,
  "method": "publickey",
  "key_fingerprint": "SHA256:WqjhHv1qunEjUzSVf2qHXic/DRMaR9XJT2Zc9NiH9ls",
  "key_comment": "claude-audit@mac-namania",
  "reason": null
}
```

- `201` (créé) ou `200` (déjà connu : même `journal_id`) → le curseur est écrit dans
  `ssh-log.cursor` (écriture atomique : fichier temporaire puis `rename`).
- Erreur réseau, `5xx`, `502/503` du nginx (API en redémarrage) → nouvel essai après 1, 2, 4, 8,
  16 puis 30 s, indéfiniment, **sans** avancer le curseur ; les événements suivants attendent
  (ordre conservé). Rien n'est perdu pendant un `make deploy`.
- `401/403` (clé appareil fausse) → journalisé en erreur, nouvel essai toutes les 60 s.
- `422` (ligne que l'API refuse) → journalisé en avertissement, événement abandonné, curseur avancé.

Journalisation de l'agent sur stderr (donc `journalctl --user -u sentinel-ssh-log`).

### Installation — `make ssh-log-install`

`scripts/ssh-log-install.sh` (sh POSIX, lancé depuis le dépôt sur le Pi) :

1. lit `DEVICE_API_KEY` dans `backend/.env` (erreur claire s'il manque) ;
2. écrit `~/.config/sentinel-x/ssh-log.env` (mode 600) : `DEVICE_API_KEY=…`,
   `SENTINEL_API_URL=http://127.0.0.1:8080/api` ;
3. écrit `~/.config/systemd/user/sentinel-ssh-log.service` :

```ini
[Unit]
Description=SENTINEL-X: journal des connexions SSH vers l'API
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 <dépôt>/scripts/ssh-log-agent.py
EnvironmentFile=%h/.config/sentinel-x/ssh-log.env
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

4. `systemctl --user daemon-reload && systemctl --user enable --now sentinel-ssh-log` ;
5. `loginctl enable-linger` (le service, et le Docker rootless, survivent à la déconnexion) ;
6. affiche l'état et la commande pour suivre les logs.

Makefile : `ssh-log-install`, `ssh-log-logs` (`journalctl --user -u sentinel-ssh-log -f`). Pour
retirer : `systemctl --user disable --now sentinel-ssh-log` (documenté, pas de cible).

## 2. API

### Domaine — `domain/ssh_event.py`

```python
Outcome = Literal["accepted", "refused"]
Reason = Literal["key_rejected", "unknown_user", "bad_password", "too_many_attempts"]

@dataclass(frozen=True, slots=True)
class SshEvent:
    id: UUID
    journal_id: str
    occurred_at: datetime
    outcome: Outcome
    username: str
    ip: str
    port: int
    method: str | None
    key_fingerprint: str | None
    key_comment: str | None
    reason: Reason | None

    @classmethod
    def create(cls, *, journal_id, occurred_at, outcome, username, ip, port, method=None,
               key_fingerprint=None, key_comment=None, reason=None) -> SshEvent   # id = uuid4()
```

Port `SshEventRepository` (dans `domain/repositories.py`, exposé par `UnitOfWork.ssh_events`) :

```python
async def add(self, event: SshEvent) -> bool          # False si journal_id existe déjà (rien écrit)
async def list(self, outcome: Literal["accepted", "refused", "all"], limit: int) -> list[SshEvent]
    # occurred_at décroissant
```

### Alerte `ssh` — `domain/alert.py`

- `Metric = Literal["temperature", "humidity", "gas", "ssh"]`. `METRICS` reste le tuple des
  **métriques capteurs** (bornes, `RecordReading`). Nouveau `ALERT_METRICS: tuple[Metric, ...] =
  (*METRICS, "ssh")` : ce que la sirène et les filtres connaissent.
- Une alerte `ssh` : `device_id = "ip:<ip>"`, `direction = "high"`, `threshold = 0.0`,
  `opened_value = 1.0`, `peak_value` = nombre de tentatives refusées depuis l'ouverture
  (`worsen(count)`), `resolved_value` = ce nombre au moment de la fermeture.
- `GET /alerts?device_id=` : le motif accepté devient `^[a-z0-9.:-]{1,64}$` (points et deux-points
  des IP).

### Service — `application/ssh/record.py`

```python
@dataclass(frozen=True, slots=True)
class SshEventInput: ...   # les champs du JSON reçu, occurred_at déjà en UTC

class RecordSshEvent:
    def __init__(self, uow_factory, broadcaster, on_alerts_changed=None,
                 quiet_minutes: int = 10, clock=utc_now, sleep=asyncio.sleep) -> None
    async def start(self) -> None     # relit les alertes ssh ouvertes (redémarrage) et arme la minuterie
    async def record(self, data: SshEventInput) -> tuple[SshEvent, bool]   # (événement, créé ?)
    def close(self) -> None           # annule la minuterie
```

`record`, dans une seule transaction :

1. `uow.ssh_events.add(event)` ; si `False` (doublon) → `commit`, renvoie `(event, False)`, ni
   diffusion ni alerte (l'agent rejoue après une coupure).
2. Si `outcome == "refused"` : alerte ouverte pour `ip:<ip>` / `ssh` ?
   - aucune → `Alert.open(...)` avec `at = occurred_at`, `value = 1.0` → `alert.opened` ;
   - déjà ouverte → `worsen(peak + 1)` → `save` → événement **`alert.updated`** (nouveau type,
     même corps que `alert.opened`).
   Dans les deux cas la dernière tentative de l'IP est mémorisée (`_last_attempt[ip] =
   occurred_at`, plafonné à `now` si l'horodatage est dans le futur).
3. `commit`, puis diffusion WebSocket : `ssh.event` (toujours, si créé), puis l'événement
   d'alerte éventuel, puis `on_alerts_changed` (la sirène) si une alerte s'est ouverte.

**Résolution après calme.** Une tâche de fond unique dort jusqu'à la plus proche échéance
`dernière tentative + quiet_minutes` ; à l'échéance elle résout chaque alerte `ssh` ouverte dont
l'IP est restée calme (`resolve(at=now, value=peak)`, `alert.resolved`, puis `on_alerts_changed`),
et se réarme sur la suivante. Chaque `record` d'un refus réarme la tâche (comme la reprise de la
sirène). Au démarrage, `start()` charge les alertes `ssh` ouvertes en base et considère leur
dernière tentative comme `now` : dix minutes après un redémarrage de l'API, une IP silencieuse est
résolue. Une erreur dans la tâche est journalisée et la tâche se réarme : jamais d'alerte bloquée
ouverte à cause d'une exception.

Réglage : `ssh_alert_quiet_minutes: int = Field(default=10, ge=1, le=1440)` (`SSH_ALERT_QUIET_MINUTES`).

### Sirène

`parse_triggers` accepte toute métrique d'`ALERT_METRICS` ; `REASON_ORDER = ("gas", "ssh",
"temperature", "humidity")`. `buzzer_triggers` garde son défaut `gas,temperature:high` : ajouter
`ssh` pour que le buzzer sonne sur une tentative refusée. Le front : `REASONS.ssh = "SSH"`.

### Routes — `presentation/http/ssh.py`, préfixe `/ssh`

- `POST /ssh/events` — `DeviceKeyDep`. Corps : le JSON de l'agent, validé par Pydantic
  (`journal_id` 1-255, `username` 1-64, `ip` 1-45, `port` 1-65535, `outcome`, `reason` et
  `method` ≤ 32 ; `reason` obligatoire si `refused`, interdit si `accepted`). `occurred_at`
  plausible comme pour les mesures (pas plus de 5 min dans le futur, pas plus de 30 jours ;
  sinon heure serveur). Réponse `201` ou `200` (doublon) avec `SshEventResponse`.
- `GET /ssh/events?outcome=all|accepted|refused&limit=1..500` (défaut 100) — JWT. Plus récent
  d'abord.

`SshEventResponse` : les champs de `SshEvent`, `id` en chaîne, dates en `…Z`. Même corps pour
l'événement WebSocket `{"type": "ssh.event", "data": …}`.

### Persistance

Modèle `SshEventModel` (table `ssh_events`) et `SqlAlchemySshEventRepository` (`add` fait un
`SELECT 1 … WHERE journal_id = …` puis `INSERT` ; l'index unique garantit le reste). Migration
`0006_create_ssh_events` :

| colonne | type |
|---|---|
| `id` | uuid, clé primaire |
| `journal_id` | varchar(255), index unique `uq_ssh_events_journal_id` |
| `occurred_at` | timestamptz, index `ix_ssh_events_occurred_at` |
| `outcome` | varchar(8) |
| `username` | varchar(64) |
| `ip` | varchar(45) |
| `port` | integer |
| `method` | varchar(32), nullable |
| `key_fingerprint` | varchar(64), nullable |
| `key_comment` | varchar(255), nullable |
| `reason` | varchar(32), nullable |

### Branchement (`main.py`)

`app.state.ssh_access = RecordSshEvent(uow_factory, app.state.hub, on_alerts_changed=
app.state.siren.refresh, quiet_minutes=settings.ssh_alert_quiet_minutes)` ; `start()` dans le
lifespan après l'annonce de la sirène, `close()` à l'arrêt. Dépendance `SshAccessDep`.

## 3. Front

### Page « Accès SSH » — `features/ssh/`

- `ssh-api.ts` : types `SshEvent`, `Outcome`, `Reason` ; `SSH_EVENTS_PATH = "/ssh/events"`,
  `SSH_LIMIT = 500`, `sshEventsPath(limit)` ; `REASON_LABELS` (`key_rejected` → « clé non
  acceptée », `unknown_user` → « utilisateur inconnu », `bad_password` → « mot de passe
  refusé », `too_many_attempts` → « trop de tentatives ») ; `METHOD_LABELS` (`publickey` → « clé »,
  `password` → « mot de passe », `keyboard-interactive` → « interactif ») ; `identityLabel(e)` →
  commentaire de clé, sinon empreinte raccourcie (`SHA256:Wqjh…9ls`), sinon utilisateur ;
  `describeEvent(e)` → « mael.namania@gmail.com depuis 192.168.0.18 · clé » / « root depuis
  203.0.113.5 · clé non acceptée » ; `prepend(events, e)` (dédoublonne par `id`, trie par
  `occurred_at` décroissant, coupe à 500) ; `summarizeSsh(events, nowMs)` → `{ accepted24h,
  refused24h, lastAccepted: SshEvent | null }`.
- `use-ssh-events.ts` : même schéma que `useAlerts` (chargement, événements `ssh.event` en
  attente avant la réponse, resynchronisation après reconnexion, récupération après un échec).
- `ssh-event-row.tsx` : une ligne — pictogramme `Check` vert (acceptée) ou `X` rouge (refusée)
  sur disque, heure, `describeEvent`, utilisateur système en petit (`sentinel-x`), port en
  `title`.
- `ssh-page-content.tsx` : titre « Accès SSH » ; trois `Stat` (« Connexions 24 h », « Refus
  24 h » avec indice « ouvrent une alerte SSH », « Dernière acceptée » : identité et « il y a
  4 min ») ; filtre `ToggleGroup` toutes / acceptées / refusées ; champ de recherche (IP, mail,
  utilisateur, sous-chaîne insensible à la casse) ; liste groupée par jour avec `groupByDay` et
  `dayLabel` **déplacés** de `alerts-api.ts` vers `lib/day-groups.ts` (génériques sur
  `opened_at` → paramètre `at: (item) => string`), réexportés par `alerts-api.ts` pour ne pas
  casser les imports ; états chargement / erreur (« Journal SSH indisponible. ») / vide
  (« Aucune connexion ») ; mention « Seules les 500 connexions les plus récentes sont
  affichées. » au plafond.
- `pages/ssh.tsx`, route `/ssh` dans `app/router.tsx`, entrée de sidebar `{ to: "/ssh", label:
  "Accès SSH", icon: KeyRound }` après « Alertes », sans badge (le badge Alertes compte déjà
  les alertes `ssh` ouvertes).

### Métrique `ssh` dans les alertes

- `Metric` ajoute `"ssh"` ; `METRIC_LABELS.ssh = "SSH"`, `UNITS.ssh = ""`, `DIGITS.ssh = 0`,
  `METRIC_COLORS.ssh = "var(--metric-ssh)"` avec `--metric-ssh: #7c3aed` (clair) / `#a78bfa`
  (sombre) dans `index.css` ; icône `KeyRound` dans `metric-icon.tsx`.
- `ipFromDevice(alert)` : `ip:203.0.113.5` → `203.0.113.5`. `attemptsLabel(n)` : « 1 tentative »,
  « 3 tentatives ».
- `valueAgainstBound` : « 3 tentatives refusées depuis 203.0.113.5 » ; `describeAlert` : « SSH :
  3 tentatives refusées depuis 203.0.113.5 » ; `peakLabel` : « 3 tentatives » ; `boundLabel` et
  `excessLabel` : `null` ; `AlertTile` sans borne : « tentatives de connexion refusées » pour `ssh`,
  « alerte signalée par l'ESP » sinon. `summarize` compte `ssh` ; le filtre de `/alertes` propose
  « SSH ».
- `useAlerts` traite `alert.updated` comme `alert.opened` (upsert) ; `useAlertCount` l'ignore.

## 4. Tests

Agent (`backend/tests/unit/test_ssh_log_agent.py`, qui charge `scripts/ssh-log-agent.py` par
`importlib` depuis la racine du dépôt ; le script n'importe rien de l'API) :
- analyse de chaque ligne du tableau ci-dessus avec des lignes réelles du Pi, et les lignes
  ignorées → `None` ;
- un `Failed password` puis un `Connection closed by authenticating user` pour le même
  `(ip, port)` → un seul refus ; deux IP différentes → deux ;
- croisement : sortie réelle de `ssh-keygen -lf` (deux clés, l'une avec commentaire mail, options
  `no-port-forwarding…` devant) → dictionnaire attendu ; empreinte inconnue → `None` ; rechargement
  quand le mtime change (fake) ;
- envoi : fake HTTP ; `201`/`200` avancent le curseur ; erreur réseau → nouvel essai avec
  attentes 1, 2, 4… et curseur inchangé ; `422` → abandon et curseur avancé ; `401` → essai
  toutes les 60 s ;
- première exécution sans curseur → `--since -24h` ; avec curseur → `--after-cursor`.

Backend :
- `tests/unit/test_ssh_event_domain.py` : `create` (identifiant généré, champs optionnels à
  `None`) ;
- `tests/unit/test_record_ssh_event.py` (fakes en mémoire, horloge et `sleep` factices) :
  acceptée → stockée, `ssh.event`, aucune alerte ; refus → alerte ouverte `ip:<ip>` valeur 1,
  `alert.opened`, hook sirène appelé ; second refus même IP → `peak 2`, `alert.updated`, hook non
  appelé ; refus d'une autre IP → seconde alerte ; après `quiet_minutes` sans refus → résolue avec
  `resolved_value = peak`, `alert.resolved`, hook appelé ; un refus à T+9 min repousse la
  résolution à T+19 ; doublon `journal_id` → `(event, False)`, rien diffusé ; `start()` avec une
  alerte `ssh` ouverte en base → résolue `quiet_minutes` plus tard ; exception du hook → journalisée,
  l'événement est quand même stocké ;
- `tests/unit/test_siren_domain.py` : `parse_triggers("ssh")` accepté, `REASON_ORDER` place `ssh`
  avant `temperature` ; `tests/unit/test_settings.py` : `SSH_ALERT_QUIET_MINUTES` défaut 10 et
  bornes ;
- `tests/integration/test_ssh_http.py` : `POST` sans clé → 401 ; corps invalide (`refused` sans
  `reason`, `port` 70000) → 422 ; `POST` acceptée → 201 et `GET /ssh/events` la renvoie ;
  re-`POST` → 200 et une seule ligne ; `POST` refusée → `GET /alerts?status=open` contient une
  alerte `ssh` `ip:…` ; `GET /ssh/events?outcome=refused` filtre ; `GET` sans JWT → 401 ;
  événements `ssh.event` et `alert.opened` reçus sur `/ws` ;
- `tests/integration/test_ssh_event_repository.py` : `add` deux fois le même `journal_id` →
  `True` puis `False`, une ligne ; `list` trié, filtré, limité.

Frontend :
- `ssh-api.test.ts` : `describeEvent` pour les deux issues et chaque raison, `identityLabel` sans
  commentaire (empreinte raccourcie), `prepend` (ordre, doublon, plafond), `summarizeSsh` ;
- `use-ssh-events.test.tsx` : chargement, `ssh.event` en direct, événement arrivé avant la liste,
  récupération après échec ;
- `ssh-page-content.test.tsx` : stats, filtres, recherche, états vide / erreur / plafond ;
- `alerts-api.test.ts` : `describeAlert`, `peakLabel`, `boundLabel`, `excessLabel` pour `ssh` ;
  `use-alerts.test.tsx` : `alert.updated` met à jour le pic sans ajouter de ligne ;
  `app-sidebar` / `router.test.tsx` : l'entrée « Accès SSH » mène à `/ssh` ;
- `lib/day-groups.test.ts` : `groupByDay` générique (les tests existants d'`alerts-api` restent
  verts via la réexportation).

## 5. README

Section « Accès SSH au Pi » : un paragraphe « **Journal des connexions.** » — `make
ssh-log-install` sur le Pi (agent hôte, service utilisateur `sentinel-ssh-log`, linger), ce qui est
reconnu, où le voir (`/ssh`), l'alerte `ssh` par IP résolue après `SSH_ALERT_QUIET_MINUTES`
(10), `ssh` à ajouter à `BUZZER_TRIGGERS` pour le buzzer, `make ssh-log-logs`, et comment
retirer le service. Section « Alertes » : mention de la métrique `ssh` et de l'événement
`alert.updated`. `.env.example` : `SSH_ALERT_QUIET_MINUTES=10`.
