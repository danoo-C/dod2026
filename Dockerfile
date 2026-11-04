FROM python:3.13-slim

# Only the dependencies are installed into the image. The source is not copied:
# ./dod mounts the project at /work, and the editable installs point at
# /work/src/hcl and /work/src/backend, so code changes need no rebuild.
# The frontend runs in its own Node container (./dod npm, sim, frontend-build);
# a Node stage here comes with the self-contained image for the notebook
# (docs/plans/frontend.md, decision 6).
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
