# =============================================================================
# Frontend Dockerfile (multi-stage)
# =============================================================================

# -----------------------------------------------------------------------------
# Development: hot reload
# -----------------------------------------------------------------------------
FROM node:20-alpine AS development

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

EXPOSE 5173

CMD ["npm", "run", "dev"]

# -----------------------------------------------------------------------------
# Builder: production 빌드
# -----------------------------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# -----------------------------------------------------------------------------
# Production: Nginx로 static 서빙
# (실제 운영에서는 별도 Nginx 이미지나 메인 nginx에서 dist/ 마운트)
# -----------------------------------------------------------------------------
FROM nginx:1.25-alpine AS production

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.prod.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
