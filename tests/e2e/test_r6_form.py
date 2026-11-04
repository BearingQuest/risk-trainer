"""R6 — the exercise form in a real browser: keyboard only, 360 px, slot limit, accept fields."""

import time

import pytest
from playwright.sync_api import Browser, Page, Route, expect

from tests.e2e.flows import answer_all_transfer
from tests.web_helpers import RT001_ID

pytestmark = pytest.mark.e2e


def tab_to(page: Page, element_id: str, limit: int = 300) -> None:
    """Press Tab until the element has focus, proving it's reachable by keyboard."""
    for _ in range(limit):
        if page.evaluate("document.activeElement && document.activeElement.id") == element_id:
            return
        page.keyboard.press("Tab")
    raise AssertionError(f"#{element_id} not reachable with Tab")


def no_horizontal_scroll(page: Page) -> bool:
    return bool(
        page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
    )


def test_r6_complete_scenario_by_keyboard_only(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/s/{RT001_ID}")
    # From each group's first radio ("avoid"), ArrowDown moves through the list in order:
    # avoid, remediate, compensate, transfer, accept. By F5 both slots are used, so its
    # disabled "remediate" is skipped and accept is three presses away.
    for fid, downs in (("F1", 1), ("F2", 2), ("F3", 3), ("F4", 1), ("F5", 3)):
        tab_to(page, f"{fid}-avoid")
        page.keyboard.press("Space")
        for _ in range(downs):
            page.keyboard.press("ArrowDown")
    expect(page.locator("#F5-accept")).to_be_checked()
    tab_to(page, "F5-approver")
    page.keyboard.type("Business")
    tab_to(page, "F5-rationale")
    page.keyboard.type("The owner accepts this small residual risk.")
    page.keyboard.press("Tab")  # to the note
    page.keyboard.press("Tab")  # privacy link
    page.keyboard.press("Tab")  # submit button
    page.keyboard.press("Enter")
    expect(page.locator("#score")).to_contain_text("10 of 10 points (100%)")


def test_r6_usable_at_360px(browser: Browser, base_url: str) -> None:
    context = browser.new_context(viewport={"width": 360, "height": 780})
    page = context.new_page()
    for path in ("/", f"/s/{RT001_ID}", "/responses", "/about", "/privacy", "/stats"):
        page.goto(base_url + path)
        assert no_horizontal_scroll(page), path
    page.goto(f"{base_url}/s/{RT001_ID}")
    for choice in ("F1-mitigate_remediate", "F2-avoid", "F3-transfer", "F4-mitigate_remediate"):
        page.locator(f"#{choice}").check()
    page.locator("#F5-accept").check()
    page.locator("#F5-approver").select_option("senior_management")
    page.locator("#F5-rationale").fill("Owner signs off on this residual risk.")
    page.get_by_role("button", name="Submit my answers").click()
    expect(page.locator("#score")).to_be_visible()
    assert no_horizontal_scroll(page), "result page"
    context.close()


def test_r6_remediate_disabled_at_slot_limit_with_reason(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/s/{RT001_ID}")
    page.locator("#F1-mitigate_remediate").check()
    expect(page.locator("#F3-mitigate_remediate")).to_be_enabled()
    page.locator("#F2-mitigate_remediate").check()
    expect(page.locator("#F3-mitigate_remediate")).to_be_disabled()
    expect(page.locator("#slot-status")).to_contain_text("remediate is disabled")
    page.locator("#F2-transfer").check()
    expect(page.locator("#F3-mitigate_remediate")).to_be_enabled()


def test_r6_accept_reveals_required_approver(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/s/{RT001_ID}")
    approver = page.locator("#F5-approver")
    expect(approver).to_be_hidden()
    page.locator("#F5-accept").check()
    expect(approver).to_be_visible()
    expect(approver).to_have_attribute("required", "")
    expect(page.locator("#F5-rationale")).to_have_attribute("minlength", "10")


def test_r6_form_works_without_javascript(browser: Browser, base_url: str) -> None:
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(f"{base_url}/s/{RT001_ID}")
    for fid in ("F1", "F2", "F3", "F4", "F5"):
        page.locator(f"#{fid}-mitigate_remediate").check()
    page.get_by_role("button", name="Submit my answers").click()
    expect(page.locator("#error-summary")).to_contain_text("capacity for 2")
    context.close()


def test_r12_answers_survive_slow_scenario_load(page: Page, base_url: str) -> None:
    """The smoke test's steps hold up when the scenario page is slow (a cold Lambda)."""

    def slow_get(route: Route) -> None:
        if route.request.method == "GET":
            time.sleep(2)
        route.continue_()

    page.goto(f"{base_url}/")
    page.route("**/s/*", slow_get)
    page.locator('a[href^="/s/"]').first.click()
    answer_all_transfer(page)
    page.get_by_role("button", name="Submit my answers").click()
    expect(page.locator("#score")).to_contain_text("points")
