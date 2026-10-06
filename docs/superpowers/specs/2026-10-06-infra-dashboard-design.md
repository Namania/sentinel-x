# Dashboard écran infra : santé serveur, carte caméra, sidebar repliée — design

Date : 2026-10-06
Statut : validé, à implémenter

## Objectif

Faire du Dashboard (`/`) un écran mural pour l'équipe infra : tout est visible d'un coup d'œil,
et chaque bloc est cliquable pour aller au détail.

- La sidebar est repliée par défaut (icônes seules) pour laisser la place au contenu.
- Une carte caméra montre le flux en direct ; un clic mène à la page Caméra.
- Une carte santé du serveur (le Raspberry Pi 5 qui héberge l'API, PostgreSQL et Mosquitto)
  montre CPU, RAM, disque, température du SoC, charge et uptime, rafraîchis en temps réel ;
  un clic mène à une page `/serveur` qui montre les mêmes séries en grand.
- La section capteurs existante reste en dessous, inchangée.

Le serveur est un hôte Linux ; les métriques sont lues depuis `/proc` et `/sys` par l'API, qui
tourne dans Docker. Pas d'exporter, pas d'agent sur l'hôte, rien en base de données.

## Hors scope

- État des services (API, PostgreSQL, Mosquitto joignables, ESP en ligne / hors ligne).
- Débit réseau, latence vers la caméra.
- Historique persistant de la santé serveur (un tampon mémoire de 30 min suffit ; un
  redémarrage de l'API le vide).
- Mode kiosque, connexion automatique de l'écran mural (il utilise un compte normal).
- Seuils d'alerte serveur configurables (les seuils d'affichage sont fixes, voir « Couleurs »).

## Backend

### Échantillon (`application/server/health.py`)

```python
@dataclass(frozen=True, slots=True)
class ServerHealth:
    recorded_at: datetime        # UTC
    cpu_pct: float | None        # None sur le premier échantillon (pas de delta)
    mem_total_bytes: int
    mem_used_bytes: int          # MemTotal - MemAvailable
    disk_total_bytes: int
    disk_used_bytes: int         # (f_blocks - f_bfree) * f_frsize
    temperature_c: float | None  # None si la zone thermique n'existe pas
    load_1: float
    load_5: float
    load_15: float
    uptime_s: int
```

`to_dict(sample)` donne la forme JSON (clés identiques, `recorded_at` ISO 8601 en `Z`, comme les
événements capteurs). `to_event(sample)` donne `{"type": "server.health", "data": to_dict(sample)}`.

`HealthHistory(maxlen=360)` : tampon circulaire (`collections.deque`). `append(sample)`,
`latest() -> ServerHealth | None`, `points() -> list[ServerHealth]` du plus ancien au plus récent.
360 points × 5 s = 30 min.

### Lecteur (`infrastructure/system/procfs.py`)

```python
class ProcfsSampler:
    def __init__(self, proc: Path, thermal: Path, disk: Path, clock=datetime.now) -> None: ...
    def sample(self) -> ServerHealth: ...
```

- CPU : `/proc/stat` première ligne `cpu  user nice system idle iowait irq softirq steal …`.
  `total = somme des champs`, `idle = idle + iowait`. `cpu_pct = 100 × (1 − Δidle / Δtotal)`
  entre deux appels de `sample()` ; le premier appel renvoie `None`. `Δtotal == 0` → `None`.
  Résultat borné dans [0, 100].
- Mémoire : `/proc/meminfo`, lignes `MemTotal:` et `MemAvailable:` en kB (× 1024).
- Charge : `/proc/loadavg`, trois premiers nombres.
- Uptime : `/proc/uptime`, premier nombre, arrondi à l'entier.
- Température : `<thermal>/thermal_zone0/temp`, millidegrés ÷ 1000. Fichier absent ou
  illisible → `None`. Sur le Pi 5 c'est la température du SoC (`cpu-thermal`).
- Disque : `os.statvfs(disk)`.
- Un fichier `/proc` absent ou mal formé lève `SamplingError` (sous-classe de `RuntimeError`) ;
  le moniteur la journalise et réessaie au prochain tick, sans tuer la tâche.

Le lecteur est purement synchrone et ne lit que des fichiers : les tests lui donnent un
`tmp_path` avec des fixtures écrites à la main et vérifient chaque champ.

### Moniteur (`infrastructure/system/monitor.py`)

```python
class ServerHealthMonitor:
    def __init__(self, sampler, history, broadcaster, interval: float = 5.0, sleep=asyncio.sleep): ...
    async def run(self) -> None: ...
```

Boucle : `sample()` dans `asyncio.to_thread` (les lectures `/proc` sont rapides mais `statvfs`
sur un disque qui patine peut bloquer), `history.append`, `broadcaster.broadcast(to_event(...))`,
`sleep(interval)`. `SamplingError` → `log.warning` et on continue. `CancelledError` → sortie
propre. Un échantillon est pris immédiatement au démarrage pour que `/server/health` ait une
valeur dès que l'API répond ; le second arrive 5 s plus tard avec le premier `cpu_pct`.

Démarré dans le `lifespan` de `main.py` à côté du souscripteur MQTT, annulé à l'arrêt.
`app.state.server_health = history`.

### Configuration (`infrastructure/config.py`)

```python
host_proc_path: Path = Path("/proc")
host_thermal_path: Path = Path("/sys/class/thermal")
host_disk_path: Path = Path("/")
server_health_interval_s: float = 5.0
```

Dans un conteneur Docker, `/proc/stat`, `/proc/meminfo`, `/proc/loadavg` et `/proc/uptime`
montrent déjà l'hôte (pas de lxcfs). Il faut monter l'hôte pour la température et le disque :

```yaml
# compose.yml, service api
volumes:
  - /sys/class/thermal:/host/thermal:ro
  - /:/host/root:ro
environment:
  HOST_THERMAL_PATH: /host/thermal
  HOST_DISK_PATH: /host/root
```

Sous Docker Desktop (Mac), `/host/thermal/thermal_zone0` n'existe pas → température `None`, le
front affiche « – » ; `/host/root` est le disque de la VM Linux, ce qui est acceptable en dev.
`compose.dev.yml` n'a rien à changer.

### Route (`presentation/http/server.py`)

`GET /server/health` (JWT requis, même dépendance que `/sensors/*`) :

```json
{
  "latest": { "recorded_at": "2026-10-06T09:00:05Z", "cpu_pct": 12.5, "mem_total_bytes": 8589934592,
              "mem_used_bytes": 2147483648, "disk_total_bytes": 62000000000,
              "disk_used_bytes": 21000000000, "temperature_c": 48.2,
              "load_1": 0.42, "load_5": 0.38, "load_15": 0.31, "uptime_s": 86400 },
  "history": [ { "...": "même forme, du plus ancien au plus récent" } ]
}
```

`latest` est `null` et `history` vide tant qu'aucun échantillon n'a abouti. Le tag OpenAPI est
`server`.

### WebSocket

Nouvel événement sur le canal `/ws` existant, diffusé à tous les clients connectés toutes les 5 s :

```json
{ "type": "server.health", "data": { "...": "même forme que latest" } }
```

## Frontend

### Sidebar repliée par défaut

`app-shell.tsx` : `<SidebarProvider defaultOpen={false}>`. Le `SidebarProvider` généré n'initialise
pas son état depuis le cookie `sidebar_state`, il ne fait que l'écrire : au chargement la sidebar
est donc toujours repliée, l'utilisateur peut l'ouvrir pendant sa session. La nav gagne une entrée
« Serveur » (`Server` de lucide, `to: "/serveur"`). Le titre « S » seul en mode replié est déjà en
place.

### Flux temps réel partagé (`features/realtime/use-event-stream.ts`)

`useSensorStream` devient une spécialisation d'un hook générique :

```ts
export function useEventStream(enabled: boolean, onEvent: (type: string, data: unknown) => void): { connected: boolean }
```

Même URL (`/ws?token=`), mêmes délais de reconnexion (1 → 30 s), même réouverture au changement
de jeton. `useSensorStream(enabled, onReading)` filtre `sensor.reading` ; `useServerHealth`
filtre `server.health`. Deux hooks montés = deux sockets. C'est accepté : le hub supporte des
dizaines de connexions, et un seul socket partagé demanderait un provider que rien d'autre ne
justifie aujourd'hui.

### Santé serveur (`features/server/`)

- `server-api.ts` : type `ServerHealth` (miroir du JSON), `SERVER_HEALTH_PATH = "/server/health"`,
  `type ServerHealthResponse = { latest: ServerHealth | null; history: ServerHealth[] }`,
  `appendHealth(history, sample, maxlen = 360)`, `pct(used, total)`, `formatBytes(n)` (Gio avec
  une décimale), `formatUptime(s)` (« 3 j 4 h », « 4 h 12 min », « 12 min »).
- `use-server-health.ts` : charge `/server/health` au montage puis applique les événements
  `server.health`. Retourne `{ status: "loading" | "ready" | "error", latest, history, connected }`.
  Un événement reçu pendant le chargement est gardé et fusionné après la réponse HTTP (même
  règle que les lectures capteurs). Les événements dont `recorded_at` est antérieur ou égal au
  dernier point sont ignorés.
- `health-gauge.tsx` : jauge compacte réutilisée quatre fois dans la carte : libellé, valeur
  (« 12 % », « 2,0 / 8,0 Gio », « 48 °C »), barre de progression horizontale, sparkline de la
  série sur 30 min (Recharts `AreaChart`, `isAnimationActive={false}`, sans axes). `role="group"`
  avec `aria-label` égal au libellé ; la valeur est du texte lisible.
- `server-health-card.tsx` : `Card` enveloppée dans un `Link to="/serveur"` (`aria-label="Santé
  du serveur, voir le détail"`). Entête « Serveur » avec un point vert si `connected`, gris sinon
  (texte alternatif « temps réel actif / interrompu »). Quatre jauges : CPU, Mémoire, Disque,
  Température. Pied : « Charge 0,42 · 0,38 · 0,31 » et « Démarré depuis 3 j 4 h ». État
  `loading` → `Skeleton` ; `error` → texte « Santé du serveur indisponible » dans la carte, le
  lien reste actif. `latest === null` → valeurs « – ».
- `server-charts.tsx` : trois graphiques pleine largeur sur l'historique : CPU % (0 → 100),
  mémoire utilisée en Gio (0 → total), température °C ; plus la jauge disque et la ligne
  charge / uptime. Même composants `ChartContainer` que les capteurs, tooltip avec l'heure.

Page `/serveur` (`pages/server.tsx`) : titre « Serveur », `ServerCharts`. Titre de document
« Serveur · sentinel-x ». Ajoutée au routeur dans la zone authentifiée et au dictionnaire
`TITLES` du shell.

### Caméra : flux réutilisable

`features/camera/camera-stream.tsx` extrait de `CameraView` tout ce qui concerne le flux :
vérification `/camera/status`, ouverture de `<img src=…/camera/stream?token=…>`, reconnexion
après 2 s, états `checking | unconfigured | connecting | live`. Il expose :

```ts
export function CameraStream({ onStateChange, className }: Props): JSX.Element
```

L'image remplit son conteneur (`object-contain` sur fond noir). L'état « unconfigured » rend un
court texte « Aucune caméra configurée » (sans le paragraphe sur `CAMERA_STREAM_URL`, qui reste
dans `CameraView`). `CameraView` garde plein écran, raccourci « f », masquage au repos, badge et
compteur de spectateurs, et utilise `CameraStream` pour l'image. Son comportement observable ne
change pas : ses tests existants restent verts.

`features/camera/camera-card.tsx` : `Link to="/camera"` (`aria-label="Caméra, voir en grand"`)
contenant une `Card` avec entête « Caméra », un cadre 16:9 avec `CameraStream`, et le badge
« EN DIRECT » quand l'état est `live`. Aucun bouton à l'intérieur (un lien ne contient pas de
contrôle). Le flux reste ouvert tant que le Dashboard est affiché : le relais fait du fan-out,
l'ESP n'a toujours qu'un seul client.

### Disposition du Dashboard (`pages/dashboard.tsx`)

```
┌──────────────────────────────────────┬──────────────────┐
│ Caméra (2 colonnes, 16:9)            │ Serveur          │
│                                      │ CPU  ▂▃▅▂▁       │
│                                      │ RAM  ▁▁▂▂▂       │
│                                      │ Disque           │
│                                      │ Temp ▂▂▃▃▂       │
│                              EN DIRECT│ Charge · Uptime  │
├──────────────────────────────────────┴──────────────────┤
│ Section capteurs existante (tuiles, filtres, graphiques) │
└──────────────────────────────────────────────────────────┘
```

Grille `grid gap-4 lg:grid-cols-3`, caméra `lg:col-span-2`. Sous `lg` tout s'empile : caméra,
serveur, capteurs. La carte serveur a la même hauteur que la caméra sur grand écran
(`items-stretch`). Le titre `h1` « Dashboard » existant reste en tête.

### Couleurs

Les jauges utilisent la teinte du thème (`--chart-1`, teal) ; la barre passe en `--destructive`
au-delà de 85 % pour CPU, mémoire et disque, et au-delà de 70 °C pour la température. Les seuils sont des constantes dans `server-api.ts`. La
couleur n'est jamais la seule indication : la valeur chiffrée est toujours affichée. Les trois
graphiques de `/serveur` sont monochromes (une série chacun), pas de légende.

## Tests

Backend (pytest, `tests/unit/`) :

- `test_procfs_sampler.py` : fixtures `/proc` écrites dans `tmp_path` ; chaque champ vérifié ;
  premier `sample()` → `cpu_pct is None`, second → valeur calculée sur le delta ; zone thermique
  absente → `None` ; `meminfo` tronqué → `SamplingError`.
- `test_server_health_monitor.py` : sommeil factice qui enregistre les délais (comme le
  souscripteur MQTT) ; deux ticks → deux événements `server.health` diffusés et deux points dans
  l'historique ; un `SamplingError` au premier tick n'arrête pas la boucle ; annulation propre.
- `test_health_history.py` : `maxlen` respecté, ordre chronologique.
- `test_server_routes.py` (intégration, app de test) : 401 sans jeton ; `latest: null` et
  `history: []` avant le premier échantillon ; forme JSON après un `append`.

Frontend (Vitest + MSW) :

- `server-api.test.ts` : `appendHealth` borne et ignore les doublons, `formatBytes`,
  `formatUptime`, `pct`.
- `use-server-health.test.tsx` : charge puis applique un événement WS ; événement reçu pendant le
  chargement fusionné après ; erreur HTTP → `status: "error"`.
- `server-health-card.test.tsx` : squelette puis valeurs ; lien vers `/serveur` ; couleur de
  seuil non testée, le texte l'est (« 92 % »).
- `camera-card.test.tsx` : lien vers `/camera`, badge « EN DIRECT » après `load` de l'image.
- `camera-view.test.tsx` : inchangé et vert après l'extraction.
- `app-shell.test.tsx` (ou `app-sidebar.test.tsx`) : sidebar repliée au premier rendu
  (`data-state="collapsed"`), entrée « Serveur » présente.
- `dashboard.test.tsx` : les trois blocs rendus, un clic sur la carte caméra navigue vers
  `/camera`.

## README

Section « Dashboard » : décrire l'écran mural, la carte serveur et ses sources (`/proc`, `/sys`),
les montages Docker requis et le fait que la température est absente sous Docker Desktop.
