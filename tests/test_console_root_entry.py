"""Root content negotiation, canonical entry and confined Console assets."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lingshu_gate.application.health import HealthService
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.interfaces.control_api import meta_routes


@pytest.fixture
def entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    static = tmp_path / "static"
    console = static / "console"
    (console / "assets").mkdir(parents=True)
    (console / "index.html").write_text(
        '<!doctype html><title>Console fixture</title><script src="/assets/index-abcdefgh.js"></script>',
        encoding="utf-8",
    )
    (console / "assets" / "index-abcdefgh.js").write_text("/* synthetic Console bundle */", encoding="utf-8")
    (console / "assets" / "plain.js").write_text("/* synthetic nonhashed asset */", encoding="utf-8")
    for name in ("lingshu-gate-icon.svg", "lingshu-gate-app-icon.svg", "lingshu-gate-icon-512.png"):
        (console / name).write_bytes(b"synthetic-icon")
    monkeypatch.setattr(meta_routes, "STATIC_DIR", static)
    auth = Mock(spec=AuthStore)
    auth.has_users.return_value = True
    app = FastAPI()
    meta_routes.register_meta_routes(
        app, settings=Settings(data_dir=tmp_path, config_dir=tmp_path / "mcp.d"),
        auth_store=auth, health_service=Mock(spec=HealthService),
    )
    with TestClient(app) as client:
        yield client, console


@pytest.mark.parametrize(
    ("accept", "representation"),
    [
        (None, "json"),
        ("", "json"),
        ("*/*", "json"),
        ("application/json", "json"),
        ("application/json;q=0.001,text/html;q=1", "json"),
        ("application/json;q=1.000,text/html", "json"),
        ("text/html", "html"),
        ("TEXT/HTML; Q=1", "html"),
        ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "html"),
        ("text/*", "html"),
        ("text/html;q=0.9,*/*;q=0.8", "html"),
        ("text/html;q=0.2,*/*;q=0.8", "json"),
        ("text/html;q=0,*/*;q=1", "json"),
        ("application/json;q=0,text/html", "html"),
        ("application/json;q=0,*/*;q=1", "html"),
        ("application/*;q=0,*/*;q=1", "html"),
        ("application/json;q=0,text/html;q=0,*/*;q=1", "unacceptable"),
        ("text/html;q=0,text/*;q=1,application/json;q=0", "unacceptable"),
        ("*/*;q=0", "unacceptable"),
        ("image/png", "unacceptable"),
        ("text/html;q=-1", "unacceptable"),
        ("text/html;q=1.1", "unacceptable"),
        ("text/html;q=nan", "unacceptable"),
        ("text/html;q=0.1234", "unacceptable"),
        ("text/html;q", "unacceptable"),
        ("text/html;q=0;q=1", "unacceptable"),
    ],
)
def test_root_negotiates_without_caching_cross_representation(entry, accept, representation):
    client, _ = entry
    headers = {} if accept is None else {"Accept": accept}
    response = client.get("/", headers=headers)
    assert response.headers["vary"] == "Accept"
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["pragma"] == "no-cache"
    if representation == "html":
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "Console fixture" in response.text
    elif representation == "json":
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        assert response.json()["console"] == "/"
        assert response.json()["meta"] == "/v1/meta"
        assert response.json()["auth"]["enabled"] is True
    else:
        assert response.status_code == 406
        assert response.json()["detail"] == "No acceptable root representation"


def test_multiple_accept_header_lines_are_combined(entry):
    client, _ = entry
    response = client.get("/", headers=[("Accept", "text/html"), ("Accept", "application/json")])
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"


def test_explicit_metadata_endpoint_is_always_json_even_for_browser_accept(entry):
    client, _ = entry
    expected = client.get("/").json()
    response = client.get("/v1/meta", headers={"Accept": "text/html,application/json;q=0"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == expected
    assert "no-store" in response.headers["cache-control"]
    assert "vary" not in response.headers


@pytest.mark.parametrize("path", ["/console", "/console/", "/console/index.html"])
def test_old_entry_redirects_to_local_root_with_query_bytes_preserved(entry, path):
    client, _ = entry
    query = "bookmark=one&bookmark=two&next=%2F%23%2FmyServers&label=a+b&url=https%3A%2F%2Fexample.test"
    response = client.get(path + "?" + query, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/?" + query
    assert "no-store" in response.headers["cache-control"]
    followed = client.get(path + "?" + query, headers={"Accept": "text/html"})
    assert followed.status_code == 200
    assert followed.url.path == "/"
    assert followed.url.query == query.encode("ascii")
    assert "Console fixture" in followed.text


@pytest.mark.parametrize("path", ["/", "/console", "/console/", "/console/index.html"])
def test_missing_build_fails_as_html_but_does_not_hide_metadata(entry, path):
    client, console = entry
    (console / "index.html").unlink()
    response = client.get(path, headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Console asset not found"
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["vary"] == "Accept"
    assert client.get("/").status_code == 200
    assert client.get("/v1/meta").json()["service"] == "Lingshu Gate"


@pytest.mark.parametrize(
    ("asset", "immutable"),
    [("assets/index-abcdefgh.js", True), ("assets/plain.js", False),
     ("lingshu-gate-icon.svg", False), ("lingshu-gate-app-icon.svg", False),
     ("lingshu-gate-icon-512.png", False)],
)
def test_new_and_old_assets_match_with_correct_cache_policy(entry, asset, immutable):
    client, _ = entry
    new = client.get("/" + asset)
    old = client.get("/console/" + asset)
    assert new.status_code == old.status_code == 200
    assert new.content == old.content
    assert new.headers["content-type"] == old.headers["content-type"]
    assert ("immutable" in new.headers["cache-control"]) is immutable
    assert new.headers["cache-control"] == old.headers["cache-control"]
    assert "vary" not in new.headers
    assert "max-age=31536000" in new.headers["cache-control"] if immutable else "max-age=3600" in new.headers["cache-control"]


def test_entry_conditional_requests_cannot_reuse_the_other_representation(entry):
    client, _ = entry
    html = client.get("/", headers={"Accept": "text/html"})
    json = client.get("/", headers={"Accept": "application/json", "If-None-Match": html.headers["etag"]})
    assert json.status_code == 200
    assert json.headers["content-type"] == "application/json"
    assert "no-store" in json.headers["cache-control"]
    again = client.get("/", headers={"Accept": "text/html", "If-None-Match": html.headers["etag"]})
    assert again.status_code == 200
    assert again.content == html.content


@pytest.mark.parametrize(
    "path",
    ["/assets/%2e%2e/private.json", "/assets/%2e%2e/%2e%2e/outside.json",
     "/assets/%5c..%5coutside.json", "/console/%2e%2e/outside.json",
     "/console/assets/%2e%2e/index.html", "/assets/not-built.js",
     "/console/not-built.js", "/assets/", "/index.html", "/some-future-clean-path",
     "/assets/%00index.js", "/console/assets/index-abcdefgh.js:%24DATA",
     "/console/%2Foutside.json",
     "/v1/unknown", "/mcp/unknown", "/oauth/unknown", "/.well-known/unknown"],
)
def test_traversal_missing_assets_and_unknown_routes_never_become_console(entry, path):
    client, console = entry
    (console / "private.json").write_text('"synthetic boundary marker"', encoding="utf-8")
    (console.parent / "outside.json").write_text('"synthetic outside marker"', encoding="utf-8")
    response = client.get(path, headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert "Console fixture" not in response.text
    assert "synthetic boundary marker" not in response.text
    assert "synthetic outside marker" not in response.text


@pytest.mark.parametrize("asset", ["index.html", "assets/index-abcdefgh.js", "lingshu-gate-icon.svg"])
def test_symlink_outside_console_tree_is_not_served(entry, tmp_path, asset):
    client, console = entry
    outside = tmp_path / "outside.txt"
    outside.write_text("synthetic outside marker", encoding="utf-8")
    target = console / asset
    target.unlink()
    target.symlink_to(outside)
    path = "/" if asset == "index.html" else "/" + asset
    response = client.get(path, headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert "synthetic outside marker" not in response.text


def test_console_directory_symlink_cannot_move_the_serving_boundary(entry, tmp_path):
    client, console = entry
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.html").write_text("synthetic outside marker", encoding="utf-8")
    console.rename(console.with_name("saved-console"))
    console.symlink_to(outside, target_is_directory=True)
    response = client.get("/", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert "synthetic outside marker" not in response.text


def test_symlink_loop_fails_without_exposing_a_local_path(entry):
    client, console = entry
    loop = console / "assets" / "loop.js"
    loop.symlink_to(loop.name)
    response = client.get("/assets/loop.js")
    assert response.status_code == 404
    assert str(console) not in response.text


def test_docs_and_openapi_are_not_shadowed_by_console(entry):
    client, _ = entry
    assert "swagger-ui" in client.get("/docs").text
    schema = client.get("/openapi.json").json()
    assert "/v1/meta" in schema["paths"]
    assert schema["paths"]["/v1/meta"]["get"]["tags"] == ["meta"]
