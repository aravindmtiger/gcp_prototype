# Frontend image for Cloud Run. Build from the frontend/ directory:
#   docker build -t agentflow-ui .
# The image is environment-agnostic: UI_* variables are applied at container start
# (docker/40-runtime-config.sh), so the same image is promoted dev -> staging -> prod.

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine
COPY docker/default.conf.template /etc/nginx/templates/default.conf.template
COPY docker/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/40-runtime-config.sh
COPY --from=build /app/dist /usr/share/nginx/html

# Cloud Run sends traffic to $PORT; the nginx image substitutes it into the template.
ENV PORT=8080
EXPOSE 8080
