"""PRD §6 Accessibility in a real browser: the theme switch, the no-JS and blocked-storage
fallbacks, the slot pips, the selected-row style, and focus never hidden by the slot bar."""

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.web_helpers import RT001_ID, rt001

pytestmark = pytest.mark.e2e

LIGHT_BG = "rgb(244, 248, 251)"
DARK_BG = "rgb(10, 21, 32)"
LIGHT_ACCENT_SOFT = "rgb(221, 241, 244)"

BLOCK_STORAGE = """
Storage.prototype.getItem = function () { throw new DOMException("blocked", "SecurityError"); };
Storage.prototype.setItem = function () { throw new DOMException("blocked", "SecurityError"); };
"""


def body_bg(page: Page) -> str:
    return str(page.evaluate("getComputedStyle(document.body).backgroundColor"))


def data_theme(page: Page) -> str | None:
    value = page.evaluate("document.documentElement.getAttribute('data-theme')")
    return None if value is None else str(value)


def expect_pressed(page: Page, name: str) -> None:
    group = page.get_by_role("group", name="Theme")
    for label in ("Auto", "Light", "Dark"):
        expect(group.get_by_role("button", name=label)).to_have_attribute(
            "aria-pressed", "true" if label == name else "false"
        )


def test_nfr_a11y_theme_switch_persists(page: Page, base_url: str) -> None:
    page.emulate_media(color_scheme="light")
    page.goto(base_url + "/")
    group = page.get_by_role("group", name="Theme")
    expect(group).to_be_visible()
    expect_pressed(page, "Auto")
    assert body_bg(page) == LIGHT_BG

    group.get_by_role("button", name="Dark").click()
    expect_pressed(page, "Dark")
    assert data_theme(page) == "dark"
    assert body_bg(page) == DARK_BG
    page.reload()
    expect_pressed(page, "Dark")
    assert data_theme(page) == "dark"
    assert body_bg(page) == DARK_BG

    # A boosted navigation keeps the choice.
    page.get_by_role("link", name="About").click()
    expect(page).to_have_url(base_url + "/about")
    expect_pressed(page, "Dark")
    assert body_bg(page) == DARK_BG

    page.emulate_media(color_scheme="dark")
    page.get_by_role("group", name="Theme").get_by_role("button", name="Light").click()
    expect_pressed(page, "Light")
    assert body_bg(page) == LIGHT_BG  # overrides the dark device setting
    page.reload()
    expect_pressed(page, "Light")
    assert body_bg(page) == LIGHT_BG

    page.get_by_role("group", name="Theme").get_by_role("button", name="Auto").click()
    expect_pressed(page, "Auto")
    assert data_theme(page) is None
    assert body_bg(page) == DARK_BG  # follows the device again
    page.reload()
    expect_pressed(page, "Auto")
    assert body_bg(page) == DARK_BG


def test_nfr_a11y_without_javascript_follows_device(browser: Browser, base_url: str) -> None:
    context = browser.new_context(java_script_enabled=False, color_scheme="dark")
    page = context.new_page()
    page.goto(base_url + "/")
    assert body_bg(page) == DARK_BG
    expect(page.locator(".theme-switch")).to_be_hidden()
    context.close()


def test_nfr_a11y_blocked_storage_still_works(browser: Browser, base_url: str) -> None:
    context = browser.new_context(color_scheme="light")
    context.add_init_script(BLOCK_STORAGE)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.goto(base_url + "/")
    expect_pressed(page, "Auto")
    assert body_bg(page) == LIGHT_BG
    page.get_by_role("group", name="Theme").get_by_role("button", name="Dark").click()
    expect_pressed(page, "Dark")
    assert body_bg(page) == DARK_BG
    assert errors == []
    context.close()


def test_nfr_a11y_slot_pips_and_selected_row(page: Page, base_url: str) -> None:
    page.emulate_media(color_scheme="light")
    page.goto(f"{base_url}/s/{RT001_ID}")
    pips = page.locator(".slot-pips .pip")
    expect(pips).to_have_count(2)
    expect(page.locator(".slot-pips .pip.is-filled")).to_have_count(0)
    page.locator("#F1-mitigate_remediate").check()
    expect(page.locator(".slot-pips .pip.is-filled")).to_have_count(1)
    page.locator("#F2-mitigate_remediate").check()
    expect(page.locator(".slot-pips .pip.is-filled")).to_have_count(2)
    page.locator("#F2-transfer").check()
    expect(page.locator(".slot-pips .pip.is-filled")).to_have_count(1)

    row = page.locator(".choice").filter(has=page.locator("#F1-mitigate_remediate"))
    expect(row).to_have_css("background-color", LIGHT_ACCENT_SOFT)
    expect(row).to_have_css("border-top-width", "2px")
    expect(row).to_have_css("border-top-color", "rgb(0, 106, 122)")
    unselected = page.locator(".choice").filter(has=page.locator("#F1-avoid"))
    expect(unselected).to_have_css("border-top-width", "1px")
    expect(unselected).to_have_css("border-top-color", "rgb(94, 116, 136)")  # --control
    for choice in (row, unselected):
        box = choice.bounding_box()
        assert box is not None and box["height"] >= 48
    # Clicking the label side of the row selects it.
    page.locator("label[for='F3-transfer']").click(position={"x": 200, "y": 10})
    expect(page.locator("#F3-transfer")).to_be_checked()


# Each field's checked radio, then its rationale, in tab order. F1 and F2 use both remediation
# slots, so the bar shows its longest message and is at its tallest.
ANSWERS = {
    "F1": "mitigate_remediate",
    "F2": "mitigate_remediate",
    "F3": "transfer",
    "F4": "transfer",
    "F5": "transfer",
}
TAB_ORDER = [f"{fid}-{field}" for fid, value in ANSWERS.items() for field in (value, "rationale")]

# Put the target 5px below the top of the viewport (on screen, under the stuck bar), focus the
# next field without scrolling, then Shift+Tab back onto the target. A browser only scrolls a
# field it thinks is hidden, so without scroll-padding-top the target stays under the bar.
PLACE_UNDER_BAR = """([target, next]) => {
    const t = document.getElementById(target);
    window.scrollTo(0, t.getBoundingClientRect().top + window.scrollY - 5);
    document.getElementById(next).focus({preventScroll: true});
}"""
MEASURE = """() => {
    const el = document.activeElement;
    const r = el.getBoundingClientRect();
    const bar = document.querySelector('.slot-bar').getBoundingClientRect();
    return {id: el.id, top: r.top, bottom: r.bottom, barTop: bar.top, barBottom: bar.bottom,
            height: window.innerHeight};
}"""


@pytest.mark.parametrize("width", [1280, 390])
def test_nfr_a11y_focus_not_obscured(browser: Browser, base_url: str, width: int) -> None:
    """WCAG 2.4.11: Shift+Tab back up the form never leaves focus under the sticky slot bar."""
    context = browser.new_context(viewport={"width": width, "height": 720})
    page = context.new_page()
    page.goto(f"{base_url}/s/{RT001_ID}")
    expect(page.locator('form[data-ready="1"]')).to_be_attached()
    for fid, value in ANSWERS.items():
        page.locator(f"#{fid}-{value}").check()
    expect(page.locator("#slot-status")).to_contain_text("remediate is disabled")
    for target, following in zip(TAB_ORDER, [*TAB_ORDER[1:], "note"], strict=True):
        page.evaluate(PLACE_UNDER_BAR, [target, following])
        page.keyboard.press("Shift+Tab")
        state = page.evaluate(MEASURE)
        assert state["id"] == target, state
        assert state["barTop"] == 0, state  # the bar is stuck to the top
        assert state["top"] >= state["barBottom"], state
        assert state["bottom"] <= state["height"], state
    context.close()


def chromium_names(page: Page) -> list[str]:
    """Heading and link names from Chromium's own accessibility tree (not Playwright's)."""
    session = page.context.new_cdp_session(page)
    tree = session.send("Accessibility.getFullAXTree")
    session.detach()
    names = []
    for node in tree["nodes"]:
        role = node.get("role", {}).get("value")
        name = node.get("name", {}).get("value")
        if role in ("heading", "link") and name:
            names.append(str(name))
    return names


def test_nfr_a11y_accessible_names(page: Page, base_url: str) -> None:
    """WCAG 2.5.3: each name starts with the visible text, with no stray space before ':'."""
    scenario = rt001()
    page.goto(base_url + "/")
    expect(
        page.get_by_role("link", name=f"Start scenario: {scenario.title}", exact=True)
    ).to_be_visible()
    home_names = chromium_names(page)
    assert f"Start scenario: {scenario.title}" in home_names

    page.goto(f"{base_url}/s/{RT001_ID}")
    for finding in scenario.findings:
        expect(
            page.get_by_role("heading", name=f"{finding.id}: {finding.title}", exact=True)
        ).to_be_visible()
    exercise_names = chromium_names(page)
    for finding in scenario.findings:
        assert f"{finding.id}: {finding.title}" in exercise_names
    for name in home_names + exercise_names:
        assert " :" not in name, name


@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_r18_draft_pill_sits_under_the_title(
    browser: Browser, preview_base_url: str, width: int, scheme: str
) -> None:
    context = browser.new_context(viewport={"width": width, "height": 844}, color_scheme=scheme)
    page = context.new_page()
    page.goto(preview_base_url + "/")
    gap = page.evaluate(
        """() => {
            const pill = document.querySelector('.scenario-card > .tag-draft');
            const title = pill.closest('.scenario-card').querySelector('h3');
            return pill.getBoundingClientRect().top - title.getBoundingClientRect().bottom;
        }"""
    )
    assert 0 <= gap <= 12, gap
    context.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_nfr_a11y_no_horizontal_scroll_at_390(browser: Browser, base_url: str, scheme: str) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme=scheme)
    page = context.new_page()
    for path in ("/", f"/s/{RT001_ID}", "/responses", "/about", "/privacy", "/stats"):
        page.goto(base_url + path)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        ), path
    context.close()
