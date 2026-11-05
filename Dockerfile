# Two images from one file:
#
#   dev       (./dod build) only the dependencies. ./dod mounts the project at
#             /work, and the editable installs point at /work/src/hcl and
#             /work/src/backend, so code changes need no rebuild. The frontend
#             runs in its own Node container (./dod npm, sim, frontend-build).
#   notebook  (the default; start.ps1 builds it) dev plus the source and the
#             built frontend copied in, so it runs on its own with nothing
#             mounted but cache/ (tech-spec 6.3).

# --- the frontend's build, for the notebook image -------------------------
FROM node:22.23.4-slim AS frontend
WORKDIR /build/src/frontend
COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY src/frontend/ ./
# the type check reads the presets from the backend's schema (tests/*.test.tsx)
COPY src/backend/schema/ /build/src/backend/schema/
RUN npm run build

# --- dev: the dependencies only --------------------------------------------
FROM python:3.13-slim AS dev
WORKDIR /work
# ffmpeg: yt-dlp merges a song's video and audio into one .mp4 with it, and the
# tests make a short test clip with it (plan step 8)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*
COPY src/hcl/pyproject.toml src/hcl/pyproject.toml
COPY src/backend/pyproject.toml src/backend/pyproject.toml
# Empty packages stand in for the source, so pip can do the editable installs.
# Both in one pip call: the backend depends on "hcl", which is the local one.
RUN mkdir -p src/hcl/hcl src/backend/dod \
 && touch src/hcl/hcl/__init__.py src/backend/dod/__init__.py \
 && pip install --no-cache-dir -e "src/hcl[dev]" -e "src/backend[dev]" \
 # mpremote and esptool talk to the board (code upload, flashing MicroPython)
 && pip install --no-cache-dir mpremote esptool

# --- notebook: everything inside -------------------------------------------
FROM dev AS notebook
# the editable installs from dev point here, so copying the source over the
# empty stand-ins is all it takes
COPY src/hcl/ src/hcl/
COPY src/backend/ src/backend/
COPY --from=frontend /build/src/frontend/dist/ src/frontend/dist/
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# Like ./dod backend, without --reload: the settings are checked first, so a
# wrong DOD_ variable stops it with a message naming it.
CMD ["sh", "-c", "python -c 'from dod.main import settings_or_exit; settings_or_exit()' && exec uvicorn --factory dod.main:create_app --host 0.0.0.0 --port 8000 --ws-max-size 65536"]
