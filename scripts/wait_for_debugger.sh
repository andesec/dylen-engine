#!/bin/bash
set -e

echo "Waiting for debugger on port 5678..."

# Loop until netcat successfully connects to localhost port 5678
while ! nc -z localhost 5678; do
  sleep 1
done

echo "Debugger port is ready!"
