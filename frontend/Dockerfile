FROM node:24-alpine AS deps
# npm's downloader retries on slow links (corepack gave up on the Raspberry Pi); keep the
# version in sync with "packageManager" in frontend/package.json.
RUN npm install -g pnpm@12.4.2
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Development: the Vite dev server with HMR; ./frontend is bind-mounted over /app
# (node_modules stays in an anonymous volume, see compose.dev.yml).
FROM deps AS dev
EXPOSE 5173
CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "5173"]

FROM deps AS build
COPY frontend/ .
RUN pnpm build

# Production (last stage: the default when no --target is given).
FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/locations.conf /etc/nginx/snippets/locations.conf
# HTTPS server, enabled at start only when the certificate is mounted (nginx/enable-tls.sh).
COPY nginx/tls.conf /etc/nginx/tls.conf.available
COPY nginx/enable-tls.sh /docker-entrypoint.d/10-enable-tls.sh
