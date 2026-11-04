"""HTTP routes (docs/backend.md 9).

    GET /, /internal/main, /internal/logging   the frontend's index.html (a placeholder until it is built)
    GET /assets/*                              the rest of the frontend's build
    GET /api/session[?key=...]                 the session cookie; with the key, the internal one
    GET /api/status                            the HCL's, the render loop's and the tasks' view
    GET /api/songs                             the song list, and which songs are downloaded
    GET /media/<id>.mp4                        a downloaded song, with range requests
    GET /api/health

The frontend is served from its build, `src/frontend/dist` in the mounted
project (`./dod frontend-build`); React Router picks the screen. In
development the pages come from Vite instead (`./dod sim`), which forwards
`/api`, `/ws` and `/media` here.

`/api/session` is how every page starts, before its WebSocket: it goes
through `/api`, so it works the same behind Vite's dev server. With
`?key=…` (the launch script opens the internal pages with it) it also sets
the internal cookie, HttpOnly, so page scripts never hold the key.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dod.control.sessions import (
    INTERNAL_COOKIE,
    SESSION_COOKIE,
    cookie_options,
    key_matches,
    new_token,
    public_id,
    session_token,
    short,
)

router = APIRouter()

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"  # src/frontend/dist

PLACEHOLDER = """<!doctype html>
<html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DOD 2026</title></head>
<body style="font-family: system-ui, sans-serif; background: #111; color: #eee; padding: 2rem">
<h1>DOD 2026</h1><p>Backend beží, frontend ešte nie je hotový.</p>
</body></html>
"""


def ensure_session(request: Request, response: Response) -> str:
    """The visitor's token; a new one (and its cookie) if they have none."""
    token = session_token(request.cookies)
    if token is None:
        token = new_token()
        response.set_cookie(SESSION_COOKIE, token, **cookie_options())  # type: ignore[arg-type]
    return token


@router.get("/", response_class=HTMLResponse)
@router.get("/internal/main", response_class=HTMLResponse)
@router.get("/internal/logging", response_class=HTMLResponse)
async def page(request: Request) -> HTMLResponse:
    index = request.app.state.frontend_dist / "index.html"
    if index.is_file():
        # no-cache: a new build is picked up on the next load; the files it
        # points to have a hash in their names, so they can be cached
        response = HTMLResponse(index.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})
    else:
        response = HTMLResponse(PLACEHOLDER)
    ensure_session(request, response)
    return response


class BuildFiles(StaticFiles):
    """The build's /assets. Until the frontend is built the folder doesn't
    exist: 404, where StaticFiles would answer every request with an error."""

    async def check_config(self) -> None:
        if self.directory is not None and Path(self.directory).is_dir():
            await super().check_config()


def mount_frontend(app: Any, dist: Path) -> None:
    app.state.frontend_dist = dist
    app.mount("/assets", BuildFiles(directory=dist / "assets", check_dir=False), name="assets")


@router.get("/api/session")
async def session(request: Request, key: str | None = None) -> Response:
    internal_key = request.app.state.settings.internal_key
    if key is not None and not key_matches(key, internal_key):
        return JSONResponse({"detail": "wrong key"}, status_code=403)
    token = session_token(request.cookies)
    new = token is None
    if token is None:
        token = new_token()
    internal = key is not None or key_matches(request.cookies.get(INTERNAL_COOKIE), internal_key)
    response = JSONResponse({"session": short(public_id(token)), "internal": internal})
    if new:
        response.set_cookie(SESSION_COOKIE, token, **cookie_options())  # type: ignore[arg-type]
    if key is not None:
        response.set_cookie(INTERNAL_COOKIE, key, **cookie_options())  # type: ignore[arg-type]
    return response


@router.get("/api/status")
async def status(request: Request) -> dict[str, Any]:
    app = request.app
    loop = app.state.loop
    return {
        "link": app.state.hardware.link_status(),
        "render": {"fps": loop.fps, "effect": loop.scene.effect.id, "led_count": app.state.hardware.led_count,
                   "ticks": loop.ticks, "mode": app.state.state.mode},
        "tasks": {"running": app.state.tasks.running, "restarts": app.state.tasks.restarts},
        "connections": len(app.state.hub.connections),
    }


@router.get("/api/songs")
async def songs(request: Request) -> list[dict[str, Any]]:
    return [s.model_dump() for s in request.app.state.songs()]


MEDIA = re.compile(r"([A-Za-z0-9_-]{11})\.mp4")


@router.get("/media/{name}")
async def media(request: Request, name: str) -> Response:
    """A downloaded song for the main screen's <video> (backend.md 9). The id is
    checked against the pattern and the song list before it is used for a
    path; anything else is 404. FileResponse answers Range with 206, so the
    video can seek."""
    match = MEDIA.fullmatch(name)
    video = request.app.state.library.video(match[1]) if match else None
    if video is None:
        return JSONResponse({"detail": "no such song"}, status_code=404)
    return FileResponse(video, media_type="video/mp4")


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
