"""R22 — monthly stats buckets against DynamoDB (moto), plus the same contract for memory."""

from datetime import UTC, datetime
from typing import Any

import pytest

from risk_trainer.domain.treatments import Approver, Treatment
from risk_trainer.storage.attempts import AttemptRecord, AttemptStore, Choice, StorageError
from risk_trainer.storage.dynamodb import DynamoAttemptStore, make_client
from risk_trainer.storage.memory import MemoryAttemptStore
from tests.integration.conftest import REGION, TABLE

NOVEMBER = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
DECEMBER = datetime(2026, 12, 2, 9, 0, tzinfo=UTC)
BUCKET_KEY = {"pk": {"S": "AGG#rt-001-five-findings#v1"}, "sk": {"S": "MONTH#2026-11"}}


@pytest.fixture(params=["memory", "dynamodb"])
def store(request: pytest.FixtureRequest) -> AttemptStore:
    if request.param == "memory":
        return MemoryAttemptStore()
    request.getfixturevalue("dynamo")
    return DynamoAttemptStore(make_client(REGION), TABLE)


def attempt(
    submit_id: str = "s" * 22,
    when: datetime = NOVEMBER,
    approver: Approver = Approver.SECURITY_TEAM,
    score: int = 7,
) -> AttemptRecord:
    choices = [Choice(f"F{i}", Treatment.MITIGATE_REMEDIATE, None) for i in (1, 2, 3, 4)]
    choices.append(Choice("F5", Treatment.ACCEPT, approver))
    return AttemptRecord(submit_id, "rt-001-five-findings", 1, tuple(choices), score, 10, when)


def test_r22_contract_window_counts_sum_months(store: AttemptStore) -> None:
    store.add_to_month(attempt("a" * 22))
    store.add_to_month(attempt("b" * 22, approver=Approver.BUSINESS_RISK_OWNER, score=10))
    store.add_to_month(attempt("c" * 22, when=DECEMBER))
    counts = store.window_counts("rt-001-five-findings", 1, ["2026-11", "2026-12"])
    assert counts.attempts == 3
    assert counts.counters == {
        "F1#mitigate_remediate": 3,
        "F2#mitigate_remediate": 3,
        "F3#mitigate_remediate": 3,
        "F4#mitigate_remediate": 3,
        "F5#accept": 3,
        "F5#by#security_team": 2,
        "F5#by#business_risk_owner": 1,
        "score#7": 2,
        "score#10": 1,
    }
    assert store.window_counts("rt-001-five-findings", 1, ["2026-12"]).attempts == 1


def test_r22_contract_unread_months_and_versions_are_empty(store: AttemptStore) -> None:
    store.add_to_month(attempt())
    assert store.window_counts("rt-001-five-findings", 1, ["2026-10"]).attempts == 0
    assert store.window_counts("rt-001-five-findings", 2, ["2026-11"]).attempts == 0
    assert store.window_counts("rt-001-five-findings", 1, []).attempts == 0


def test_r22_contract_buckets_leave_peer_aggregates_alone(store: AttemptStore) -> None:
    store.add_to_month(attempt())
    assert store.peer_counts("rt-001-five-findings", 1).attempts == 0
    assert store.record(attempt())
    assert store.peer_counts("rt-001-five-findings", 1).attempts == 1
    assert store.window_counts("rt-001-five-findings", 1, ["2026-11"]).attempts == 1


def test_r22_bucket_item_has_counters_and_ttl(dynamo: Any) -> None:
    store = DynamoAttemptStore(make_client(REGION), TABLE)
    store.add_to_month(attempt("a" * 22))
    store.add_to_month(attempt("b" * 22))
    item = dynamo.get_item(TableName=TABLE, Key=BUCKET_KEY)["Item"]
    assert item["n"] == {"N": "2"}
    assert item["F5#by#security_team"] == {"N": "2"}
    assert item["score#7"] == {"N": "2"}
    assert item["expires_at"] == {"N": str(int(datetime(2027, 6, 1, tzinfo=UTC).timestamp()))}
    assert not any(name.startswith(("submit", "ATTEMPT")) for name in item)


def test_r22_one_update_item_per_bucket_write(dynamo: Any) -> None:
    client = make_client(REGION)
    calls: list[str] = []
    client.meta.events.register(
        "before-call.dynamodb.*", lambda model, **_: calls.append(model.name)
    )
    DynamoAttemptStore(client, TABLE).add_to_month(attempt())
    assert calls == ["UpdateItem"]


def test_r22_bucket_ttl_is_not_counted(dynamo: Any) -> None:
    store = DynamoAttemptStore(make_client(REGION), TABLE)
    store.add_to_month(attempt())
    counts = store.window_counts("rt-001-five-findings", 1, ["2026-11"])
    assert "expires_at" not in counts.counters


def test_r22_missing_table_raises_storage_error(dynamo: Any) -> None:
    broken = DynamoAttemptStore(make_client(REGION), "no-such-table")
    with pytest.raises(StorageError):
        broken.add_to_month(attempt())
    with pytest.raises(StorageError):
        broken.window_counts("rt-001-five-findings", 1, ["2026-11"])
