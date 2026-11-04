"""R9 — peer distribution, attempt records, storage settings and no free text in logs."""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from risk_trainer.config import ConfigError, Settings
from risk_trainer.domain.peers import counter_name, distribution
from risk_trainer.domain.treatments import Treatment
from risk_trainer.storage.attempts import (
    AttemptRecord,
    AttemptStore,
    PeerCounts,
    StorageError,
    expires_at,
    not_expired,
)
from risk_trainer.storage.memory import MemoryAttemptStore
from risk_trainer.web.app import create_app
from tests.web_helpers import EXPERT_ANSWERS, SECRET, client, rt001, settings, submit

FINDINGS = ["F1", "F2", "F3", "F4", "F5"]


def test_r9_peers_hidden_below_min_sample() -> None:
    assert distribution(9, {}, FINDINGS, min_sample=10) is None


def test_r9_peers_shown_at_min_sample_with_percentages() -> None:
    counters = {counter_name("F1", Treatment.AVOID): 3, counter_name("F1", Treatment.ACCEPT): 7}
    result = distribution(10, counters, FINDINGS, min_sample=10)
    assert result is not None
    assert result.percents["F1"][Treatment.AVOID] == 30
    assert result.percents["F1"][Treatment.ACCEPT] == 70
    assert result.percents["F2"][Treatment.AVOID] == 0


def test_r9_result_page_shows_peers_once_sample_reached() -> None:
    test_client = client(peer_min_sample=2)
    first = submit(test_client).text
    assert "Peer results appear once enough people" in first
    second = submit(test_client).text
    assert "Based on 2 attempts" in second
    assert "100%" in second


def test_r9_duplicate_submit_id_not_counted_twice() -> None:
    store = MemoryAttemptStore()
    test_client = client(store=store)
    page = test_client.get("/s/rt-001-five-findings").text
    from tests.web_helpers import form_fields

    data = {**form_fields(page), **EXPERT_ANSWERS}
    assert test_client.post("/s/rt-001-five-findings", data=data).status_code == 200
    assert test_client.post("/s/rt-001-five-findings", data=data).status_code == 200
    assert store.peer_counts("rt-001-five-findings", 1).attempts == 1


def test_r9_ttl_is_submission_plus_180_days() -> None:
    submitted = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    assert expires_at(submitted) == int(datetime(2027, 4, 4, 12, 0, tzinfo=UTC).timestamp())


def test_r9_not_expired_filter() -> None:
    now = datetime(2026, 10, 6, tzinfo=UTC)
    assert not_expired(int(now.timestamp()) + 1, now)
    assert not not_expired(int(now.timestamp()), now)


def test_r9_store_exposes_no_raw_attempt_read() -> None:
    # Any new read of raw attempts must filter with not_expired; adding one fails this test
    # on purpose so the reviewer checks it.
    # The R22 monthly buckets are counters read by key, not raw attempts.
    methods = {name for name in vars(AttemptStore) if not name.startswith("_")}
    assert methods == {"record", "peer_counts", "add_to_month", "window_counts"}


def test_r9_attempt_record_has_only_structured_fields() -> None:
    assert set(AttemptRecord.__dataclass_fields__) == {
        "submit_id",
        "scenario_id",
        "scenario_version",
        "choices",
        "score",
        "max_score",
        "submitted_at",
    }


class _FailingStore:
    def record(self, attempt: AttemptRecord) -> bool:
        raise StorageError("down")

    def peer_counts(self, scenario_id: str, version: int) -> PeerCounts:
        raise StorageError("down")

    def add_to_month(self, attempt: AttemptRecord) -> None:
        raise StorageError("down")

    def window_counts(self, scenario_id: str, version: int, months: Sequence[str]) -> PeerCounts:
        raise StorageError("down")


def test_r9_storage_failure_still_shows_debrief() -> None:
    response = submit(client(store=_FailingStore()))
    assert response.status_code == 200
    assert "10 of 10 points" in response.text


def test_r9_rationale_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    rationale_marker = "RATIONALE-MARKER-123"
    note = "NOTE-MARKER-456"
    failing, working = client(store=_FailingStore()), client()
    logger = logging.getLogger("risk_trainer")  # create_app replaced its handlers
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.DEBUG, logger="risk_trainer"):
            submit(failing, {**EXPERT_ANSWERS, "F5.rationale": rationale_marker}, note=note)
            submit(working, {**EXPERT_ANSWERS, "F5.rationale": rationale_marker}, note=note)
            submit(
                working, {**EXPERT_ANSWERS, "F5.rationale": rationale_marker, "F2.treatment": "x"}
            )
    finally:
        logger.removeHandler(caplog.handler)
    assert any(getattr(r, "event", None) == "storage_error" for r in caplog.records)
    logged = caplog.text + " ".join(str(r.__dict__) for r in caplog.records)
    assert rationale_marker not in logged
    assert note not in logged


def test_r9_storage_backend_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("SESSION_SECRET", SECRET)
    with pytest.raises(ValidationError, match="storage_backend"):
        Settings()


def test_r9_memory_backend_refused_in_lambda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "risk-trainer-prod")
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    monkeypatch.setenv("SESSION_SECRET", SECRET)
    with pytest.raises(ConfigError, match="not allowed in Lambda"):
        Settings()


def test_r9_create_app_refuses_memory_in_lambda() -> None:
    unsafe = Settings.model_construct(
        **{**settings().model_dump(), "aws_lambda_function_name": "risk-trainer-prod"}
    )
    with pytest.raises(ConfigError):
        create_app(unsafe, MemoryAttemptStore(), [rt001()])


def test_r9_dynamodb_backend_needs_table(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="DYNAMODB_TABLE"):
        settings(storage_backend="dynamodb")


def test_r9_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    env: dict[str, Any] = {
        "STORAGE_BACKEND": "dynamodb",
        "DYNAMODB_TABLE": "risk-trainer-dev",
        "SESSION_SECRET": SECRET,
        "PEER_MIN_SAMPLE": "3",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    loaded = Settings()
    assert (loaded.dynamodb_table, loaded.peer_min_sample) == ("risk-trainer-dev", 3)
