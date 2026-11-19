# ---- build stage ----
FROM node:20-slim AS builder
WORKDIR /app

# Frontend depends on workspace-level package.json/package-lock.json.
COPY package*.json ./
RUN npm ci

COPY apps/frontend ./apps/frontend
COPY tsconfig.json tsconfig.app.json ./

RUN npx vite build --config apps/frontend/vite.config.ts

# ---- serve stage ----
FROM nginx:stable-alpine

RUN apk add --no-cache gettext

COPY --from=builder /app/apps/frontend/dist /usr/share/nginx/html
COPY apps/frontend/nginx/default.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8080

CMD ["/bin/sh", "-c", "envsubst '$PORT $BACKEND_URL' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
