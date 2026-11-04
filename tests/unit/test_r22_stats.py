"""R22 — public stats page: window, minimum sample, totals only, rounding, cache, fail-open."""

import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from risk_trainer.config import Settings
from risk_trainer.domain.models import Difficulty
from risk_trainer.domain.peers import DEFAULT_PEER_MIN_SAMPLE, counter_name
from risk_trainer.domain.stats import (
    STATS_FIRST_MONTH,
    approver_counter_name,
    bucket_expires_at,
    build_stats,
    month_label,
    scenario_figures,
    score_counter_name,
    window_months,
)
from risk_trainer.domain.treatments import Approver, Treatment
from risk_trainer.storage.attempts import AttemptRecord, Choice, PeerCounts, StorageError
from risk_trainer.storage.memory import MemoryAttemptStore
from risk_trainer.web.routes.stats import STATS_CACHE_TTL, STATS_FAILURE_TTL, StatsCache
from tests.web_helpers import EXPERT_ANSWERS, RT001_ID, client, form_fields, rt001, submit

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
EXPERT = {
    "F1": Treatment.MITIGATE_REMEDIATE,
    "F2": Treatment.MITIGATE_COMPENSATE,
    "F3": Treatment.TRANSFER,
    "F4": Treatment.MITIGATE_REMEDIATE,
    "F5": Treatment.ACCEPT,
}


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def attempt(
    n: int,
    when: datetime = NOW,
    *,
    scenario_id: str = RT001_ID,
    score: int = 10,
    f1: Treatment = Treatment.MITIGATE_REMEDIATE,
    f5_approver: Approver = Approver.BUSINESS_RISK_OWNER,
) -> AttemptRecord:
    choices = [
        Choice(fid, f1 if fid == "F1" else t, f5_approver if t is Treatment.ACCEPT else None)
        for fid, t in EXPERT.items()
    ]
    return AttemptRecord(
        f"submit-{n:04d}-xxxxxxxx", scenario_id, 1, tuple(choices), score, 10, when
    )


def seed(store: MemoryAttemptStore, count: int, when: datetime = NOW, start: int = 0) -> None:
    for n in range(start, start + count):
        store.add_to_month(attempt(n, when))


def stats_page(store: MemoryAttemptStore, now: datetime = NOW, **settings: object) -> str:
    test_client = client(store=store, **settings)
    test_client.app.state.stats_cache = StatsCache(Clock(now))  # type: ignore[attr-defined]
    response = test_client.get("/stats")
    assert response.status_code == 200
    return response.text.replace("&#39;", "'")


# Minimum sample over the window total


def test_r22_uses_the_peer_minimum_sample_setting() -> None:
    assert Settings(storage_backend="memory", session_secret="x" * 32).peer_min_sample == (
        DEFAULT_PEER_MIN_SAMPLE
    )
    assert DEFAULT_PEER_MIN_SAMPLE == 10


def test_r22_nine_attempts_show_nothing() -> None:
    store = MemoryAttemptStore()
    seed(store, 9)
    html = stats_page(store)
    assert "Not enough attempts yet. Figures appear at 10 attempts." in html
    assert "Median score" not in html
    assert not re.search(r"\d+%", html)
    assert "No scenario has 10 attempts in this window yet." in html
    assert ">9<" not in html and "9 attempts" not in html


def test_r22_ten_attempts_show_totals() -> None:
    store = MemoryAttemptStore()
    seed(store, 10)
    html = stats_page(store)
    assert "10 attempts. Median score: 10 of 10 points." in html
    assert "10 attempts on scenarios with at least 10 attempts." in html
    assert "Not enough attempts yet. Figures appear" not in html


def test_r22_minimum_applies_to_window_total_not_single_months() -> None:
    store = MemoryAttemptStore()
    seed(store, 5, datetime(2027, 1, 20, tzinfo=UTC))
    seed(store, 5, datetime(2027, 2, 3, tzinfo=UTC), start=5)
    html = stats_page(store, now=datetime(2027, 2, 10, tzinfo=UTC))
    assert "10 attempts. Median score" in html


def test_r22_months_outside_the_window_are_ignored() -> None:
    store = MemoryAttemptStore()
    seed(store, 10, datetime(2027, 1, 5, tzinfo=UTC))  # seven months before July
    seed(store, 3, datetime(2027, 7, 5, tzinfo=UTC), start=10)
    html = stats_page(store, now=datetime(2027, 7, 20, tzinfo=UTC))
    assert "Median score" not in html


def test_r22_window_is_six_months_from_the_first_month() -> None:
    assert window_months(NOW) == ("2026-11",)
    assert window_months(datetime(2027, 1, 31, 23, 59, tzinfo=UTC)) == (
        "2026-11",
        "2026-12",
        "2027-01",
    )
    assert window_months(datetime(2027, 7, 1, tzinfo=UTC)) == (
        "2027-02",
        "2027-03",
        "2027-04",
        "2027-05",
        "2027-06",
        "2027-07",
    )
    assert window_months(datetime(2026, 10, 31, tzinfo=UTC)) == ()
    assert STATS_FIRST_MONTH == "2026-11"


def test_r22_since_label() -> None:
    assert "Totals since November 2026." in stats_page(MemoryAttemptStore())
    later = stats_page(MemoryAttemptStore(), now=datetime(2027, 7, 1, tzinfo=UTC))
    assert "Totals from the last six calendar months, since February 2027." in later
    assert month_label("2027-02") == "February 2027"


def test_r22_bucket_ttl_is_about_seven_months() -> None:
    assert bucket_expires_at("2026-11") == int(datetime(2027, 6, 1, tzinfo=UTC).timestamp())
    assert bucket_expires_at("2027-06") == int(datetime(2028, 1, 1, tzinfo=UTC).timestamp())


def test_r22_site_totals_count_only_scenarios_that_reached_the_minimum() -> None:
    rt002 = rt001(id="rt-002-other-one", difficulty="advanced", title="Second one")
    totals = {RT001_ID: (12, {}), "rt-002-other-one": (9, {})}
    site = build_stats([rt001(), rt002], totals, 10, ("2026-11",))
    assert site.total == 12
    assert dict(site.by_difficulty) == {
        Difficulty.FOUNDATIONAL: 12,
        Difficulty.INTERMEDIATE: None,
        Difficulty.ADVANCED: None,
    }
    assert site.scenarios[1].figures is None


# Figures


def test_r22_percentages_are_whole_and_rounded() -> None:
    counters = {
        counter_name("F1", Treatment.MITIGATE_REMEDIATE): 10,
        counter_name("F1", Treatment.AVOID): 20,
        score_counter_name(10): 30,
    }
    figures = scenario_figures(rt001(), 30, counters, 10)
    assert figures is not None
    f1 = figures.findings[0]
    assert f1.preferred_percent == 33
    assert f1.other is not None
    assert (f1.other.treatment, f1.other.percent) == (Treatment.AVOID, 67)


def test_r22_page_shows_only_whole_percentages() -> None:
    store = MemoryAttemptStore()
    for n in range(12):  # F1: 8 of 12 chose the expert answer, 4 of 12 chose avoid
        store.add_to_month(
            attempt(n, f1=Treatment.AVOID if n < 4 else Treatment.MITIGATE_REMEDIATE)
        )
    html = stats_page(store)
    assert "<td>67%</td>" in html
    assert "(33%)" in html
    assert not re.search(r"\d+[.,]\d+\s*%", html)


def test_r22_most_common_other_choice_ties_and_none() -> None:
    tie = {
        counter_name("F1", Treatment.MITIGATE_REMEDIATE): 8,
        counter_name("F1", Treatment.TRANSFER): 1,
        counter_name("F1", Treatment.AVOID): 1,
    }
    figures = scenario_figures(rt001(), 10, tie, 10)
    assert figures is not None
    assert figures.findings[0].other is not None
    assert figures.findings[0].other.treatment is Treatment.AVOID  # first in Treatment order
    assert figures.findings[1].other is None  # nobody answered F2 at all


def test_r22_median_and_score_bands() -> None:
    scores = {score_counter_name(4): 3, score_counter_name(7): 3, score_counter_name(10): 4}
    figures = scenario_figures(rt001(), 10, scores, 10)
    assert figures is not None
    assert figures.median == 7
    assert [(b.label, b.percent) for b in figures.bands] == [
        ("90 to 100%", 40),
        ("70 to 89%", 30),
        ("50 to 69%", 0),
        ("Under 50%", 30),
    ]


def test_r22_trap_rate_counts_security_and_it_operations() -> None:
    counters = {
        counter_name("F5", Treatment.ACCEPT): 10,
        approver_counter_name("F5", Approver.SECURITY_TEAM): 2,
        approver_counter_name("F5", Approver.IT_OPERATIONS): 1,
        approver_counter_name("F5", Approver.BUSINESS_RISK_OWNER): 6,
        approver_counter_name("F5", Approver.SENIOR_MANAGEMENT): 1,
    }
    figures = scenario_figures(rt001(), 12, counters, 10)
    assert figures is not None
    f5 = figures.findings[4]
    assert f5.accept_preferred and f5.trap_percent == 30
    assert not figures.findings[0].accept_preferred and figures.findings[0].trap_percent is None


def test_r22_trap_rate_needs_the_minimum_accept_answers() -> None:
    counters = {
        counter_name("F5", Treatment.ACCEPT): 9,
        approver_counter_name("F5", Approver.SECURITY_TEAM): 9,
    }
    figures = scenario_figures(rt001(), 12, counters, 10)
    assert figures is not None
    assert figures.findings[4].accept_preferred and figures.findings[4].trap_percent is None


def test_r22_page_shows_trap_rate() -> None:
    store = MemoryAttemptStore()
    for n in range(10):
        approver = Approver.SECURITY_TEAM if n < 4 else Approver.BUSINESS_RISK_OWNER
        store.add_to_month(attempt(n, f5_approver=approver))
    assert "of learners who chose accept, 40% named the security team" in stats_page(store)


# Privacy and HTTP


def test_r22_no_identifiers_timestamps_or_free_text_in_page() -> None:
    marker, note = "RATIONALE-MARKER-789", "NOTE-MARKER-987"
    test_client = client(peer_min_sample=1)
    submit_ids = []
    for _ in range(2):
        fields = form_fields(test_client.get(f"/s/{RT001_ID}").text)
        submit_ids.append(fields["submit_id"])
        answers = {**EXPERT_ANSWERS, "F5.rationale": marker, "note": note}
        assert test_client.post(f"/s/{RT001_ID}", data={**fields, **answers}).status_code == 200
    cookie = test_client.cookies.get("rt_session")
    assert cookie

    html = test_client.get("/stats").text
    assert "2 attempts. Median score" in html
    for secret in (marker, note, *submit_ids, cookie):
        assert secret not in html
    assert not re.search(r"\d{4}-\d{2}-\d{2}", html)  # no dates or timestamps
    assert not re.search(r"\d{4}-\d{2}(?!\d)", html)  # no raw month keys either
    assert not re.search(r"\d{1,2}:\d{2}", html)  # no times of day


def test_r22_post_refused() -> None:
    assert client().post("/stats").status_code == 405


def test_r22_nav_links_stats_on_every_page() -> None:
    for path in ("/", f"/s/{RT001_ID}", "/about", "/privacy", "/stats"):
        assert '<a href="/stats">Learner stats</a>' in client().get(path).text


def test_r22_caveats_on_page() -> None:
    html = stats_page(MemoryAttemptStore())
    for caveat in (
        "Learners chose to try these scenarios",
        "include the site owner's own test attempts",
        "rolling window of about six months",
        "This is a learning tool, not research.",
        "at least 10 attempts in the window",
    ):
        assert caveat in html


def test_r22_privacy_page_describes_stats_and_threshold() -> None:
    html = client().get("/privacy").text.replace("&#39;", "'")
    monthly = html[html.index('id="privacy-monthly"') :]
    assert "About 7 months" in monthly[: monthly.index("</tr>")]
    stats_row = html[html.index('id="privacy-stats"') :]
    assert "at least 10 attempts" in stats_row[: stats_row.index("</tr>")]
    answers = html[html.index('id="privacy-attempts"') :]
    assert "the stats page reads those totals, not the attempts" in answers


def test_r22_draft_scenarios_not_counted() -> None:
    store = MemoryAttemptStore()
    seed(store, 10)
    test_client = client([rt001(status="draft")], store, preview=True)
    test_client.app.state.stats_cache = StatsCache(Clock(NOW))  # type: ignore[attr-defined]
    assert "Median score" not in test_client.get("/stats").text


# Cache and storage


class SpyStore(MemoryAttemptStore):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.fail_reads = False
        self.fail_bucket = False

    def window_counts(self, scenario_id: str, version: int, months: Sequence[str]) -> PeerCounts:
        self.reads += 1
        if self.fail_reads:
            raise StorageError("throttled")
        return super().window_counts(scenario_id, version, months)

    def add_to_month(self, attempt: AttemptRecord) -> None:
        if self.fail_bucket:
            raise StorageError("throttled")
        super().add_to_month(attempt)


def _cached_client(store: SpyStore, clock: Clock):  # type: ignore[no-untyped-def]
    test_client = client(store=store)
    test_client.app.state.stats_cache = StatsCache(clock)  # type: ignore[attr-defined]
    return test_client


def test_r22_cache_ttl_five_minutes() -> None:
    assert timedelta(minutes=5) == STATS_CACHE_TTL
    store, clock = SpyStore(), Clock(NOW)
    test_client = _cached_client(store, clock)
    assert test_client.get("/stats").status_code == 200
    assert store.reads == 1
    clock.now = NOW + timedelta(seconds=299)
    test_client.get("/stats")
    assert store.reads == 1
    clock.now = NOW + timedelta(seconds=300)
    test_client.get("/stats")
    assert store.reads == 2


def test_r22_storage_failure_is_503_and_cached_30_seconds() -> None:
    assert timedelta(seconds=30) == STATS_FAILURE_TTL
    store, clock = SpyStore(), Clock(NOW)
    store.fail_reads = True
    test_client = _cached_client(store, clock)
    first = test_client.get("/stats")
    assert first.status_code == 503
    assert "Stats are unavailable right now." in first.text
    assert "Learners chose to try these scenarios" in first.text
    clock.now = NOW + timedelta(seconds=29)
    assert test_client.get("/stats").status_code == 503
    assert store.reads == 1
    store.fail_reads = False
    clock.now = NOW + timedelta(seconds=30)
    assert test_client.get("/stats").status_code == 200
    assert store.reads == 2
    clock.now = NOW + timedelta(seconds=30 + 299)
    test_client.get("/stats")
    assert store.reads == 2


def test_r22_bucket_failure_fails_open(caplog: pytest.LogCaptureFixture) -> None:
    store = SpyStore()
    store.fail_bucket = True
    marker = "RATIONALE-MARKER-321"
    test_client = client(store=store, peer_min_sample=1)
    logger = logging.getLogger("risk_trainer")  # create_app replaced its handlers
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.DEBUG, logger="risk_trainer"):
            response = submit(test_client, {**EXPERT_ANSWERS, "F5.rationale": marker})
    finally:
        logger.removeHandler(caplog.handler)
    assert response.status_code == 200
    assert "10 of 10 points" in response.text
    assert "Based on 1 attempts" in response.text  # peers still shown
    assert store.peer_counts(RT001_ID, 1).attempts == 1  # the attempt was saved
    assert any(getattr(r, "event", None) == "stats_bucket_error" for r in caplog.records)
    assert marker not in caplog.text + " ".join(str(r.__dict__) for r in caplog.records)


def test_r22_submission_adds_to_month_once() -> None:
    store = MemoryAttemptStore()
    test_client = client(store=store)
    page = test_client.get(f"/s/{RT001_ID}").text
    fields = form_fields(page)
    for _ in range(2):  # the same submit_id twice
        assert test_client.post(f"/s/{RT001_ID}", data={**fields, **EXPERT_ANSWERS}).is_success
    months = window_months(datetime.now(UTC))
    counts = store.window_counts(RT001_ID, 1, months)
    assert counts.attempts == 1
    assert counts.counters[approver_counter_name("F5", Approver.BUSINESS_RISK_OWNER)] == 1
    assert counts.counters[score_counter_name(10)] == 1
