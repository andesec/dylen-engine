PYTHON ?= python3
VENV_DIR := .venv
APP_DIR := dgs-backend
PORT ?= 8080
MIGRATION_BASE_REF ?= main

.PHONY: install dev dev-stop lint format format-check typecheck test openapi run \
	    security-sca security-sast-bandit security-sast-semgrep security-sast \
	    security-container security-dast security-all
.PHONY: hooks-install

install:
	uv sync --all-extras
	@# Remove conflicting 'app' package from myapplication to prevent import conflicts
	@rm -rf .venv/lib/python*/site-packages/app 2>/dev/null || true

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
	uv run ruff format .

format-check:
	uv run ruff format --check .

fix:
	uv run ruff check --fix .
	uv run ruff format .
	@$(MAKE) lint

lint:
	uv run ruff check .

typecheck:
	uv run mypy .

test:
	uv run pytest

openapi:
	@set -a; [ -f .env ] && . ./.env; set +a; \
	cd $(APP_DIR) && uv run python -c "import json, os, sys; repo_root=os.path.abspath(os.path.join(os.getcwd(), '..')); sys.path.insert(0, os.getcwd()); from app.main import app; openapi=app.openapi(); f=open(os.path.join(repo_root, 'openapi.json'), 'w', encoding='utf-8'); json.dump(openapi, f, indent=2, sort_keys=True); f.write('\n'); f.close()"

run: install
	@$(MAKE) dev

hooks-install:
	@echo "Installing git hooks..."
	@git config core.hooksPath .githooks
	@chmod +x .githooks/pre-commit
	@echo "OK: core.hooksPath set to .githooks"


# Security scanning targets
.PHONY: security-sca
security-sca:
	@echo "Running Snyk SCA (Software Composition Analysis)..."
	@command -v snyk >/dev/null 2>&1 || { echo "Error: snyk CLI not found. Install with: brew install snyk or npm install -g snyk"; exit 1; }
	@echo "Exporting dependencies to requirements.txt..."
	uv export --format requirements-txt --no-hashes --output-file requirements.txt
	@# Remove editable install (-e .) and local packages from requirements.txt to satisfy Snyk
	@sed -i.bak '/^-e/d' requirements.txt && rm requirements.txt.bak
	@sed -i.bak '/^myapplication/d' requirements.txt && rm requirements.txt.bak
	@echo "Running Snyk test..."
	snyk test --file=requirements.txt --package-manager=pip --severity-threshold=high || true
	@echo "Uploading results to Snyk dashboard..."
	snyk monitor --file=requirements.txt --package-manager=pip --project-name=dgs-backend || true
	@echo "Cleaning up requirements.txt..."
	@rm -f requirements.txt

.PHONY: security-sast-bandit
security-sast-bandit:
	@echo "Running Bandit SAST scan..."
	@mkdir -p reports
	uv run bandit -r $(APP_DIR)/app \
		-f json -o reports/bandit-report.json \
		--severity-level medium || true
	@echo "Bandit report saved to reports/bandit-report.json"

.PHONY: security-sast-semgrep
security-sast-semgrep:
	@echo "Running Semgrep SAST scan..."
	@mkdir -p reports
	@echo "Generating JSON report..."
	uv run semgrep scan \
		--config p/security-audit \
		--config p/python \
		--config p/owasp-top-ten \
		--config p/fastapi \
		--json --output reports/semgrep-report.json \
		$(APP_DIR) || true
	@echo "Generating SARIF report..."
	uv run semgrep scan \
		--config p/security-audit \
		--config p/python \
		--config p/owasp-top-ten \
		--config p/fastapi \
		--sarif --output reports/semgrep-report.sarif \
		$(APP_DIR) || true
	@echo "Semgrep reports saved to reports/semgrep-report.json and reports/semgrep-report.sarif"

.PHONY: security-sast
security-sast: security-sast-bandit security-sast-semgrep
	@echo "SAST scanning complete. Check reports/ directory for results."

.PHONY: security-container
security-container:
	@echo "Building Docker image for scanning (production target)..."
	docker build --pull --target production -t dgs-backend:security-scan .
	@echo "Running Snyk Container scan..."
	@command -v snyk >/dev/null 2>&1 || { echo "Error: snyk CLI not found. Install with: brew install snyk or npm install -g snyk"; exit 1; }
	snyk container test dgs-backend:security-scan \
		--file=Dockerfile \
		--severity-threshold=high || true
	@echo "Uploading container scan to Snyk dashboard..."
	snyk container monitor dgs-backend:security-scan \
		--file=Dockerfile \
		--project-name=dgs-backend-container || true

.PHONY: security-dast
security-dast:
	@echo "Starting application for DAST scan..."
	@docker-compose up -d
	@echo "Waiting for application to be ready..."
	@sleep 15
	@echo "Running OWASP ZAP baseline scan..."
	@mkdir -p reports
	docker run --rm --network host \
		-v $(PWD)/.zap:/zap/wrk:rw \
		-v $(PWD)/reports:/zap/reports:rw \
		ghcr.io/zaproxy/zaproxy:stable zap-baseline.py \
		-t http://localhost:8002 \
		-c .zap/rules.tsv \
		-r /zap/reports/zap-report.html \
		-J /zap/reports/zap-report.json || true
	@echo "DAST scan complete. Report saved to reports/zap-report.html"
	@echo "Stopping application..."
	@docker-compose down

.PHONY: security-all
security-all: security-sca security-sast security-container
	@echo ""
	@echo "=========================================="
	@echo "All security scans complete!"
	@echo "=========================================="
	@echo "Reports available in reports/ directory:"
	@ls -lh reports/ 2>/dev/null || echo "No reports generated"
	@echo ""
	@echo "Note: DAST scan (security-dast) not run automatically."
	@echo "Run 'make security-dast' separately to test running application."

.PHONY: gp

gp:
	@echo "Running auto-fixes..."
	@$(MAKE) fix
	@echo "Committing and pushing changes..."
	@git add -A
	@msg="$(m)"; \
	if [ -z "$$msg" ]; then \
		msg="Auto commit $$(date '+%Y-%m-%d %H:%M:%S') - $$(git diff --name-only --cached)"; \
	fi; \
	git commit -m "$$msg" || echo "No changes to commit"; \
	git push


# Database migrations
.PHONY: migrate migration migration-auto migration-squash db-heads db-migration-lint db-migration-smoke db-check-drift db-check-seed-data db-check-pr-migration-count

migrate:
	@echo "Running database migrations..."
	@cd $(APP_DIR) && uv run alembic upgrade head

migration:
	@if [ -z "$(m)" ]; then echo "Error: migration message required. Usage: make migration m='message'"; exit 1; fi
	@echo "Generating migration: $(m)..."
	@cd $(APP_DIR) && uv run alembic revision --autogenerate -m "$(m)"

migration-auto:
	@if [ -z "$(m)" ]; then echo "Error: migration message required. Usage: make migration-auto m='message'"; exit 1; fi
	@echo "Ensuring local Postgres is running..."
	@docker-compose up -d postgres postgres-init
	@echo "Waiting for Postgres to be ready..."
	@sleep 5
	@set -a; [ -f .env ] && . ./.env; set +a; \
	uv run python scripts/db_migration_autogen.py --message "$(m)"

migration-squash:
	@if [ -z "$(m)" ]; then echo "Error: migration message required. Usage: make migration-squash m='message'"; exit 1; fi
	@echo "Ensuring local Postgres is running..."
	@docker-compose up -d postgres postgres-init
	@echo "Waiting for Postgres to be ready..."
	@sleep 5
	@set -a; [ -f .env ] && . ./.env; set +a; \
	uv run python scripts/db_migration_squash.py --message "$(m)" --base-ref "$(MIGRATION_BASE_REF)" --yes

db-heads:
	@uv run python scripts/db_check_heads.py

db-migration-lint:
	@uv run python scripts/db_migration_lint.py

db-check-pr-migration-count:
	@uv run python scripts/db_check_pr_migration_count.py

db-migration-smoke:
	@uv run python scripts/db_migration_smoke.py --mode both

db-check-drift:
	@uv run python scripts/db_check_drift.py

db-check-seed-data:
	@uv run python scripts/db_check_seed_data.py
