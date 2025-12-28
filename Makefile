PYTHON ?= python3
APP_DIR := dgs-backend
PORT ?= 8000

.PHONY: install dev lint format typecheck test sam-local

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e .[dev]

dev:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	PORT=$${PORT:-$(PORT)}; \
	cd $(APP_DIR) && $(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port $$PORT

format:
	$(PYTHON) -m black $(APP_DIR)

lint:
	$(PYTHON) -m ruff check $(APP_DIR)

typecheck:
	$(PYTHON) -m mypy $(APP_DIR)

test:
	$(PYTHON) -m pytest

sam-local:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	STAGE=$${STAGE:-local}; \
	LOG_LEVEL=$${LOG_LEVEL:-info}; \
	PORT=$${PORT:-$(PORT)}; \
	sam local start-api --template infra/template.yaml --parameter-overrides Stage=$$STAGE LogLevel=$$LOG_LEVEL --port $$PORT
