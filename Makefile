PYTHON ?= python3
VENV_DIR := .venv
VENV_PYTHON := $(VENV_DIR)/bin/python
VENV_MARKER := $(VENV_DIR)/.deps_installed
APP_DIR := dgs-backend
PORT ?= 8080

.PHONY: install dev lint format typecheck test sam-local openapi run

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e .[dev]

dev: openapi
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
	PORT=$${PORT:-$(PORT)}; \/mo
	sam local start-api --template infra/template.yaml --parameter-overrides Stage=$$STAGE LogLevel=$$LOG_LEVEL --port $$PORT

openapi:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	$(PYTHON) -c "import json, os, sys; repo_root=os.path.abspath(os.getcwd()); app_dir=os.path.join(repo_root, 'dgs-backend'); sys.path.insert(0, app_dir); from app.main import app; openapi=app.openapi(); f=open(os.path.join(repo_root, 'openapi.json'), 'w', encoding='utf-8'); json.dump(openapi, f, indent=2, sort_keys=True); f.write('\\n'); f.close()"

run:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		$(PYTHON) -m venv $(VENV_DIR); \
	fi
	@if [ ! -f "$(VENV_MARKER)" ]; then \
		$(VENV_PYTHON) -m pip install --upgrade pip; \
		$(VENV_PYTHON) -m pip install -e .[dev]; \
		touch $(VENV_MARKER); \
	fi
	@$(MAKE) dev PYTHON=$(VENV_PYTHON)
