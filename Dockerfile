# Plimsoll — single-image build: backend/main.py already mounts
# frontend/dist as a static SPA when it exists (see backend/config.py's
# FRONTEND_DIST), so one container serves both the API and the UI on one
# port. No dev-server/HMR here — this is the "just run it" container; keep
# using `.claude/launch.json`'s two dev servers for live-reload development.

FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
WORKDIR /app

# backend/services/cjk_font.py needs a CJK-capable font on *this* machine at
# runtime to embed Traditional Chinese text into PDF exports (匯出 → PDF).
# Deliberately fonts-wqy-zenhei, NOT fonts-noto-cjk: reportlab's TTFont
# parser only supports TrueType (glyf) outlines, and Noto's CJK .ttc ships
# PostScript/CFF outlines — registerFont raises "postscript outlines are
# not supported" (confirmed by actually running the export endpoint in this
# image). wqy-zenhei is real TrueType and is cjk_font.py's own Linux
# fallback candidate. Don't add fonts-noto-cjk alongside it: find_cjk_font()
# checks Noto's path first, so its mere presence would still break export.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
# data/demo/*.pdf (demo comparison + chain data) and data/store/config/**
# (approval roles / rulesets / term aliases — versioned seed config, not
# runtime state) are committed to git; data/store/sessions|exports|.integrity
# are NOT — those are per-run local state, see docker-compose.yml's volume.
COPY data/demo/ ./data/demo/
COPY data/store/config/ ./data/store/config/
# The glossary is product content, not runtime state — a second copy lives
# outside the data volume, because a named volume only takes the seed config
# on its first run and would otherwise never see a newer glossary
# (backend/storage/config_loader.py reads both).
COPY data/store/config/glossary/ ./seed/glossary/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# 8110 (not 8099, which Postman Interceptor claims) — see docker-compose.yml.
EXPOSE 8110
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8110"]
