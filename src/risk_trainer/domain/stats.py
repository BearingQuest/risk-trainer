"""Public learner stats from monthly totals (PRD R22). Pure: no I/O.

Each submission adds one to a monthly bucket for its scenario version. The stats page sums the
buckets in a rolling window of six calendar months and shows totals only. A scenario shows
nothing until its window total reaches the peer minimum sample; single months are never checked
on their own. Site-wide and per-difficulty totals count only scenarios that reached it, so a
hidden scenario can't be worked out by subtraction.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from risk_trainer.domain.models import Difficulty, Scenario
from risk_trainer.domain.peers import counter_name
from risk_trainer.domain.scoring import PREFERRED_POINTS
from risk_trainer.domain.treatments import Approver, Treatment

# Must equal the month this change first deploys (docs/decisions.md, 2026-11-03). There is
# no backfill, so the page counts from here.
STATS_FIRST_MONTH = "2026-11"
WINDOW_MONTHS = 6
BUCKET_TTL_MONTHS = 7
# Acceptance is the risk owner's or senior management's decision; these two are the trap.
TRAP_APPROVERS: tuple[Approver, ...] = (Approver.SECURITY_TEAM, Approver.IT_OPERATIONS)
# (label, lowest percent of the maximum score in the band)
SCORE_BANDS: tuple[tuple[str, int], ...] = (
    ("90 to 100%", 90),
    ("70 to 89%", 70),
    ("50 to 69%", 50),
    ("Under 50%", 0),
)
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# Window totals per scenario ID: (attempts, counters).
WindowTotals = Mapping[str, tuple[int, Mapping[str, int]]]


@dataclass(frozen=True, slots=True)
class OtherChoice:
    treatment: Treatment
    percent: int


@dataclass(frozen=True, slots=True)
class FindingStats:
    finding_id: str
    title: str
    preferred: Treatment
    preferred_percent: int
    # The most common non-preferred treatment, or None if nobody chose one.
    other: OtherChoice | None
    accept_preferred: bool
    # Of learners who chose accept, the share naming a trap approver. None unless accept is
    # preferred and at least the minimum sample chose accept.
    trap_percent: int | None


@dataclass(frozen=True, slots=True)
class ScoreBand:
    label: str
    percent: int


@dataclass(frozen=True, slots=True)
class ScenarioFigures:
    attempts: int
    median: int
    maximum: int
    bands: tuple[ScoreBand, ...]
    findings: tuple[FindingStats, ...]


@dataclass(frozen=True, slots=True)
class ScenarioStats:
    scenario_id: str
    title: str
    difficulty: Difficulty
    # None below the minimum sample: nothing else about the scenario is shown.
    figures: ScenarioFigures | None


@dataclass(frozen=True, slots=True)
class SiteStats:
    since: str
    full_window: bool
    min_sample: int
    # Totals over scenarios that reached the minimum; None if none has.
    total: int | None
    by_difficulty: tuple[tuple[Difficulty, int | None], ...]
    scenarios: tuple[ScenarioStats, ...]

    @property
    def since_label(self) -> str:
        return month_label(self.since)


def month_key(moment: datetime) -> str:
    """The UTC calendar month of a moment, e.g. "2026-11"."""
    utc = moment.astimezone(UTC)
    return f"{utc.year:04d}-{utc.month:02d}"


def shift_month(month: str, delta: int) -> str:
    year, number = (int(part) for part in month.split("-"))
    index = year * 12 + number - 1 + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_label(month: str) -> str:
    year, number = month.split("-")
    return f"{MONTH_NAMES[int(number) - 1]} {year}"


def window_months(now: datetime, first_month: str = STATS_FIRST_MONTH) -> tuple[str, ...]:
    """The current month and the five before it, oldest first, from first_month on."""
    current = month_key(now)
    months = (shift_month(current, -back) for back in range(WINDOW_MONTHS - 1, -1, -1))
    return tuple(month for month in months if month >= first_month)


def bucket_expires_at(month: str) -> int:
    """TTL for a monthly bucket: the start of the month seven months on, in epoch seconds."""
    year, number = (int(part) for part in shift_month(month, BUCKET_TTL_MONTHS).split("-"))
    return int(datetime(year, number, 1, tzinfo=UTC).timestamp())


def approver_counter_name(finding_id: str, approver: Approver) -> str:
    """Bucket counter for an accept answer's approver, e.g. "F5#by#security_team"."""
    return f"{finding_id}#by#{approver.value}"


def score_counter_name(points: int) -> str:
    """Bucket counter for a total score, e.g. "score#7"."""
    return f"score#{points}"


def bucket_counter_names(
    choices: Iterable[tuple[str, Treatment, Approver | None]], score: int
) -> list[str]:
    """Counters one attempt adds to its monthly bucket, besides the attempt count."""
    names: list[str] = []
    for finding_id, treatment, approver in choices:
        names.append(counter_name(finding_id, treatment))
        if treatment is Treatment.ACCEPT and approver is not None:
            names.append(approver_counter_name(finding_id, approver))
    names.append(score_counter_name(score))
    return names


def _percent(part: int, whole: int) -> int:
    return round(part * 100 / whole)


def _median(scores: Mapping[int, int]) -> int:
    """The lower median, so it's always a score someone got."""
    position = (sum(scores.values()) - 1) // 2
    seen = 0
    for points in sorted(scores):
        seen += scores[points]
        if seen > position:
            return points
    return 0


def _bands(scores: Mapping[int, int], attempts: int, maximum: int) -> tuple[ScoreBand, ...]:
    counts = dict.fromkeys((label for label, _ in SCORE_BANDS), 0)
    for points, count in scores.items():
        share = points * 100 // maximum
        label = next(label for label, floor in SCORE_BANDS if share >= floor)
        counts[label] += count
    return tuple(ScoreBand(label, _percent(counts[label], attempts)) for label, _ in SCORE_BANDS)


def _finding(
    scenario: Scenario,
    finding_id: str,
    title: str,
    attempts: int,
    counters: Mapping[str, int],
    min_sample: int,
) -> FindingStats:
    key = scenario.answer_key.findings[finding_id]
    counts = {t: counters.get(counter_name(finding_id, t), 0) for t in Treatment}
    other: OtherChoice | None = None
    for treatment in Treatment:
        count = counts[treatment]
        is_more = other is None or count > counts[other.treatment]
        if treatment is not key.preferred and count > 0 and is_more:
            other = OtherChoice(treatment, _percent(count, attempts))
    accept_preferred = key.preferred is Treatment.ACCEPT
    trap_percent: int | None = None
    accepted = counts[Treatment.ACCEPT]
    if accept_preferred and accepted >= max(min_sample, 1):
        traps = sum(counters.get(approver_counter_name(finding_id, a), 0) for a in TRAP_APPROVERS)
        trap_percent = _percent(traps, accepted)
    return FindingStats(
        finding_id=finding_id,
        title=title,
        preferred=key.preferred,
        preferred_percent=_percent(counts[key.preferred], attempts),
        other=other,
        accept_preferred=accept_preferred,
        trap_percent=trap_percent,
    )


def scenario_figures(
    scenario: Scenario, attempts: int, counters: Mapping[str, int], min_sample: int
) -> ScenarioFigures | None:
    """Figures for one scenario's window totals, or None below the minimum sample."""
    if attempts < max(min_sample, 1):
        return None
    maximum = PREFERRED_POINTS * len(scenario.findings)
    scores = {
        points: count
        for points in range(maximum + 1)
        if (count := counters.get(score_counter_name(points), 0)) > 0
    }
    findings = tuple(
        _finding(scenario, f.id, f.title, attempts, counters, min_sample) for f in scenario.findings
    )
    return ScenarioFigures(
        attempts=attempts,
        median=_median(scores),
        maximum=maximum,
        bands=_bands(scores, attempts, maximum),
        findings=findings,
    )


def build_stats(
    scenarios: Sequence[Scenario],
    totals: WindowTotals,
    min_sample: int,
    months: Sequence[str],
    first_month: str = STATS_FIRST_MONTH,
) -> SiteStats:
    """The whole stats page from each scenario's window totals."""
    per_scenario: list[ScenarioStats] = []
    shown: dict[Difficulty, int] = {}
    for scenario in scenarios:
        attempts, counters = totals.get(scenario.id, (0, {}))
        figures = scenario_figures(scenario, attempts, counters, min_sample)
        if figures is not None:
            shown[scenario.difficulty] = shown.get(scenario.difficulty, 0) + figures.attempts
        per_scenario.append(
            ScenarioStats(scenario.id, scenario.title, scenario.difficulty, figures)
        )
    return SiteStats(
        since=months[0] if months else first_month,
        full_window=len(months) == WINDOW_MONTHS,
        min_sample=min_sample,
        total=sum(shown.values()) if shown else None,
        by_difficulty=tuple((d, shown.get(d)) for d in Difficulty),
        scenarios=tuple(per_scenario),
    )
