"""PRD §6 Accessibility and R12 — theme tokens meet WCAG contrast in both themes, the theme
switch markup, and self-hosted fonts."""

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest

from risk_trainer.web.app import STATIC_DIR
from tests.web_helpers import RT001_ID, client

CSS = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
HEX = r"#[0-9A-Fa-f]{6}"


def block(selector_pattern: str) -> str:
    match = re.search(selector_pattern + r"\s*\{([^{}]*)\}", CSS)
    assert match, selector_pattern
    return match.group(1)


def tokens(body: str) -> dict[str, str]:
    return {name: value.upper() for name, value in re.findall(rf"--([\w-]+):\s*({HEX})", body)}


LIGHT = tokens(block(r"(?m)^:root"))
DARK_AUTO = tokens(block(r':root:not\(\[data-theme="light"\]\)'))
DARK_CHOSEN = tokens(block(r':root\[data-theme="dark"\]'))
MASTHEAD = block(r"(?m)^\.masthead")


def luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


TEXT_PAIRS = [
    *[(fg, bg) for fg in ("text", "muted", "accent", "error", "draft") for bg in ("bg", "surface")],
    ("text", "surface2"),
    ("accent", "surface2"),
    ("draft", "draft-bg"),
    ("text", "accent-soft"),
    ("on-accent", "accent"),
]
NON_TEXT_PAIRS = [
    *[(fg, bg) for fg in ("control", "focus") for bg in ("bg", "surface")],
    ("control", "surface2"),
]


def test_nfr_a11y_dark_selectors() -> None:
    assert re.search(
        r'@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)', CSS
    )
    assert DARK_AUTO == DARK_CHOSEN
    assert set(LIGHT) == set(DARK_AUTO)
    assert "color-scheme: light" in block(r"(?m)^:root")
    assert "color-scheme: dark" in block(r':root\[data-theme="dark"\]')


@pytest.mark.parametrize("theme", [LIGHT, DARK_AUTO], ids=["light", "dark"])
@pytest.mark.parametrize(("fg", "bg"), TEXT_PAIRS, ids=lambda v: v)
def test_nfr_a11y_contrast_text(theme: dict[str, str], fg: str, bg: str) -> None:
    assert contrast(theme[fg], theme[bg]) >= 4.5


@pytest.mark.parametrize("theme", [LIGHT, DARK_AUTO], ids=["light", "dark"])
@pytest.mark.parametrize(("fg", "bg"), NON_TEXT_PAIRS, ids=lambda v: v)
def test_nfr_a11y_contrast_controls_and_focus(theme: dict[str, str], fg: str, bg: str) -> None:
    assert contrast(theme[fg], theme[bg]) >= 3


def test_nfr_a11y_contrast_masthead() -> None:
    """The masthead is dark in both themes, so it scopes its own focus color."""
    ground = re.search(rf"background-color:\s*({HEX})", MASTHEAD)
    focus = tokens(MASTHEAD).get("focus")
    assert ground and focus
    assert contrast(focus, ground.group(1)) >= 3
    title = re.search(rf"\.site-name\s*\{{[^}}]*color:\s*({HEX})", CSS)
    tagline = re.search(rf"\.tagline\s*\{{[^}}]*color:\s*({HEX})", CSS)
    assert title and tagline
    assert contrast(title.group(1), ground.group(1)) >= 4.5
    assert contrast(tagline.group(1), ground.group(1)) >= 4.5


def test_nfr_a11y_contrast_family_strip() -> None:
    """The Bearing Quest strip is dark in both themes. Its border (#1C3A4F) is decoration only."""
    strip = block(r"\.bq-strip")
    ground = re.search(rf"background:\s*({HEX})", strip)
    text = re.search(rf"(?<![-\w])color:\s*({HEX})", strip)
    assert ground and text
    assert contrast(text.group(1), ground.group(1)) >= 4.5


def test_nfr_a11y_focus_ring() -> None:
    rule = r":focus-visible\s*\{\s*outline: 3px solid var\(--focus\); outline-offset: 2px;"
    assert re.search(rule, CSS)


def _same_origin(url: str) -> bool:
    parts = urlsplit(url)
    return not parts.scheme and not parts.netloc


def test_r12_fonts_self_hosted() -> None:
    urls = re.findall(r"""url\(\s*["']?([^"')]+)["']?\s*\)""", CSS)
    assert urls
    for url in urls:
        assert _same_origin(url), url
        assert (STATIC_DIR / url).is_file(), url
    assert '--sans: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;' in CSS
    for name in ("OFL-Inter.txt", "OFL-IBM-Plex-Mono.txt"):
        assert "SIL Open Font License" in (STATIC_DIR / "fonts" / name).read_text(encoding="utf-8")


class _HeadAssets(HTMLParser):
    """Every <link href> and <script src>, and whether each script sits in <head>."""

    def __init__(self) -> None:
        super().__init__()
        self.in_head = False
        self.refs: list[str] = []
        self.head_scripts: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "head":
            self.in_head = True
        if tag == "link" and values.get("href"):
            self.refs.append(values["href"] or "")
        if tag == "script" and values.get("src"):
            self.refs.append(values["src"] or "")
            if self.in_head:
                self.head_scripts.append(values)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.in_head = False


@pytest.mark.parametrize(
    "path", ["/", f"/s/{RT001_ID}", "/responses", "/about", "/privacy", "/stats"]
)
def test_r12_page_assets_are_same_origin(path: str) -> None:
    parser = _HeadAssets()
    parser.feed(client().get(path).text)
    assert parser.refs
    assert all(_same_origin(ref) for ref in parser.refs), parser.refs


def test_nfr_a11y_theme_script_runs_before_paint() -> None:
    parser = _HeadAssets()
    parser.feed(client().get("/").text)
    first = parser.head_scripts[0]
    assert (first["src"] or "").endswith("/theme.js")
    assert "defer" not in first and "async" not in first


@pytest.mark.parametrize("path", ["/", f"/s/{RT001_ID}", "/about"])
def test_nfr_a11y_theme_switch_markup(path: str) -> None:
    html = client().get(path).text
    assert '<div class="theme-switch" role="group" aria-label="Theme" hidden>' in html
    for choice, label in (("auto", "Auto"), ("light", "Light"), ("dark", "Dark")):
        assert re.search(
            rf'<button type="button" data-theme-choice="{choice}" aria-pressed="(true|false)">'
            rf"{label}</button>",
            html,
        )


def test_nfr_a11y_banner_art_is_decorative() -> None:
    home = client().get("/").text
    assert '<p class="tagline">Five findings. Two fixes. Your call.</p>' in home
    assert 'class="banner-art" aria-hidden="true" focusable="false"' in home
    assert "masthead--full" in home
    for path in (f"/s/{RT001_ID}", "/about"):
        page = client().get(path).text
        assert "masthead--slim" in page
        assert "banner-art" not in page
    for svg in re.findall(r"<svg[^>]*>", home + client().get("/about").text):
        assert 'aria-hidden="true"' in svg
