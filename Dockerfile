# Stage 1: Build Vue 3 + MapLibre GL frontend
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Lightweight Python FastAPI + WebSocket runtime (fits comfortably in Render Free 512 MB RAM)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY data/ ./data/
COPY scripts/fetch_offline_tiles.py ./scripts/fetch_offline_tiles.py
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Pre-cache compact Paris offline map tiles (~3.9 MB) so OFFLINE map layer works even in cloud
RUN python scripts/fetch_offline_tiles.py || true

EXPOSE 10000

CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
