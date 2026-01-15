PYTHON ?= python3
VENV_DIR := .venv
APP_DIR := dgs-backend
PORT ?= 8080

.PHONY: install dev dev-stop lint format typecheck test openapi run

install:
	uv sync

dev: openapi
	@echo "Starting Postgres..."
	@docker-compose up -d postgres postgres-init
	@echo "Waiting for Postgres to be ready..."
	@sleep 5
	@set -a; [ -f .env ] && . ./.env; set +a; \
	PORT=$${PORT:-$(PORT)}; \
	echo "Starting FastAPI app on port $$PORT..."; \
	cd $(APP_DIR) && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port $$PORT

dev-stop:
	@echo "Stopping Docker services..."
	@docker-compose down

format:
	uv run ruff format $(APP_DIR)

lint:
	uv run ruff check $(APP_DIR)

typecheck:
	uv run mypy $(APP_DIR)

test:
	uv run pytest

openapi:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	cd $(APP_DIR) && uv run python -c "import json, os, sys; repo_root=os.path.abspath(os.path.join(os.getcwd(), '..')); sys.path.insert(0, os.getcwd()); from app.main import app; openapi=app.openapi(); f=open(os.path.join(repo_root, 'openapi.json'), 'w', encoding='utf-8'); json.dump(openapi, f, indent=2, sort_keys=True); f.write('\n'); f.close()"

run: install
	@$(MAKE) dev

snyk-test: install
	uv export --format requirements-txt --output-file requirements.txt
	@echo "Running Snyk test..."
	. $(VENV_DIR)/bin/activate && snyk test --file=requirements.txt --package-manager=pip
	@rm requirements.txt
