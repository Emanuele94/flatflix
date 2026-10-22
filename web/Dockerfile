FROM node:24.15-alpine AS build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM caddy:2.11.7-alpine
COPY web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/frontend/dist /srv/portal
