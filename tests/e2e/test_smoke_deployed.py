"""Read-only smoke checks against the deployed app (PRD §9 item 4; R9, R12, R14).

Runs with `make smoke SMOKE_BASE_URL=https://<distribution>.cloudfront.net`, and in the deploy
workflow's `smoke` job after every apply. GET only: nothing here submits a form or records an
attempt (a unit test enforces it).
"""

import os
from collections.abc import Iterator

import httpx
import pytest

from risk_trainer.web.app import STATIC_DIR
from risk_trainer.web.assets import asset_version
from tests.e2e.smoke_http import FINDINGS_PER_SCENARIO, parse_page, read_only_client

pytestmark = pytest.mark.smoke


@pytest.fixture(scope="session")
def deployed_url() -> str:
    url = os.environ.get("SMOKE_BASE_URL", "").rstrip("/")
    if not url:
        pytest.skip("set SMOKE_BASE_URL to the deployed https:// URL")
    assert url.startswith("https://"), "the deployed app is HTTPS only"
    return url


@pytest.fixture(scope="session")
def client(deployed_url: str) -> Iterator[httpx.Client]:
    with read_only_client(deployed_url) as http:
        yield http


@pytest.fixture(scope="session")
def home(client: httpx.Client) -> httpx.Response:
    return client.get("/")


def test_smoke_home_security_headers(home: httpx.Response) -> None:
    assert home.status_code == 200
    assert home.headers["strict-transport-security"].startswith("max-age=")
    assert "frame-ancestors 'none'" in home.headers["content-security-policy"]
    assert home.headers["x-frame-options"] == "DENY"
    assert home.headers["x-content-type-options"] == "nosniff"


def test_smoke_http_redirects_to_https(client: httpx.Client, deployed_url: str) -> None:
    response = client.get(deployed_url.replace("https://", "http://", 1) + "/")
    assert response.status_code in (301, 302, 307, 308)
    assert response.headers["location"].startswith("https://")


def test_smoke_scenario_page_shows_five_findings(
    client: httpx.Client, home: httpx.Response
) -> None:
    scenario_hrefs = parse_page(home.text).scenario_hrefs
    assert scenario_hrefs, "the home page lists no scenarios"
    response = client.get(scenario_hrefs[0])
    assert response.status_code == 200
    assert parse_page(response.text).findings == FINDINGS_PER_SCENARIO


def test_smoke_stats_page_ok(client: httpx.Client) -> None:
    # R22: works whatever the counts are, including before any scenario reaches the minimum.
    response = client.get("/stats")
    assert response.status_code == 200
    assert "<h1>Learner stats</h1>" in response.text
    assert "This is a learning tool, not research." in response.text


def test_smoke_stylesheet_is_immutable(client: httpx.Client, home: httpx.Response) -> None:
    (href,) = parse_page(home.text).stylesheet_hrefs
    # The version hashes this checkout's static/ folder, so a match means this commit is live.
    assert f"/static/{asset_version(STATIC_DIR)}/" in href, href
    response = client.get(href)
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]
