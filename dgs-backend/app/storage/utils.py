from __future__ import annotations

import logging
import time
from typing import Any

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def ensure_table_exists(
    resource: Any,
    table_name: str,
    key_schema: list[dict[str, str]],
    attribute_definitions: list[dict[str, str]],
    provisioned_throughput: dict[str, int] | None = None,
    global_secondary_indexes: list[dict[str, Any]] | None = None,
) -> None:
    """Idempotently create a DynamoDB table and wait until it's active."""
    if provisioned_throughput is None:
        provisioned_throughput = {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}

    try:
        table = resource.create_table(
            TableName=table_name,
            KeySchema=key_schema,
            AttributeDefinitions=attribute_definitions,
            ProvisionedThroughput=provisioned_throughput,
            GlobalSecondaryIndexes=global_secondary_indexes or [],
        )
        logger.info(f"Creating table {table_name}...")
        table.wait_until_exists()
        logger.info(f"Table {table_name} is now ACTIVE.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            logger.info(f"Table {table_name} already exists.")
        else:
            logger.error(f"Failed to create table {table_name}: {e}")
            raise
