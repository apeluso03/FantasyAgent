# Single-service image for Railway: builds the React frontend, then serves it
# from the FastAPI backend (backend/app/main.py mounts it when FRONTEND_DIST is
# set). One origin for the SPA, the REST API and the mock draft websockets --
# no CORS setup, no cross-origin websocket, one Railway service to run.
#
# backend/Dockerfile is still the API-only image for the split
# Vercel/Netlify + separate-backend setup (CLAUDE.md section 7.3).

# APP_MODE=mock builds/serves only the mock draft simulator; "full" is the
# whole app. Railway passes service variables to declared build ARGs, so
# setting APP_MODE on the service covers both stages.
ARG APP_MODE=full

# --- frontend build ---
FROM node:22-slim AS frontend
ARG APP_MODE
ENV VITE_APP_MODE=${APP_MODE}
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Same-origin API in this image, so no VITE_API_URL.
RUN npm run build

# --- backend + static frontend ---
FROM python:3.12-slim
ARG APP_MODE
ENV APP_MODE=${APP_MODE}
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY backend ./backend
# psycopg[binary] vendors its own libpq, so no apt-get needed for the Postgres driver.
RUN pip install --no-cache-dir ".[web]"

COPY --from=frontend /frontend/dist ./frontend_dist

ENV PYTHONUNBUFFERED=1 \
    FRONTEND_DIST=/app/frontend_dist \
    PORT=8000
EXPOSE 8000

# Exactly one worker: mock draft rooms (live state, pick clocks, websocket
# fan-out) live in this process's memory -- see backend/app/mock/rooms.py.
# Railway injects $PORT.
CMD ["sh", "-c", "python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
