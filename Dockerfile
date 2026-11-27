# 1. the pages (React), built once
FROM node:22-slim AS pages
WORKDIR /pages
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

# 2. the API (FastAPI) and the engine, serving the pages
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt && playwright install --with-deps chromium

COPY jobfinder ./jobfinder
COPY backend ./backend
COPY assets ./assets
COPY static ./static
COPY --from=pages /pages/dist ./frontend/dist

# offers, CVs and letters; mount a volume here to keep CVs and settings between restarts
VOLUME /app/data
EXPOSE 8600
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8600/api/summary')"
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8600"]
