"""The WebSocket hub and the HTTP routes, with TestClient (docs/backend.md 9).

The app runs in TestClient's own thread; anything done to it directly goes
through `client.portal.call`, so it runs in the app's event loop.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient
from hcl.testing import sim_link
from starlette.websockets import WebSocketDisconnect

from dod.api.messages import LogLine
from dod.control.sessions import INTERNAL_COOKIE, SESSION_COOKIE, new_token, public_id
from dod.main import create_app
from dod.settings import Settings

KEY = "test-key"


def app(**settings):
    link, _ = sim_link()
    return create_app(Settings(internal_key=KEY, **settings), link=link)


@pytest.fixture
def client():
    with TestClient(app()) as c:
        yield c


def cookies(token=None, key=None):
    parts = []
    if token:
        parts.append(f"{SESSION_COOKIE}={token}")
    if key:
        parts.append(f"{INTERNAL_COOKIE}={key}")
    return {"cookie": "; ".join(parts)} if parts else {}


def connect(client, role="phone", token=None, key=None):
    """A WebSocket with its own cookies (not the client's jar). Returns (ws, token)."""
    token = token or new_token()
    return client.websocket_connect(f"/ws?role={role}", headers=cookies(token, key)), token


def until(ws, type_, check=lambda msg: True, limit=500):
    """Read messages until one of `type_` passes `check` (previews keep coming, so this never hangs)."""
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == type_ and check(msg):
            return msg
    raise AssertionError(f"no {type_} message")


def closed_with(ws, limit=500):
    for _ in range(limit):
        try:
            ws.receive_json()
        except WebSocketDisconnect as e:
            return e.code
    raise AssertionError("not closed")


def send(ws, **message):
    ws.send_text(json.dumps(message))


# --- connecting ---------------------------------------------------------------


def test_a_phone_gets_welcome_state_and_you(client):
    cm, token = connect(client)
    with cm as ws:
        welcome = ws.receive_json()
        assert welcome["type"] == "welcome" and welcome["role"] == "phone"
        assert welcome["session"] == public_id(token)[:4]
        assert [p["id"] for p in welcome["presets"]] == ["rainbow", "fire", "police", "breathe", "comet", "strobe", "solid"]
        assert welcome["presets"][0]["params"][0]["label"] == "Rýchlosť"
        assert welcome["turn_seconds"] == 180 and welcome["songs"] == []
        state = ws.receive_json()
        assert state["type"] == "state" and state["mode"] == "idle"
        you = ws.receive_json()
        assert you == {"type": "you", "session": welcome["session"], "position": None, "in_control": False,
                       "turn_ends_at": None}


def test_without_a_session_cookie_4401(client):
    with client.websocket_connect("/ws?role=phone") as ws:
        assert closed_with(ws) == 4401


def test_an_unknown_role_4400(client):
    cm, _ = connect(client, role="admin")
    with cm as ws:
        assert closed_with(ws) == 4400


@pytest.mark.parametrize("role", ["main", "logging"])
def test_internal_roles_need_the_key(client, role):
    for key in (None, "wrong"):
        cm, _ = connect(client, role=role, key=key)
        with cm as ws:
            assert closed_with(ws) == 4403
    cm, _ = connect(client, role=role, key=KEY)
    with cm as ws:
        assert ws.receive_json()["role"] == role


def test_a_second_main_replaces_the_first(client):
    first, _ = connect(client, role="main", key=KEY)
    with first as old:
        until(old, "state", lambda s: s["music"]["player_connected"])
        second, _ = connect(client, role="main", key=KEY)
        with second as new:
            new.receive_json()
            assert closed_with(old) == 4001
            send(new, type="set_preset", preset="solid")  # the new one works
            until(new, "state", lambda s: s["manual"]["preset"] == "solid")
        # the newer one closed too: nobody can play
        assert client.portal.call(lambda: client.app.state.state.player_connected) is False


# --- commands -----------------------------------------------------------------


def test_a_phone_queues_takes_control_and_everyone_sees_its_preset(client):
    watcher_cm, _ = connect(client)
    phone_cm, token = connect(client)
    with watcher_cm as watcher, phone_cm as phone:
        send(phone, type="join_queue")
        you = until(phone, "you", lambda y: y["in_control"])
        assert you["position"] == 0 and you["turn_ends_at"] is not None
        send(phone, type="set_preset", preset="solid")
        send(phone, type="set_param", name="color", value="#00ff00")
        state = until(watcher, "state", lambda s: s["manual"]["params"].get("color") == "#00ff00")
        assert state["mode"] == "manual" and state["queue"]["controller"] == public_id(token)[:4]
        preview = until(watcher, "preview", lambda p: p["leds"][0] == "#00cc00")  # green at brightness 0.8
        assert len(preview["leds"]) == 10 and len(preview["matrix"]) == 16 and 0 <= preview["brightness"] <= 15


def test_not_your_turn(client):
    first_cm, _ = connect(client)
    second_cm, _ = connect(client)
    with first_cm as first, second_cm as second:
        send(first, type="join_queue")
        until(first, "you", lambda y: y["in_control"])
        send(second, type="join_queue")
        assert until(second, "you", lambda y: y["position"] == 1)["in_control"] is False
        send(second, type="set_preset", preset="solid")
        assert until(second, "error")["code"] == "not_your_turn"
        assert client.portal.call(lambda: client.app.state.state.preset) == "rainbow"


def test_the_main_screen_may_always_control(client):
    cm, _ = connect(client, role="main", key=KEY)
    with cm as main:
        send(main, type="set_preset", preset="solid")
        until(main, "state", lambda s: s["manual"]["preset"] == "solid")


def test_wrong_messages_get_errors(client):
    cm, _ = connect(client)
    main_cm, _ = connect(client, role="main", key=KEY)
    with cm as phone, main_cm as main:
        send(phone, type="join_queue")
        until(phone, "you", lambda y: y["in_control"])
        for message, code in [
            ({"type": "dance"}, "invalid"),
            ({"type": "set_param", "name": "speed", "value": 99}, "invalid"),  # the state refuses it
            ({"type": "set_preset", "preset": "idle"}, "invalid"),
            ({"type": "admin", "action": "skip"}, "forbidden"),
            ({"type": "spectrum", "bands": [0.1] * 32}, "forbidden"),
            ({"type": "play_song", "song": "dQw4w9WgXcQ"}, "unknown_song"),  # a main is connected, no songs yet
        ]:
            phone.send_text(json.dumps(message))
            assert until(phone, "error")["code"] == code, message
        phone.send_bytes(b"\x00\x01")
        assert until(phone, "error")["code"] == "invalid"
        send(main, type="join_queue")
        assert until(main, "error")["code"] == "forbidden"


def test_play_song_without_a_main_screen(client):
    cm, _ = connect(client)
    with cm as phone:
        send(phone, type="join_queue")
        until(phone, "you", lambda y: y["in_control"])
        send(phone, type="play_song", song="dQw4w9WgXcQ")
        assert until(phone, "error")["code"] == "no_player"


def test_admin_commands(client):
    a_cm, a = connect(client)
    b_cm, b = connect(client)
    main_cm, _ = connect(client, role="main", key=KEY)
    with a_cm as phone_a, b_cm as phone_b, main_cm as main:
        send(phone_a, type="join_queue")
        until(phone_a, "you", lambda y: y["in_control"])
        send(phone_b, type="join_queue")
        until(phone_b, "you", lambda y: y["position"] == 1)
        send(main, type="admin", action="skip")
        until(phone_b, "you", lambda y: y["in_control"])
        send(main, type="admin", action="pause_queue")
        until(main, "state", lambda s: s["queue"]["paused"])
        send(main, type="admin", action="resume_queue")
        until(main, "state", lambda s: not s["queue"]["paused"])


def test_leaving_the_queue(client):
    cm, _ = connect(client)
    with cm as phone:
        send(phone, type="join_queue")
        until(phone, "you", lambda y: y["in_control"])
        send(phone, type="leave_queue")
        until(phone, "you", lambda y: y["position"] is None)


def test_a_disconnected_controller_loses_control():
    with TestClient(app(inactive_seconds=0.3)) as client:
        cm, token = connect(client)
        with cm as phone:
            send(phone, type="join_queue")
            until(phone, "you", lambda y: y["in_control"])
        controller = lambda: client.portal.call(lambda: client.app.state.state.queue.controller)
        assert controller() == public_id(token)  # still, right after closing
        deadline = time.monotonic() + 3
        while controller() is not None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert controller() is None


def test_two_tabs_of_one_phone_count_as_one(client):
    token = new_token()
    first, _ = connect(client, token=token)
    second, _ = connect(client, token=token)
    queue = lambda: client.app.state.state.queue
    with first as tab1:
        send(tab1, type="join_queue")
        until(tab1, "you", lambda y: y["in_control"])
        with second as tab2:
            until(tab2, "you", lambda y: y["in_control"])  # the same visitor
        # one tab closed: still online
        assert client.portal.call(lambda: public_id(token) not in queue()._offline_since)


# --- limits -------------------------------------------------------------------


def test_a_flood_from_one_phone_is_cut_at_about_20_a_second(client):
    cm, _ = connect(client)
    with cm as phone:
        send(phone, type="join_queue")
        until(phone, "you", lambda y: y["in_control"])
        send(phone, type="set_preset", preset="rainbow")
        values = [round(0.05 + i * 0.01, 2) for i in range(100)]
        for v in values:
            send(phone, type="set_param", name="speed", value=v)
        until(phone, "error", lambda e: e["code"] == "rate_limited")
        time.sleep(0.2)
        speed = client.portal.call(lambda: client.app.state.state.params["speed"])
        assert speed < values[50]  # most of the flood was dropped


def test_a_huge_message_closes_the_connection(client):
    cm, _ = connect(client)
    with cm as phone:
        phone.receive_json()
        phone.send_text(json.dumps({"type": "set_preset", "preset": "x" * 100_000}))
        assert closed_with(phone) == 1009


def test_state_messages_are_coalesced(client):
    main_cm, _ = connect(client, role="main", key=KEY)
    phone_cm, _ = connect(client)
    with main_cm as main, phone_cm as phone:
        until(phone, "you")
        start = time.monotonic()
        for i in range(200):  # the main screen isn't rate limited
            send(main, type="set_param", name="speed", value=round(0.05 + i * 0.005, 3))
        last = round(0.05 + 199 * 0.005, 3)
        states = 0
        while True:
            msg = phone.receive_json()
            if msg["type"] == "state":
                states += 1
                if msg["manual"]["params"]["speed"] == last:
                    break
        elapsed = time.monotonic() - start
        assert states <= elapsed * 20 + 3, (states, elapsed)
        assert states < 100


# --- logs ---------------------------------------------------------------------


def test_logs_go_to_main_and_logging_never_to_phones(client):
    main_cm, _ = connect(client, role="main", key=KEY)
    logging_cm, _ = connect(client, role="logging", key=KEY)
    phone_cm, _ = connect(client)
    with main_cm as main, logging_cm as logging_page, phone_cm as phone:
        for ws in (main, logging_page, phone):
            until(ws, "you")
        line = LogLine(t=1.0, tag="rgb-core", level="INFO", text="frame 000001 committed")
        client.portal.call(lambda: client.app.state.hub.send_log([line]))
        for ws in (main, logging_page):
            assert until(ws, "log")["lines"][0]["tag"] == "rgb-core"
        for _ in range(30):  # three seconds of previews: no log among them
            assert phone.receive_json()["type"] != "log"


# --- HTTP ---------------------------------------------------------------------


def test_only_the_main_screen_gets_the_wifi():
    with TestClient(app(wifi_ssid="DOD-SPSE", wifi_password="svetlo2026")) as c:
        for role, key in (("main", KEY), ("logging", KEY), ("phone", None)):
            cm, _ = connect(c, role=role, key=key)
            with cm as ws:
                welcome = ws.receive_json()
                expected = {"ssid": "DOD-SPSE", "password": "svetlo2026"} if role == "main" else None
                assert welcome["wifi"] == expected, role


def test_without_the_wifi_settings_nobody_gets_it(client):
    cm, _ = connect(client, role="main", key=KEY)
    with cm as ws:
        assert ws.receive_json()["wifi"] is None


def test_api_session_sets_the_cookie_once(client):
    client.cookies.clear()
    first = client.get("/api/session")
    token = first.cookies[SESSION_COOKIE]
    assert first.json() == {"session": public_id(token)[:4], "internal": False}
    assert "httponly" in first.headers["set-cookie"].lower()
    again = client.get("/api/session")
    assert SESSION_COOKIE not in again.cookies and again.json()["session"] == public_id(token)[:4]


def test_api_session_with_the_key(client):
    client.cookies.clear()
    assert client.get("/api/session", params={"key": "wrong"}).status_code == 403
    ok = client.get("/api/session", params={"key": KEY})
    assert ok.json()["internal"] is True and ok.cookies[INTERNAL_COOKIE] == KEY
    assert client.get("/api/session").json()["internal"] is True  # the cookie is remembered
    # and the cookies from /api/session open the main screen's WebSocket
    jar = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
    with client.websocket_connect("/ws?role=main", headers={"cookie": jar}) as ws:
        assert ws.receive_json()["role"] == "main"


@pytest.mark.parametrize("path", ["/", "/internal/main", "/internal/logging"])
def test_pages_set_the_session(client, path):
    client.cookies.clear()
    response = client.get(path)
    assert response.status_code == 200 and "DOD 2026" in response.text  # the build's or the placeholder
    assert SESSION_COOKIE in response.cookies


def test_api_songs_and_status(client):
    assert client.get("/api/songs").json() == []
    cm, _ = connect(client)
    with cm as ws:
        ws.receive_json()
        status = client.get("/api/status").json()
        assert status["connections"] == 1 and "state broadcaster" in status["tasks"]["running"]
