"""DynamoDB-backed repository for background jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.client import Config

from app.jobs.guardrails import (
    enforce_item_size_guardrails,
    maybe_truncate_result_json,
    sanitize_logs,
)
from app.jobs.models import JobRecord, JobStatus
from app.storage.jobs_repo import JobsRepository
from app.storage.utils import ensure_table_exists


@dataclass(frozen=True)
class DynamoJobKeys:
    """Key structure for a job item."""

    pk: str
    sk: str


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _serialize_for_dynamodb(obj: Any) -> Any:
    """Recursively convert float types to Decimal for DynamoDB storage."""
    if isinstance(obj, float):
        # Convert float to Decimal via string to preserve precision
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {key: _serialize_for_dynamodb(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_dynamodb(item) for item in obj]
    return obj


class DynamoJobsRepository(JobsRepository):
    """Persist jobs to DynamoDB."""

    def __init__(
        self,
        *,
        table_name: str,
        region: str,
        endpoint_url: str | None,
        all_jobs_index: str | None,
        idempotency_index: str | None,
        timeout_seconds: int = 10,
    ) -> None:
        aws_kwargs: dict[str, Any] = {}
        if endpoint_url and ("localhost" in endpoint_url or "127.0.0.1" in endpoint_url):
            import os

            if not os.getenv("AWS_ACCESS_KEY_ID"):
                aws_kwargs["aws_access_key_id"] = "test"
                aws_kwargs["aws_secret_access_key"] = "test"

        session = boto3.session.Session()
        resource = session.resource(
            "dynamodb",
            region_name=region,
            endpoint_url=endpoint_url,
            config=Config(connect_timeout=timeout_seconds, read_timeout=timeout_seconds),
            **aws_kwargs,
        )

        # Build attribute definitions and indexes
        attr_defs = [
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ]
        gsis = []
        if all_jobs_index:
            attr_defs.append({"AttributeName": "gsi1_pk", "AttributeType": "S"})
            attr_defs.append({"AttributeName": "gsi1_sk", "AttributeType": "S"})
            gsis.append({
                "IndexName": all_jobs_index,
                "KeySchema": [
                    {"AttributeName": "gsi1_pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi1_sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
            })
        if idempotency_index:
            attr_defs.append({"AttributeName": "gsi2_pk", "AttributeType": "S"})
            attr_defs.append({"AttributeName": "gsi2_sk", "AttributeType": "S"})
            gsis.append({
                "IndexName": idempotency_index,
                "KeySchema": [
                    {"AttributeName": "gsi2_pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi2_sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
            })

        ensure_table_exists(
            resource=resource,
            table_name=table_name,
            key_schema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            attribute_definitions=attr_defs,
            global_secondary_indexes=gsis if gsis else None,
        )

        self._table = resource.Table(table_name)
        self._all_jobs_index = all_jobs_index
        self._idempotency_index = idempotency_index

    def create_job(self, record: JobRecord) -> None:
        item = self._record_to_item(record)
        safe_item = enforce_item_size_guardrails(item)
        self._table.put_item(Item=safe_item)

    def get_job(self, job_id: str) -> JobRecord | None:
        keys = self._job_keys(job_id)
        response = self._table.get_item(Key={"pk": keys.pk, "sk": keys.sk})
        item = response.get("Item")
        if not item:
            return None
        return self._item_to_record(item)

    def update_job(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        phase: str | None = None,
        subphase: str | None = None,
        total_steps: int | None = None,
        completed_steps: int | None = None,
        progress: float | None = None,
        logs: list[str] | None = None,
        result_json: dict | None = None,
        validation: dict | None = None,
        cost: dict | None = None,
        completed_at: str | None = None,
        updated_at: str | None = None,
    ) -> JobRecord | None:
        current = self.get_job(job_id)
        if current is None:
            return None

        # Prevent overwriting a canceled status with anything other than canceled
        if current.status == "canceled" and status is not None and status != "canceled":
            return current

        updated_record = JobRecord(
            job_id=current.job_id,
            request=current.request,
            status=status or current.status,
            phase=phase if phase is not None else current.phase,
            subphase=subphase if subphase is not None else current.subphase,
            total_steps=total_steps if total_steps is not None else current.total_steps,
            completed_steps=(
                completed_steps if completed_steps is not None else current.completed_steps
            ),
            progress=progress if progress is not None else current.progress,
            logs=logs if logs is not None else current.logs,
            result_json=result_json if result_json is not None else current.result_json,
            validation=validation if validation is not None else current.validation,
            cost=cost if cost is not None else current.cost,
            created_at=current.created_at,
            updated_at=updated_at or _now_iso(),
            completed_at=completed_at if completed_at is not None else current.completed_at,
            ttl=current.ttl,
            idempotency_key=current.idempotency_key,
        )

        safe_item = enforce_item_size_guardrails(self._record_to_item(updated_record))
        self._table.put_item(Item=safe_item)
        return updated_record

    def find_queued(self, limit: int = 5) -> list[JobRecord]:
        if not self._all_jobs_index:
            return []
        response = self._table.query(
            IndexName=self._all_jobs_index,
            KeyConditionExpression=Key("gsi1_pk").eq("JOB"),
            FilterExpression=Attr("status").eq("queued"),
            Limit=limit,
            ScanIndexForward=True,
        )
        items = response.get("Items", [])
        return [self._item_to_record(item) for item in items]

    def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        if not self._idempotency_index:
            return None
        response = self._table.query(
            IndexName=self._idempotency_index,
            KeyConditionExpression=Key("gsi2_pk").eq(idempotency_key),
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            return None
        return self._item_to_record(items[0])

    def _job_keys(self, job_id: str) -> DynamoJobKeys:
        pk = f"JOB#{job_id}"
        return DynamoJobKeys(pk=pk, sk=pk)

    def _record_to_item(self, record: JobRecord) -> dict[str, Any]:
        keys = self._job_keys(record.job_id)
        item: dict[str, Any] = {
            "pk": keys.pk,
            "sk": keys.sk,
            "job_id": record.job_id,
            "request": _serialize_for_dynamodb(record.request),
            "status": record.status,
            "phase": record.phase,
            "subphase": record.subphase,
            "total_steps": record.total_steps,
            "completed_steps": record.completed_steps,
            "progress": Decimal(str(record.progress)) if record.progress is not None else None,
            "logs": sanitize_logs(record.logs),
            "result_json": maybe_truncate_result_json(record.result_json),
            "validation": record.validation,
            "cost": record.cost,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "completed_at": record.completed_at,
            "ttl": record.ttl,
            "idempotency_key": record.idempotency_key,
            "gsi1_pk": "JOB",
            "gsi1_sk": f"{record.created_at}#{record.job_id}",
        }
        if record.idempotency_key and self._idempotency_index:
            item["gsi2_pk"] = record.idempotency_key
            item["gsi2_sk"] = record.created_at
        return {key: value for key, value in item.items() if value is not None}

    def _item_to_record(self, item: dict[str, Any]) -> JobRecord:
        return JobRecord(
            job_id=item["job_id"],
            request=item["request"],
            status=item["status"],
            phase=item.get("phase"),
            subphase=item.get("subphase"),
            total_steps=item.get("total_steps"),
            completed_steps=item.get("completed_steps"),
            progress=(
                float(item["progress"])
                if "progress" in item and item["progress"] is not None
                else None
            ),
            logs=item.get("logs") or [],
            result_json=item.get("result_json"),
            validation=item.get("validation"),
            cost=item.get("cost"),
            created_at=item["created_at"],
            updated_at=item["updated_at"],
            completed_at=item.get("completed_at"),
            ttl=item.get("ttl"),
            idempotency_key=item.get("idempotency_key"),
        )
