#!/bin/bash
# BFG2 E2E Test Runner
# Run all end-to-end tests

cd "$(dirname "$0")"

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Error: Virtual environment not found. Please create it first:"
    echo "  python -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Run E2E tests
python -m pytest tests/e2e/ -v --tb=short -m e2e

