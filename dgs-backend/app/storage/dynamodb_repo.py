"""DynamoDB-backed lesson repository implementation."""

from __future__ import annotations

from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from app.storage.lessons_repo import LessonRecord, LessonsRepository
from app.storage.utils import ensure_table_exists


class DynamoLessonsRepository(LessonsRepository):
    """Store and retrieve lesson records in DynamoDB."""

    def __init__(
        self,
        *,
        table_name: str,
        region: str,
        endpoint_url: str | None = None,
        tenant_key: str,
        lesson_id_index: str,
    ) -> None:
        self._table_name = table_name
        self._tenant_key = tenant_key
        self._lesson_id_index = lesson_id_index
        # Handle local DynamoDB credentials
        aws_kw = {}
        if endpoint_url and ("localhost" in endpoint_url or "127.0.0.1" in endpoint_url):
            import os

            # If running locally and no credentials exist, provide dummies to satisfy Boto3
            if not os.getenv("AWS_ACCESS_KEY_ID"):
                aws_kw["aws_access_key_id"] = "test"
                aws_kw["aws_secret_access_key"] = "test"

        resource = boto3.resource(
            "dynamodb", region_name=region, endpoint_url=endpoint_url, **aws_kw
        )

        # Ensure table exists
        ensure_table_exists(
            resource=resource,
            table_name=table_name,
            key_schema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            attribute_definitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "lesson_id", "AttributeType": "S"},
            ],
            global_secondary_indexes=[
                {
                    "IndexName": lesson_id_index,
                    "KeySchema": [{"AttributeName": "lesson_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
                }
            ],
        )

        self._table = resource.Table(table_name)

    def create_lesson(self, record: LessonRecord) -> None:
        """Persist a lesson record."""
        item: dict[str, Any] = {
            "pk": self._tenant_key,
            "sk": f"LESSON#{record.created_at}#{record.lesson_id}",
            "lesson_id": record.lesson_id,
            "topic": record.topic,
            "title": record.title,
            "created_at": record.created_at,
            "schema_version": record.schema_version,
            "prompt_version": record.prompt_version,
            "provider_a": record.provider_a,
            "model_a": record.model_a,
            "provider_b": record.provider_b,
            "model_b": record.model_b,
            "lesson_json": record.lesson_json,
            "status": record.status,
            "latency_ms": record.latency_ms,
        }
        if record.idempotency_key:
            item["idempotency_key"] = record.idempotency_key
        if record.tags:
            item["tags"] = record.tags
        self._table.put_item(Item=item)

    def get_lesson(self, lesson_id: str) -> LessonRecord | None:
        """Fetch a lesson record by lesson identifier."""
        response = self._table.query(
            IndexName=self._lesson_id_index,
            KeyConditionExpression=Key("lesson_id").eq(lesson_id),
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            return None
        item = items[0]
        return LessonRecord(
            lesson_id=item["lesson_id"],
            topic=item["topic"],
            title=item["title"],
            created_at=item["created_at"],
            schema_version=item["schema_version"],
            prompt_version=item["prompt_version"],
            provider_a=item["provider_a"],
            model_a=item["model_a"],
            provider_b=item["provider_b"],
            model_b=item["model_b"],
            lesson_json=item["lesson_json"],
            status=item["status"],
            latency_ms=int(item.get("latency_ms", 0)),
            idempotency_key=item.get("idempotency_key"),
            tags=set(item["tags"]) if "tags" in item else None,
        )
