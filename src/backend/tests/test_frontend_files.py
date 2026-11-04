"""The backend serves the frontend's build (docs/plans/frontend.md, step 1):
the page routes answer with its index.html, /assets with its files; before
it is built, the placeholder page and 404s."""

import pytest
from fastapi.testclient import TestClient
from hcl.testing import sim_link

from dod.api.http import FRONTEND_DIST
from dod.control.sessions import SESSION_COOKIE
from dod.main import create_app
from dod.settings import Settings

PAGES = ["/", "/internal/main", "/internal/logging"]
INDEX = '<!doctype html><title>DOD 2026 build</title><script type="module" src="/assets/index-abc123.js"></script>'


def client(dist):
    # no lifespan (no `with`): only the routes, nothing connects to the board
    link, _ = sim_link()
    return TestClient(create_app(Settings(internal_key="k"), link=link, frontend_dist=dist))


@pytest.fixture
def built(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX, encoding="utf-8")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log('dod')", encoding="utf-8")
    return tmp_path


def test_the_build_folder_is_the_frontends():
    assert FRONTEND_DIST.parts[-3:] == ("src", "frontend", "dist")


@pytest.mark.parametrize("path", PAGES)
def test_pages_are_the_builds_index(built, path):
    response = client(built).get(path)
    assert response.status_code == 200 and response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"
    assert SESSION_COOKIE in response.cookies  # / sets it, the internal pages too


def test_assets_are_served(built):
    c = client(built)
    response = c.get("/assets/index-abc123.js")
    assert response.status_code == 200 and response.text == "console.log('dod')"
    assert "javascript" in response.headers["content-type"]
    assert c.get("/assets/missing.js").status_code == 404
    assert c.get("/assets/../index.html").status_code == 404


@pytest.mark.parametrize("path", PAGES)
def test_without_a_build_the_placeholder(tmp_path, path):
    response = client(tmp_path / "dist").get(path)
    assert response.status_code == 200 and "frontend ešte nie je hotový" in response.text


def test_without_a_build_assets_are_404_not_an_error(tmp_path):
    assert client(tmp_path / "dist").get("/assets/index-abc123.js").status_code == 404


def test_a_build_made_while_running_is_picked_up(tmp_path):
    dist = tmp_path / "dist"
    c = client(dist)
    assert c.get("/assets/index-abc123.js").status_code == 404
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("x", encoding="utf-8")
    assert c.get("/").text == INDEX
    assert c.get("/assets/index-abc123.js").status_code == 200
