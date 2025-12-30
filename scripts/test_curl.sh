#!/bin/bash
# Source the .env file
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

if [ -z "$GEMINI_API_KEY" ]; then
  echo "GEMINI_API_KEY is not set"
  exit 1
fi

echo "Testing with key: ${GEMINI_API_KEY:0:5}..."

curl "https://generativelanguage.googleapis.com/v1beta/models?key=$GEMINI_API_KEY"
