"""R12 — static files are served under a content-versioned path, so a deploy isn't served stale
from the edge cache, and the versioned mount never serves anything outside static/."""

import asyncio
import hashlib
from html.parser import HTMLParser
from pathlib import Path

import pytest
from starlette.exceptions import HTTPException
from starlette.types import Scope

from risk_trainer.web.app import STATIC_DIR
from risk_trainer.web.assets import (
    CACHE_CURRENT,
    CACHE_OTHER_VERSION,
    VersionedStaticFiles,
    asset_version,
)
from tests.web_helpers import RT001_ID, STATIC_VERSION, client, static_path

OTHER_VERSION = "0123456789ab"
PAGES = ["/", f"/s/{RT001_ID}", "/responses", "/about", "/privacy", "/no-such-page"]
FONTS = sorted(path.name for path in (STATIC_DIR / "fonts").glob("*.woff2"))
# Inter v4.1 Latin subsets and its license, as recorded in docs/decisions.md (2026-10-29).
INTER_SHA256 = {
    "Inter-Regular-Latin1.woff2": (
        "f8cb1a8297bbafb8bdee0d85096e94509e0bdbc8c0fcf11d836c9577fe1037ca"
    ),
    "Inter-SemiBold-Latin1.woff2": (
        "da0bf9afabea47b878a79a029468e86157897af11818c6c71bc97b18934a8075"
    ),
    "OFL-Inter.txt": "262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a",
}
# IBM Plex Mono 2.5.0 Latin1 files, as recorded in docs/decisions.md (2026-10-15).
PLEX_MONO_SHA256 = {
    "IBMPlexMono-Regular-Latin1.woff2": (
        "e8993d946649b9d01abb1ed06d574b19d8ea3e66b5c3948602db335c44c18e56"
    ),
    "IBMPlexMono-Medium-Latin1.woff2": (
        "41201b658a328b9d00368215c2f1102770f80b15952ab82631e4006255e6365d"
    ),
}
# The Bearing Quest lockup, copied unedited (docs/decisions.md, 2026-10-29).
LOCKUP_SHA256 = "723322e0e64f7e6e91877b5122746f09a9f4e6198e7b62910b25097e3d67b9d5"


class _AssetRefs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attribute = {"link": "href", "script": "src"}.get(tag)
        ref = dict(attrs).get(attribute) if attribute else None
        if ref is not None:
            self.refs.append(ref)


def asset_refs(html: str) -> list[str]:
    parser = _AssetRefs()
    parser.feed(html)
    return parser.refs


def test_r12_version_changes_when_any_static_file_changes(tmp_path: Path) -> None:
    (tmp_path / "fonts").mkdir()
    (tmp_path / "app.css").write_text("body {}")
    (tmp_path / "fonts" / "a.woff2").write_bytes(b"wOF2one")
    first = asset_version(tmp_path)
    assert len(first) == 12
    assert asset_version(tmp_path) == first
    (tmp_path / "fonts" / "a.woff2").write_bytes(b"wOF2two")
    second = asset_version(tmp_path)
    assert second != first
    (tmp_path / "fonts" / "a.woff2").rename(tmp_path / "fonts" / "b.woff2")
    assert asset_version(tmp_path) not in (first, second)


@pytest.mark.parametrize("path", PAGES)
def test_r12_pages_link_versioned_same_origin_assets(path: str) -> None:
    refs = asset_refs(client().get(path).text)
    assert len(refs) == 4  # theme.js, app.css, htmx, app.js
    for ref in refs:
        assert ref.startswith(f"/static/{STATIC_VERSION}/"), ref


def test_r12_current_version_is_cached_for_a_year() -> None:
    response = client().get(static_path("app.css"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == CACHE_CURRENT
    assert response.headers["content-type"].startswith("text/css")


def test_r12_other_version_gets_current_file_uncached() -> None:
    test_client = client()
    current = test_client.get(static_path("app.css"))
    other = test_client.get(f"/static/{OTHER_VERSION}/app.css")
    assert other.status_code == 200
    assert other.content == current.content
    assert other.headers["cache-control"] == CACHE_OTHER_VERSION


@pytest.mark.parametrize(
    "path",
    [
        "/static/app.css",
        "/static/fonts/Inter-Regular-Latin1.woff2",
        f"/static/{STATIC_VERSION}/missing.css",
        f"/static/{OTHER_VERSION}/missing.css",
        f"/static/{STATIC_VERSION.upper()}/app.css",
        f"/static/{STATIC_VERSION}",
    ],
)
def test_r12_unversioned_malformed_or_missing_is_404(path: str) -> None:
    response = client().get(path)
    assert response.status_code == 404
    assert "immutable" not in response.headers.get("cache-control", "")


TRAVERSALS = [
    f"/static/{STATIC_VERSION}/../app.py",
    f"/static/{STATIC_VERSION}/%2e%2e/app.py",
    f"/static/{STATIC_VERSION}/fonts/../../pyproject.toml",
    f"/static/{STATIC_VERSION}/../../app.py",
    f"/static/{STATIC_VERSION}/../../../../pyproject.toml",
]


@pytest.mark.parametrize("path", TRAVERSALS)
def test_r12_traversal_through_the_app_is_404(path: str) -> None:
    assert client().get(path).status_code == 404


@pytest.mark.parametrize("path", TRAVERSALS)
def test_r12_traversal_raw_path_is_404(path: str) -> None:
    """The same paths straight to the mount, as a server delivers them (decoded, unnormalized)."""
    files = VersionedStaticFiles(directory=STATIC_DIR, version=STATIC_VERSION)
    route_path = path.removeprefix("/static").replace("%2e", ".")
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": route_path,
        "root_path": "",
        "headers": [],
    }
    with pytest.raises(HTTPException) as caught:
        asyncio.run(files.get_response(files.get_path(scope), scope))
    assert caught.value.status_code == 404


@pytest.mark.parametrize("font", FONTS)
def test_r12_fonts_are_served_as_woff2(font: str) -> None:
    response = client().get(static_path(f"fonts/{font}"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "font/woff2"
    assert response.content[:4] == b"wOF2"


def test_r12_all_four_fonts_are_present() -> None:
    assert FONTS == [
        "IBMPlexMono-Medium-Latin1.woff2",
        "IBMPlexMono-Regular-Latin1.woff2",
        "Inter-Regular-Latin1.woff2",
        "Inter-SemiBold-Latin1.woff2",
    ]


@pytest.mark.parametrize(("name", "digest"), INTER_SHA256.items())
def test_r12_inter_files_match_pinned_sha256(name: str, digest: str) -> None:
    assert hashlib.sha256((STATIC_DIR / "fonts" / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(("name", "digest"), PLEX_MONO_SHA256.items())
def test_ui02_plex_mono_files_match_pinned_sha256(name: str, digest: str) -> None:
    assert hashlib.sha256((STATIC_DIR / "fonts" / name).read_bytes()).hexdigest() == digest


def test_r12_lockup_matches_pinned_sha256() -> None:
    lockup = (STATIC_DIR / "bearing-quest-lockup.svg").read_bytes()
    assert hashlib.sha256(lockup).hexdigest() == LOCKUP_SHA256
