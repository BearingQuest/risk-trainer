"""R22 — the stats page in a real browser: CSP-clean, accessible tables, both themes."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from playwright.sync_api import Browser, expect

from risk_trainer.domain.treatments import Approver, Treatment
from risk_trainer.storage.attempts import AttemptRecord, Choice
from risk_trainer.storage.memory import MemoryAttemptStore
from risk_trainer.web.app import create_app
from tests.e2e.conftest import _serve
from tests.web_helpers import RT001_ID, rt001, settings

pytestmark = pytest.mark.e2e

EXPERT = {
    "F1": Treatment.MITIGATE_REMEDIATE,
    "F2": Treatment.MITIGATE_COMPENSATE,
    "F3": Treatment.TRANSFER,
    "F4": Treatment.MITIGATE_REMEDIATE,
    "F5": Treatment.ACCEPT,
}


@pytest.fixture(scope="module")
def stats_url() -> Iterator[str]:
    store = MemoryAttemptStore()
    for n in range(12):
        approver = Approver.SECURITY_TEAM if n < 3 else Approver.BUSINESS_RISK_OWNER
        choices = tuple(
            Choice(fid, t, approver if t is Treatment.ACCEPT else None) for fid, t in EXPERT.items()
        )
        store.add_to_month(
            AttemptRecord(
                f"e2e-{n:04d}-xxxxxxxxxx", RT001_ID, 1, choices, 10, 10, datetime.now(UTC)
            )
        )
    app = create_app(settings(session_cookie_secure=False), store, [rt001()])
    yield from _serve(app)


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_r22_stats_page_renders_without_console_errors(
    browser: Browser, stats_url: str, scheme: str
) -> None:
    context = browser.new_context(color_scheme=scheme)
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.goto(stats_url + "/stats")
    expect(page.get_by_role("heading", level=1, name="Learner stats")).to_be_visible()
    expect(page.get_by_role("table", name="Attempts by difficulty")).to_be_visible()
    expect(page.get_by_role("table", name="How learners answered each finding")).to_be_visible()
    expect(page.get_by_role("rowheader", name="Foundational")).to_be_visible()
    expect(page.get_by_text("12 attempts. Median score: 10 of 10 points.")).to_be_visible()
    expect(page.get_by_text("of learners who chose accept, 25% named")).to_be_visible()
    assert errors == []
    context.close()


def test_r22_nav_link_reaches_stats(browser: Browser, stats_url: str) -> None:
    page = browser.new_page()
    page.goto(stats_url + "/")
    page.get_by_role("navigation", name="Main").get_by_role("link", name="Learner stats").click()
    expect(page).to_have_url(stats_url + "/stats")
    page.close()
