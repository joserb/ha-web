FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29-alpine
# Plantilla, no fichero final: la ruta de la cámara depende de la IP Tailscale
# de la Raspberry, que es configuración del host y no puede quedar en la imagen.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
