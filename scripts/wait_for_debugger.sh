#!/bin/bash
echo "Waiting for debugger on port 5678..."
while ! nc -z localhost 5678; do
  sleep 0.5
done
echo "Debugger port is ready!"
