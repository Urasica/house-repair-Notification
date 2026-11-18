FROM node:22.23.1-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund --fetch-timeout=30000 --fetch-retries=1
COPY . .
RUN npm run build

FROM caddy:2.11.4-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
COPY Caddyfile.prod /etc/caddy/
