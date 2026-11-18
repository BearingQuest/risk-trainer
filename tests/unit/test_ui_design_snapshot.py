"""UI-01 and UI-04 — docs/design.md and the docs/design/ snapshot exist, and tokens.json holds
the same custom properties as app.css in both themes."""

import hashlib
import json
import re
from pathlib import Path

import pytest

from risk_trainer.web.app import STATIC_DIR

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs" / "design"
CSS = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
TOKENS = json.loads((DESIGN / "tokens.json").read_text(encoding="utf-8"))

LOCKUP_SHA256 = "723322e0e64f7e6e91877b5122746f09a9f4e6198e7b62910b25097e3d67b9d5"
SCREENS = [
    f"{name}-{theme}.png"
    for name in ("home", "exercise", "debrief", "preview")
    for theme in ("light", "dark")
]


def custom_properties(selector_pattern: str) -> dict[str, str]:
    """Every `--name: value;` in the one rule that matches the selector."""
    match = re.search(selector_pattern + r"\s*\{([^{}]*)\}", CSS)
    assert match, selector_pattern
    found = re.findall(r"--([\w-]+):\s*([^;]+);", match.group(1))
    assert found, selector_pattern
    return {name: " ".join(value.split()) for name, value in found}


LIGHT = custom_properties(r"(?m)^:root")
DARK_AUTO = custom_properties(r':root:not\(\[data-theme="light"\]\)')
DARK_CHOSEN = custom_properties(r':root\[data-theme="dark"\]')


def test_ui04_light_tokens_match_app_css() -> None:
    assert TOKENS["themes"]["light"] == LIGHT


def test_ui04_dark_tokens_match_app_css_auto_block() -> None:
    assert TOKENS["themes"]["dark"] == DARK_AUTO


def test_ui04_dark_tokens_match_app_css_chosen_block() -> None:
    assert TOKENS["themes"]["dark"] == DARK_CHOSEN


def test_ui04_every_token_has_a_usage_note() -> None:
    assert set(TOKENS["usage"]) == set(TOKENS["themes"]["light"])


def test_ui01_design_doc_and_snapshot_files_exist() -> None:
    assert (ROOT / "docs" / "design.md").read_text(encoding="utf-8").startswith("# ")
    for name in ("tokens.json", "bearing-quest-lockup.svg", "app-reference.css"):
        assert (DESIGN / name).is_file(), name


def test_ui01_lockup_copy_matches_the_pinned_static_file() -> None:
    copy = (DESIGN / "bearing-quest-lockup.svg").read_bytes()
    assert hashlib.sha256(copy).hexdigest() == LOCKUP_SHA256
    assert copy == (STATIC_DIR / "bearing-quest-lockup.svg").read_bytes()


@pytest.mark.parametrize("name", SCREENS)
def test_ui01_screen_is_a_png(name: str) -> None:
    assert (DESIGN / "screens" / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_ui01_agents_md_points_ui_work_at_the_design_doc() -> None:
    agents = " ".join((ROOT / "AGENTS.md").read_text(encoding="utf-8").split())
    assert "UI work follows docs/design.md" in agents
