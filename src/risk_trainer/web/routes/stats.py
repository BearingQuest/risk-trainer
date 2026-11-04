"""Public learner stats page (PRD R22): totals only, GET only, cached in-process.

Each Lambda instance refreshes the totals at most once every five minutes, and after a storage
failure waits 30 seconds before trying again, so a throttled table isn't read on every GET.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Lock

from fastapi import APIRouter, Request
from fastapi.responses import Response

from risk_trainer.domain.models import Scenario, Status
from risk_trainer.domain.stats import SiteStats, build_stats, window_months
from risk_trainer.storage.attempts import AttemptStore, StorageError

logger = logging.getLogger("risk_trainer.web.stats")
router = APIRouter()

STATS_CACHE_TTL = timedelta(minutes=5)
STATS_FAILURE_TTL = timedelta(seconds=30)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class StatsUnavailable(Exception):
    """The totals couldn't be read; the page says so."""


class StatsCache:
    """One cached result: the stats for 5 minutes, or a storage failure for 30 seconds."""

    def __init__(self, clock: Clock = utc_now) -> None:
        self._clock = clock
        self._lock = Lock()
        self._value: SiteStats | None = None
        self._expires: datetime | None = None

    def get(self, compute: Callable[[datetime], SiteStats]) -> SiteStats:
        now = self._clock()
        with self._lock:
            if self._expires is None or now >= self._expires:
                try:
                    self._value = compute(now)
                    self._expires = now + STATS_CACHE_TTL
                except StorageError:
                    logger.exception("stats unavailable", extra={"event": "stats_storage_error"})
                    self._value = None
                    self._expires = now + STATS_FAILURE_TTL
            if self._value is None:
                raise StatsUnavailable
            return self._value


def compute_stats(
    store: AttemptStore, scenarios: list[Scenario], min_sample: int, now: datetime
) -> SiteStats:
    """Read each approved scenario's window totals and build the page."""
    months = window_months(now)
    approved = sorted((s for s in scenarios if s.status is Status.APPROVED), key=lambda s: s.id)
    totals: dict[str, tuple[int, dict[str, int]]] = {}
    if months:  # empty only before STATS_FIRST_MONTH
        for scenario in approved:
            counts = store.window_counts(scenario.id, scenario.version, months)
            totals[scenario.id] = (counts.attempts, counts.counters)
    return build_stats(approved, totals, min_sample, months)


@router.get("/stats")
async def stats(request: Request) -> Response:
    state = request.app.state
    cache: StatsCache = state.stats_cache
    scenarios: list[Scenario] = list(state.scenarios.values())
    min_sample: int = state.settings.peer_min_sample
    site: SiteStats | None
    try:
        site = cache.get(lambda now: compute_stats(state.store, scenarios, min_sample, now))
        status_code = 200
    except StatsUnavailable:
        site, status_code = None, 503
    response: Response = state.templates.TemplateResponse(
        request,
        "stats.html",
        {"preview": state.preview, "site": site, "min_sample": min_sample},
        status_code=status_code,
    )
    return response
