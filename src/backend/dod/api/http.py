"""HTTP routes (docs/backend.md 9).

    GET /, /internal/main, /internal/logging   the frontend (a placeholder until it exists)
    GET /api/session[?key=...]                 the session cookie; with the key, the internal one
    GET /api/status                            the HCL's, the render loop's and the tasks' view
    GET /api/songs                             the song list (empty until plan step 8)
    GET /api/health

`/api/session` is how every page starts, before its WebSocket: it goes
through `/api`, so it works the same behind Vite's dev server. With
`?key=…` (the launch script opens the internal pages with it) it also sets
the internal cookie, HttpOnly, so page scripts never hold the key.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

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
    response = HTMLResponse(PLACEHOLDER)
    ensure_session(request, response)
    return response


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


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
