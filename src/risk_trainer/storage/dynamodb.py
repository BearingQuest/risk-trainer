"""DynamoDB attempt store (PRD R9, R22). One table keyed by pk/sk.

- Attempt: pk=ATTEMPT#<submit_id>, sk=ATTEMPT, with expires_at (TTL, epoch seconds).
- Aggregate: pk=AGG#<scenario_id>#v<version>, sk=AGG, with counters n and F1#avoid etc.
- Monthly stats bucket: the aggregate's pk, sk=MONTH#<YYYY-MM>, with counters n, F1#avoid,
  F5#by#security_team and score#7, and expires_at about seven months on.

Each submission is one transaction: a conditional Put of the attempt (so a resubmitted form
isn't counted twice) and an ADD to the aggregate counters. The monthly bucket is a separate
UpdateItem, made only after the transaction records a new attempt.
"""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from risk_trainer.domain.peers import counter_name
from risk_trainer.domain.stats import bucket_expires_at, month_key
from risk_trainer.storage.attempts import (
    AttemptRecord,
    PeerCounts,
    StorageError,
    expires_at,
    month_counters,
)

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient

ATTEMPTS_COUNTER = "n"
CLIENT_CONFIG = Config(
    connect_timeout=2,
    read_timeout=3,
    retries={"total_max_attempts": 3, "mode": "standard"},
)


def make_client(region: str | None) -> DynamoDBClient:
    return boto3.client("dynamodb", region_name=region, config=CLIENT_CONFIG)


def aggregate_pk(scenario_id: str, version: int) -> str:
    return f"AGG#{scenario_id}#v{version}"


def month_sk(month: str) -> str:
    return f"MONTH#{month}"


class DynamoAttemptStore:
    def __init__(self, client: DynamoDBClient, table: str) -> None:
        self._client = client
        self._table = table

    def record(self, attempt: AttemptRecord) -> bool:
        choices: dict[str, Any] = {}
        for choice in attempt.choices:
            entry: dict[str, Any] = {"treatment": {"S": choice.treatment.value}}
            if choice.approver is not None:
                entry["approver"] = {"S": choice.approver.value}
            choices[choice.finding_id] = {"M": entry}

        counters = [ATTEMPTS_COUNTER] + [
            counter_name(c.finding_id, c.treatment) for c in attempt.choices
        ]
        names = {f"#c{i}": name for i, name in enumerate(counters)}
        update = "ADD " + ", ".join(f"{placeholder} :one" for placeholder in names)
        try:
            self._client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self._table,
                            "Item": {
                                "pk": {"S": f"ATTEMPT#{attempt.submit_id}"},
                                "sk": {"S": "ATTEMPT"},
                                "scenario_id": {"S": attempt.scenario_id},
                                "scenario_version": {"N": str(attempt.scenario_version)},
                                "choices": {"M": choices},
                                "score": {"N": str(attempt.score)},
                                "max_score": {"N": str(attempt.max_score)},
                                "submitted_at": {"S": attempt.submitted_at.isoformat()},
                                "expires_at": {"N": str(expires_at(attempt.submitted_at))},
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Update": {
                            "TableName": self._table,
                            "Key": {
                                "pk": {
                                    "S": aggregate_pk(attempt.scenario_id, attempt.scenario_version)
                                },
                                "sk": {"S": "AGG"},
                            },
                            "UpdateExpression": update,
                            "ExpressionAttributeNames": names,
                            "ExpressionAttributeValues": {":one": {"N": "1"}},
                        }
                    },
                ]
            )
        except ClientError as exc:
            if _is_duplicate(exc):
                return False
            raise StorageError("could not record the attempt") from exc
        except BotoCoreError as exc:
            raise StorageError("could not record the attempt") from exc
        return True

    def peer_counts(self, scenario_id: str, version: int) -> PeerCounts:
        try:
            response = self._client.get_item(
                TableName=self._table,
                Key={"pk": {"S": aggregate_pk(scenario_id, version)}, "sk": {"S": "AGG"}},
                ConsistentRead=False,
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError("could not read peer counts") from exc
        return _counts(response.get("Item", {}))

    def add_to_month(self, attempt: AttemptRecord) -> None:
        month = month_key(attempt.submitted_at)
        counters = [ATTEMPTS_COUNTER, *month_counters(attempt)]
        names = {f"#c{i}": name for i, name in enumerate(counters)}
        update = "SET #exp = if_not_exists(#exp, :exp) ADD " + ", ".join(
            f"{placeholder} :one" for placeholder in names
        )
        try:
            self._client.update_item(
                TableName=self._table,
                Key={
                    "pk": {"S": aggregate_pk(attempt.scenario_id, attempt.scenario_version)},
                    "sk": {"S": month_sk(month)},
                },
                UpdateExpression=update,
                ExpressionAttributeNames={**names, "#exp": "expires_at"},
                ExpressionAttributeValues={
                    ":one": {"N": "1"},
                    ":exp": {"N": str(bucket_expires_at(month))},
                },
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError("could not update the monthly totals") from exc

    def window_counts(self, scenario_id: str, version: int, months: Sequence[str]) -> PeerCounts:
        attempts = 0
        counters: dict[str, int] = {}
        for month in months:
            try:
                response = self._client.get_item(
                    TableName=self._table,
                    Key={
                        "pk": {"S": aggregate_pk(scenario_id, version)},
                        "sk": {"S": month_sk(month)},
                    },
                    ConsistentRead=False,
                )
            except (ClientError, BotoCoreError) as exc:
                raise StorageError("could not read the monthly totals") from exc
            bucket = _counts(response.get("Item", {}))
            attempts += bucket.attempts
            for name, count in bucket.counters.items():
                counters[name] = counters.get(name, 0) + count
        return PeerCounts(attempts, counters)


def _counts(item: Mapping[str, Any]) -> PeerCounts:
    counters = {
        name: int(value["N"])
        for name, value in item.items()
        if name not in ("pk", "sk", "expires_at") and "N" in value
    }
    attempts = counters.pop(ATTEMPTS_COUNTER, 0)
    return PeerCounts(attempts, counters)


def _is_duplicate(exc: ClientError) -> bool:
    if exc.response.get("Error", {}).get("Code") != "TransactionCanceledException":
        return False
    reasons: list[dict[str, Any]] = exc.response.get("CancellationReasons", [])  # type: ignore[assignment]
    return bool(reasons) and reasons[0].get("Code") == "ConditionalCheckFailed"
