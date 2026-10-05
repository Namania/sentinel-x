# Front-end React + shadcn/ui — design

Date : 2026-10-05
Statut : en attente de relecture

## Objectif

Donner à sentinel-x un front web servi par le nginx existant, à côté de l'API, avec :

- un socle Vite + React + TypeScript + Tailwind v4 + shadcn/ui, pnpm ;
- une page 404, une bascule de thème clair / sombre / système ;
- une page de connexion branchée sur `/api/auth/login` et `/api/auth/refresh`, avec session
  restaurée au rechargement et routes protégées ;
- une vue caméra qui affiche le flux MJPEG relayé par `/api/camera/stream` ;
- une image Docker multi-étapes et une CI GitHub Actions (backend + front + build des images).

Spec backend de référence : `2026-10-05-backend-fastapi-design.md`. Le relais caméra est livré
sur la branche `feat/camera-relay` (endpoint `GET /camera/stream`, auth Bearer ou `?token=`).

## Hors scope (volontairement)

- Commande du servo, capture photo, enregistrement.
- Inscription, mot de passe oublié, gestion de profil.
- i18n : l'interface est en français, textes en dur.
- PWA / mode hors-ligne.
- Déploiement automatique sur le Raspberry Pi (la CI construit, elle ne déploie pas).
- Tests end-to-end navigateur (Playwright) : tests unitaires et de composants seulement.

## Stack

| Rôle | Choix |
|---|---|
| Build | Vite 7, TypeScript 5 strict |
| UI | React 19, Tailwind v4 (`@tailwindcss/vite`), shadcn/ui (style `new-york`, base `neutral`, variables CSS), lucide-react |
| Routage | React Router 7, mode librairie (`createBrowserRouter`, `RouterProvider`) |
| Formulaires | react-hook-form + zod, composant `Form` de shadcn |
| HTTP | `fetch` natif, petit client dans `src/lib/api.ts` |
| Tests | Vitest, jsdom, Testing Library, MSW (mock HTTP), `@testing-library/user-event` |
| Qualité | ESLint (config du template Vite) + Prettier ; `tsc -b` en `typecheck` |
| Paquets | pnpm 12, `pnpm install --frozen-lockfile` en CI et Docker |
| Prod | Image `node:24-alpine` (build) → `nginx:alpine` (serve) |

Choix pnpm : déjà installé, store partagé (utile si l'image est construite sur le Pi), lockfile
strict comparable à `uv sync --frozen` côté backend.

## Arborescence

```
frontend/
  package.json  pnpm-lock.yaml  vite.config.ts  vitest.config.ts
  tsconfig.json  tsconfig.app.json  tsconfig.node.json
  components.json            # config shadcn
  eslint.config.js  .prettierrc  .prettierignore
  index.html  Dockerfile  .dockerignore
  src/
    main.tsx                 # StrictMode > ThemeProvider > AuthProvider > RouterProvider
    index.css                # @import "tailwindcss", variables shadcn, @custom-variant dark
    vite-env.d.ts
    app/
      router.tsx             # définition des routes
      root-layout.tsx        # <AppHeader/> + <Outlet/>, fond et hauteur plein écran
      require-auth.tsx       # route layout : redirige vers /login si non connecté
    components/
      app-header.tsx         # titre SENTINEL-X, ThemeToggle, bouton Déconnexion si connecté
      ui/                    # composants shadcn ajoutés par la CLI (button, card, input, label,
                             # form, dropdown-menu, alert, badge, skeleton)
    features/
      theme/theme-provider.tsx   # contexte thème + persistance localStorage
      theme/theme-toggle.tsx     # DropdownMenu Clair / Sombre / Système
      auth/auth-provider.tsx     # contexte session (accessToken, user, login, logout)
      auth/token-storage.ts      # lecture/écriture du refresh token (localStorage)
      auth/jwt.ts                # lecture de `exp` dans un JWT (base64url, sans lib)
      auth/auth-api.ts           # login(), refresh(), me()
      camera/camera-view.tsx     # <img> MJPEG, overlay, plein écran, reconnexion
      camera/camera-api.ts       # status()
    pages/
      login.tsx  camera.tsx  not-found.tsx
    lib/
      api.ts                 # apiFetch(path, init, { token }) : base "/api", erreurs typées
      utils.ts               # cn() généré par shadcn
    test/
      setup.ts               # jest-dom, MSW server lifecycle, matchMedia/localStorage stubs
      server.ts              # handlers MSW par défaut (login, refresh, me, camera/status)
      render.tsx             # renderWithProviders(ui, { route, session })
```

Alias `@/` → `src/`. Les composants shadcn ne sont jamais modifiés à la main hors `ui/` ; les
spécificités projet vivent dans `components/` et `features/`.

## Routage

| Chemin | Accès | Rendu |
|---|---|---|
| `/login` | public ; redirige vers `/` si déjà connecté | `LoginPage` |
| `/` | protégé (`RequireAuth`) | `CameraPage` (vue caméra, c'est l'accueil) |
| `*` | public | `NotFoundPage` |

Toutes les routes sont enfants de `RootLayout`. `RequireAuth` est une route layout
intermédiaire : pendant la restauration de session elle affiche un `Skeleton` plein écran ;
non connecté → `<Navigate to="/login" state={{ from }} replace />` ; connecté → `<Outlet />`.

### Page 404

Grand « 404 », titre « Cette page n'existe pas », texte « L'adresse demandée ne correspond à
aucune page de sentinel-x. », `Button` shadcn « Retour à l'accueil » (lien vers `/`). Centrée,
responsive. Le `<title>` du document devient « 404 · sentinel-x ».

## Thème

- `ThemeProvider` : état `theme ∈ {"light","dark","system"}`, défaut `"dark"`, persisté dans
  `localStorage["sentinel-x-theme"]`. Applique la classe `dark` ou `light` sur
  `document.documentElement` ; en mode `system`, suit `matchMedia("(prefers-color-scheme: dark)")`
  et réagit à ses changements.
- `index.css` : `@custom-variant dark (&:is(.dark *));` et les variables shadcn `:root` / `.dark`.
- `ThemeToggle` : `DropdownMenu` avec icônes Soleil / Lune, trois entrées, entrée courante cochée.
- Un script inline dans `index.html` applique la classe avant le premier rendu pour éviter le
  flash de thème clair.

## Authentification

### Stockage des jetons

- Access token (15 min) : en mémoire uniquement, dans le contexte React.
- Refresh token (7 jours) : `localStorage["sentinel-x-refresh"]`. C'est un compromis assumé :
  l'application vit sur un LAN, le backend ne pose pas de cookie, et le flux `<img>` impose de
  pouvoir obtenir un access token côté client. Le refresh token est effacé à la déconnexion et
  dès qu'un rafraîchissement échoue.

### Cycle de session (`AuthProvider`)

1. **Démarrage** : `status = "restoring"`. S'il existe un refresh token → `POST /api/auth/refresh`
   puis `GET /api/users/me`. Succès → `status = "authenticated"`, nouvelle paire stockée.
   Échec (401, réseau) → refresh token effacé, `status = "anonymous"`. Pas de refresh token →
   `"anonymous"` directement.
2. **login(email, password)** : `POST /api/auth/login`. 401 → erreur « Email ou mot de passe
   incorrect ». Erreur réseau → « Serveur injoignable ». Succès → paire stockée, `me()` chargé.
3. **Rafraîchissement proactif** : un timer relance `refresh()` 60 s avant `exp` de l'access
   token (lu dans le JWT). Il remplace l'access token sans toucher aux composants montés : le
   flux `<img>` déjà ouvert continue, seule une future reconnexion utilisera le nouveau jeton.
4. **Réponse 401 sur un appel API** : `apiFetch` tente un `refresh()` une fois puis rejoue la
   requête ; si le refresh échoue → `logout()`.
5. **logout()** : efface mémoire et localStorage, `status = "anonymous"`, le routeur renvoie
   vers `/login`.

Le contexte expose `{ status, user, accessToken, login, logout }`.

### Page de connexion

`Card` centrée : titre « Connexion », champs Email et Mot de passe (`Form` + zod : email valide,
mot de passe non vide), bouton « Se connecter » désactivé pendant l'envoi, `Alert` destructive
pour l'erreur. Après succès : navigation vers `state.from` ou `/`. `<title>` :
« Connexion · sentinel-x ».

## Vue caméra

### Backend : `GET /camera/status` (ajout à `feat/camera-relay`)

Authentifié (Bearer ou `?token=`), renvoie `{ "configured": bool, "viewers": int }`. Permet au
front de distinguer « pas de caméra configurée » (une balise `<img>` ne voit pas un 503) et
d'afficher le nombre de spectateurs. Couvert par des tests d'intégration côté backend.

### Composant `CameraView`

- Au montage : `camera-api.status()`. `configured: false` → écran « Aucune caméra configurée.
  Renseigne `CAMERA_STREAM_URL` dans `backend/.env`. » Sinon rendu du flux.
- Flux : `<img src="/api/camera/stream?token=<accessToken>&t=<Date.now()>">`, `object-fit:
  contain`, fond noir, plein écran disponible (bouton + double-clic + touche F), barres
  d'informations qui se masquent après 2,5 s d'inactivité (reprise de la page embarquée de
  l'ESP32). Badge « EN DIRECT » rouge quand `onload` a été reçu.
- Reconnexion : `onerror` → overlay « Connexion à la caméra… », nouvelle tentative 2 s plus
  tard avec le token courant (donc rafraîchi si besoin) et un nouveau `t=`.
- Démontage : `img.src = ""` pour fermer la connexion et libérer le relais.
- Le composant ne relance pas le flux quand l'access token change (voir cycle de session).

## Dev local

`vite.config.ts` :

```ts
server: {
  proxy: {
    "/api": { target: "http://localhost:8000", rewrite: p => p.replace(/^\/api/, "") },
    "/ws":  { target: "ws://localhost:8000", ws: true },
  },
}
```

Le front en dev parle donc à l'uvicorn local du README (`uv run uvicorn --factory
app.presentation.main:create_app --reload`). Le proxy conserve les réponses en streaming,
le flux MJPEG fonctionne en dev. Sans CORS à configurer, en dev comme en prod (même origine).

## Production (Raspberry Pi)

### `frontend/Dockerfile`

```
FROM node:24-alpine AS build
RUN corepack enable
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ .
RUN pnpm build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
```

Le contexte de build est la racine du dépôt (pour copier `nginx/default.conf`) : dans
`compose.yml`, `web: build: { context: ., dockerfile: frontend/Dockerfile }`. Le volume qui
montait `nginx/default.conf` disparaît : la conf est dans l'image (une seule source de vérité,
et plus de bind-mount d'un fichier unique). Un `.dockerignore` racine exclut `node_modules`,
`backend/`, `docs/`, `.git`.

### nginx

`location /` devient :

```
location / {
    root /usr/share/nginx/html;
    index index.html;
    try_files $uri /index.html;
}
location /assets/ {
    root /usr/share/nginx/html;
    add_header Cache-Control "public, max-age=31536000, immutable";
}
```

Les emplacements `/api/`, `/api/camera/stream` et `/ws` sont inchangés.

## CI (GitHub Actions, `.github/workflows/ci.yml`)

Déclencheurs : `push` sur `develop` et `main`, `pull_request` vers ces branches.

| Job | Étapes |
|---|---|
| `backend` | service `postgres:16-alpine` (`POSTGRES_USER=sentinel`, `POSTGRES_PASSWORD=sentinel`, `POSTGRES_DB=sentinel_test`, healthcheck) ; `astral-sh/setup-uv` ; `uv sync --frozen` ; `uv run ruff check .` ; `uv run ruff format --check .` ; `uv run pytest` avec `TEST_POSTGRES_HOST=localhost` |
| `frontend` | `pnpm/action-setup` ; `actions/setup-node` (Node 24, cache pnpm) ; `pnpm install --frozen-lockfile` ; `pnpm lint` ; `pnpm typecheck` ; `pnpm test -- --run` ; `pnpm build` |
| `images` | `docker build backend` et `docker build -f frontend/Dockerfile .` (sans push), pour garantir que ce qui part sur le Pi se construit |

Un badge CI est ajouté en tête du README.

## Tests (TDD, Vitest)

- `not-found` : titre, message, lien vers `/`.
- `router` : `/inconnue` rend la 404 ; `/` sans session redirige vers `/login` ; `/login` avec
  session redirige vers `/`.
- `theme-provider` : défaut sombre ; persistance ; mode système suit `matchMedia`.
- `auth-provider` : restauration depuis un refresh token ; refresh invalide → anonyme et
  stockage effacé ; `login` ok → authentifié ; `login` 401 → message d'erreur ; déconnexion.
- `jwt` : lecture de `exp`.
- `api` : 401 → refresh puis rejeu ; refresh en échec → logout.
- `login page` : validation zod, envoi, affichage de l'erreur, redirection.
- `camera-view` : état « non configurée » ; `src` contient le token ; `onerror` programme une
  reconnexion avec un nouveau `t=` ; démontage vide `src`.
- Backend : `GET /camera/status` (401 sans token, `configured` selon la config, `viewers`).

## Scripts pnpm

`dev`, `build` (`tsc -b && vite build`), `preview`, `lint`, `format`, `typecheck`, `test`.

## README

Section « Front » : prérequis (Node 24, pnpm), `pnpm install`, `pnpm dev`, URL
`http://localhost:5173`, scripts ; mise à jour de la section « Démarrer » (le `web` est
désormais construit, `docker compose up -d --build`).
