"""In-memory attempt store for `rt preview` and end-to-end tests. Never used in Lambda."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from threading import Lock

from risk_trainer.domain.peers import counter_name
from risk_trainer.domain.stats import month_key
from risk_trainer.storage.attempts import AttemptRecord, PeerCounts, month_counters


class MemoryAttemptStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._submit_ids: set[str] = set()
        self._attempts: Counter[tuple[str, int]] = Counter()
        self._counters: defaultdict[tuple[str, int], Counter[str]] = defaultdict(Counter)
        self._month_attempts: Counter[tuple[str, int, str]] = Counter()
        self._months: defaultdict[tuple[str, int, str], Counter[str]] = defaultdict(Counter)

    def record(self, attempt: AttemptRecord) -> bool:
        key = (attempt.scenario_id, attempt.scenario_version)
        with self._lock:
            if attempt.submit_id in self._submit_ids:
                return False
            self._submit_ids.add(attempt.submit_id)
            self._attempts[key] += 1
            for choice in attempt.choices:
                self._counters[key][counter_name(choice.finding_id, choice.treatment)] += 1
        return True

    def peer_counts(self, scenario_id: str, version: int) -> PeerCounts:
        key = (scenario_id, version)
        with self._lock:
            return PeerCounts(self._attempts[key], dict(self._counters[key]))

    def add_to_month(self, attempt: AttemptRecord) -> None:
        key = (attempt.scenario_id, attempt.scenario_version, month_key(attempt.submitted_at))
        with self._lock:
            self._month_attempts[key] += 1
            self._months[key].update(month_counters(attempt))

    def window_counts(self, scenario_id: str, version: int, months: Sequence[str]) -> PeerCounts:
        attempts = 0
        counters: Counter[str] = Counter()
        with self._lock:
            for month in months:
                key = (scenario_id, version, month)
                attempts += self._month_attempts.get(key, 0)
                counters.update(self._months.get(key, Counter()))
        return PeerCounts(attempts, dict(counters))
