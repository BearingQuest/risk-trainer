"""README presentation rules (engineering standards, README section).

Every image in README.md has alt text and comes either from this repository's
docs/readme/ folder or from an allow-listed badge host. Every <picture> has an
<img> fallback. Files in docs/readme/ are all used, stay under a size cap, and
SVGs pass the same safety rules as the logo files. The Bearing Quest lockups
are copies of the design-system files and are pinned by SHA-256. Each VHS tape
writes its GIF into docs/readme/ and that GIF exists.
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
README = ROOT / "README.md"
ASSETS = ROOT / "docs" / "readme"

# Hosts an image in README.md may load from. GitHub proxies each one through
# camo, so a viewer's browser never contacts them directly.
ALLOWED_IMAGE_HOSTS = {"github.com", "img.shields.io", "api.scorecard.dev"}
# github.com images are workflow status badges in this organization only.
GITHUB_BADGE_PATH = re.compile(r"/BearingQuest/[\w.-]+/actions/workflows/[\w.-]+\.ya?ml/badge\.svg")
ASSET_SUFFIXES = {".svg", ".png", ".gif", ".jpg", ".jpeg", ".webp"}
MAX_ASSET_BYTES = 5 * 1024 * 1024

# Copies of the design system's Marks files, never edited (engineering
# standards, UI and brand, Logo files). Source: BearingQuest/bearingquest.github.io
# assets/img/, same bytes as the design system's lockups.
PINNED_SHA256 = {
    "bearing-quest-lockup-on-light.svg": (
        "464c80c7ee3124dcd7e9fef0b9fbf216eb23a08b592bd10ffd506bec8388511c"
    ),
    "bearing-quest-lockup-on-dark.svg": (
        "6a34f44ae1bd1880d9ff1e14628f7c4c3947a90a7113a81934e20ab7d08ea981"
    ),
}

FENCED_BLOCK = re.compile(r"^ {0,3}(`{3,}|~{3,}).*?^ {0,3}\1[ \t]*$", re.MULTILINE | re.DOTALL)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
MD_INLINE_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
MD_REF_IMAGE = re.compile(r"!\[([^\]]*)\]\[([^\]]*)\]")
MD_REF_DEFINITION = re.compile(
    r"^ {0,3}\[([^\]]+)\]:\s*<?(\S+?)>?(?:\s+\"[^\"]*\")?\s*$", re.MULTILINE
)

SVG_FORBIDDEN = {
    "script element": re.compile(r"<script", re.IGNORECASE),
    "foreignObject element": re.compile(r"<foreignObject", re.IGNORECASE),
    "image element": re.compile(r"<image", re.IGNORECASE),
    "style element": re.compile(r"<style", re.IGNORECASE),
    "event handler attribute": re.compile(r"\son[a-z]+\s*=", re.IGNORECASE),
}
SVG_HREF = re.compile(r"\s(?:xlink:)?href\s*=\s*(['\"])(.*?)\1", re.IGNORECASE)
SVG_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
FRAGMENT = re.compile(r"#[\w.-]+")
TAPE_OUTPUT = re.compile(r"^Output\s+(\S+)\s*$", re.MULTILINE)


class _ReadmeHtml(HTMLParser):
    """Collects <img> and <source> image references and <picture> fallbacks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[tuple[str, str | None]] = []
        self.picture_depth = 0
        self.picture_has_img: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "picture":
            self.picture_depth += 1
            self.picture_has_img.append(False)
        elif tag == "img":
            self.images.append((values.get("src") or "", values.get("alt")))
            if self.picture_depth:
                self.picture_has_img[-1] = True
        elif tag == "source" and self.picture_depth:
            for candidate in (values.get("srcset") or "").split(","):
                url = candidate.strip().split(" ")[0]
                # A <source> has no alt of its own; the <img> fallback carries it.
                self.images.append((url, "(picture source)"))

    def handle_endtag(self, tag: str) -> None:
        if tag == "picture" and self.picture_depth:
            self.picture_depth -= 1


def _readme_text() -> str:
    assert README.is_file(), "README.md is missing"
    text = README.read_text(encoding="utf-8")
    return HTML_COMMENT.sub("", FENCED_BLOCK.sub("", text))


def _parsed() -> _ReadmeHtml:
    parser = _ReadmeHtml()
    parser.feed(_readme_text())
    parser.close()
    return parser


def _all_images() -> list[tuple[str, str | None]]:
    text = _readme_text()
    images = list(_parsed().images)
    images += [
        (url, alt)
        for alt, url in ((m.group(1), m.group(2)) for m in MD_INLINE_IMAGE.finditer(text))
    ]
    definitions = {label.lower(): url for label, url in MD_REF_DEFINITION.findall(text)}
    for alt, label in MD_REF_IMAGE.findall(text):
        key = (label or alt).lower()
        assert key in definitions, f"image reference [{key}] has no definition"
        images.append((definitions[key], alt))
    return images


def _local_asset(url: str) -> Path:
    parts = urlsplit(url)
    assert not parts.query and not parts.fragment, (
        f"{url}: local image URLs take no query or fragment"
    )
    path = (ROOT / unquote(parts.path)).resolve()
    assert path.is_relative_to(ASSETS.resolve()), f"{url}: local images live in docs/readme/"
    assert not (ROOT / unquote(parts.path)).is_symlink(), f"{url}: symlinks are not allowed"
    assert path.is_file(), f"{url}: file does not exist"
    assert path.suffix.lower() in ASSET_SUFFIXES, f"{url}: unexpected file type {path.suffix}"
    return path


def test_readme_has_images_to_check() -> None:
    assert _all_images(), "README.md has no images; the family header is required"


@pytest.mark.parametrize(("url", "alt"), _all_images() if README.is_file() else [])
def test_every_image_has_alt_text_and_an_allowed_source(url: str, alt: str | None) -> None:
    assert alt is not None and alt.strip(), f"{url}: alt text is missing or empty"
    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        assert parts.scheme == "https", f"{url}: remote images must use https"
        assert parts.hostname in ALLOWED_IMAGE_HOSTS, (
            f"{url}: {parts.hostname} is not an allowed host"
        )
        if parts.hostname == "github.com":
            assert GITHUB_BADGE_PATH.fullmatch(parts.path), (
                f"{url}: not a BearingQuest workflow badge"
            )
    else:
        _local_asset(url)


def test_every_picture_has_an_img_fallback() -> None:
    parser = _parsed()
    assert all(parser.picture_has_img), "a <picture> in README.md has no <img> fallback"


def test_every_asset_is_used_and_small_enough() -> None:
    if not ASSETS.is_dir():
        return
    used = {
        _local_asset(url)
        for url, _ in _all_images()
        if not (urlsplit(url).scheme or urlsplit(url).netloc)
    }
    for path in sorted(ASSETS.iterdir()):
        assert not path.is_symlink(), f"{path.name}: symlinks are not allowed"
        if path.suffix == ".tape":
            continue
        assert path.resolve() in used, (
            f"{path.name} is in docs/readme/ but README.md doesn't use it"
        )
        assert path.stat().st_size <= MAX_ASSET_BYTES, (
            f"{path.name} is over {MAX_ASSET_BYTES} bytes"
        )


@pytest.mark.parametrize("name", sorted(PINNED_SHA256))
def test_lockups_are_unedited_copies(name: str) -> None:
    path = ASSETS / name
    assert path.is_file(), f"{name} is missing from docs/readme/"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == PINNED_SHA256[name], (
        f"{name} differs from the design-system file"
    )


@pytest.mark.parametrize(
    "path", sorted(ASSETS.glob("*.svg")) if ASSETS.is_dir() else [], ids=lambda p: p.name
)
def test_svgs_pass_the_logo_safety_rules(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for label, pattern in SVG_FORBIDDEN.items():
        assert not pattern.search(text), f"{path.name}: {label} is not allowed"
    for match in SVG_HREF.finditer(text):
        assert FRAGMENT.fullmatch(match.group(2)), (
            f"{path.name}: href is not a fragment: {match.group(2)}"
        )
    for match in SVG_URL.finditer(text):
        assert FRAGMENT.fullmatch(match.group(2)), (
            f"{path.name}: url() is not a fragment: {match.group(2)}"
        )


@pytest.mark.parametrize(
    "tape", sorted(ASSETS.glob("*.tape")) if ASSETS.is_dir() else [], ids=lambda p: p.name
)
def test_each_tape_writes_an_existing_gif_in_docs_readme(tape: Path) -> None:
    outputs = TAPE_OUTPUT.findall(tape.read_text(encoding="utf-8"))
    assert outputs, f"{tape.name} has no Output line"
    for output in outputs:
        path = (ROOT / output).resolve()
        assert path.is_relative_to(ASSETS.resolve()), (
            f"{tape.name}: Output {output} is outside docs/readme/"
        )
        assert path.is_file(), (
            f"{tape.name}: {output} has not been recorded (run vhs {tape.relative_to(ROOT)})"
        )
