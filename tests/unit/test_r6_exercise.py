"""R6 — the exercise page shows everything needed and labels every input."""

import re
from html.parser import HTMLParser

from tests.web_helpers import RT001_ID, client, rt001

SCENARIO = rt001()


def page() -> str:
    return client().get(f"/s/{RT001_ID}").text


def test_r6_shows_context_and_capacity() -> None:
    html = page().replace("&#39;", "'")
    context = SCENARIO.context
    for text in (context.organization, context.industry, context.size, context.risk_appetite):
        assert text in html
    for constraint in context.constraints:
        assert constraint in html
    assert "Remediation capacity: 2 findings." in html


def test_r6_page_before_submission_holds_no_answer_key_text() -> None:
    html = page().replace("&#39;", "'").replace("&#34;", '"').replace("&amp;", "&")
    key = SCENARIO.answer_key
    secrets = [key.overall_debrief, key.job_tip, key.exam_tip, *key.common_traps]
    for entry in key.findings.values():
        secrets += [entry.expert_rationale, *entry.key_considerations, *entry.why_not.values()]
    for text in secrets:
        if text:
            assert text not in html


def test_r6_shows_all_five_findings_with_signals() -> None:
    html = page().replace("&#39;", "'")
    for finding in SCENARIO.findings:
        assert f'id="finding-{finding.id}"' in html
        assert finding.title in html
        assert finding.asset in html
        assert finding.signals.business_owner in html
        for control in finding.signals.compensating_controls_available:
            assert control in html
    for label in (
        "CVSS base score",
        "Known to be exploited",
        "Data involved",
        "Remediation effort",
    ):
        assert html.count(label) == 5


def test_r6_one_required_radio_group_per_finding() -> None:
    html = page()
    for finding in SCENARIO.findings:
        radios = re.findall(rf'<input type="radio"[^>]*name="{finding.id}\.treatment"[^>]*>', html)
        assert len(radios) == 5
        assert sum(" required" in r for r in radios) == 1


def test_r6_accept_fields_present_with_limits() -> None:
    html = page()
    for finding in SCENARIO.findings:
        assert f'name="{finding.id}.approver"' in html
        assert re.search(rf'name="{finding.id}\.rationale" maxlength="600"', html)
    assert 'name="note" maxlength="1200"' in html


class _Inputs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.label_for: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in ("input", "select", "textarea") and values.get("type") != "hidden":
            self.ids.append(values.get("id") or "")
        if tag == "label" and values.get("for"):
            self.label_for.add(values["for"] or "")


def test_r6_every_input_has_a_label() -> None:
    parser = _Inputs()
    parser.feed(page())
    assert parser.ids
    assert all(parser.ids)
    assert set(parser.ids) <= parser.label_for


def test_r6_form_carries_slot_count_for_the_browser() -> None:
    assert 'data-slots="2"' in page()
    assert 'id="slot-status" class="slot-status" aria-live="polite"' in page()
