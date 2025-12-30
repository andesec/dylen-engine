#!/bin/bash
set -e

echo "Waiting for DynamoDB Local to be ready..."
until aws dynamodb list-tables --endpoint-url http://dynamodb-local:8000 --region us-east-1 >/dev/null 2>&1; do
  echo "DynamoDB not ready yet, waiting..."
  sleep 2
done

echo "DynamoDB is ready. Checking if table exists..."

# Check if table exists
if aws dynamodb describe-table \
    --table-name dgs-lessons-local \
    --endpoint-url http://dynamodb-local:8000 \
    --region us-east-1 >/dev/null 2>&1; then
    echo "✓ Table 'dgs-lessons-local' already exists, skipping creation."
else
    echo "Creating table 'dgs-lessons-local'..."
    aws dynamodb create-table \
        --table-name dgs-lessons-local \
        --attribute-definitions \
            AttributeName=pk,AttributeType=S \
            AttributeName=sk,AttributeType=S \
            AttributeName=lesson_id,AttributeType=S \
        --key-schema \
            AttributeName=pk,KeyType=HASH \
            AttributeName=sk,KeyType=RANGE \
        --global-secondary-indexes \
            "[{\"IndexName\":\"lesson-id-index\",\"KeySchema\":[{\"AttributeName\":\"lesson_id\",\"KeyType\":\"HASH\"}],\"Projection\":{\"ProjectionType\":\"ALL\"},\"ProvisionedThroughput\":{\"ReadCapacityUnits\":5,\"WriteCapacityUnits\":5}}]" \
        --provisioned-throughput \
            ReadCapacityUnits=5,WriteCapacityUnits=5 \
        --endpoint-url http://dynamodb-local:8000 \
        --region us-east-1
    
    echo "✓ Table 'dgs-lessons-local' created successfully!"
fi

echo "DynamoDB initialization complete."
