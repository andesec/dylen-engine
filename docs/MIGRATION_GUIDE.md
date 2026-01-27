# Database Migration Guide

This project uses a robust, "Code-First" migration workflow powered by Alembic, custom scripts, and GitHub Actions. This ensures the database schema stays in sync with your SQLAlchemy models while preventing data loss in production.

## 1. CI/CD Automation (The "Foolproof" Layer)

To mitigate issues early, we run automated checks at the Pull Request level.

### Pull Requests (`pr-migration-check.yml`)
Every PR is automatically checked for schema drift.
-   **What it does**: Spins up a test DB, runs `alembic check`.
-   **If successful**: The check passes.
-   **If failed**:
    -   The workflow **generates a proposed migration file** and displays it in the Job Summary.
    -   It **analyzes** the file for destructive changes (Drops) and warns you.
    -   The build **FAILS** to prevent merging broken code.
-   **Resolution**: Run `make migrate` locally and commit the resulting file.

### Post-Merge (`post-merge-migration.yml`)
When code is merged to `main`, we verify consistency one last time.
-   **What it does**: Checks for schema drift on `main`.
-   **If drift detected** (e.g., due to complex merge resolutions):
    -   It **automatically generates** a valid migration file.
    -   It **commits and pushes** this file back to `main` with the message `chore: auto-generate migration [skip ci]`.
    -   This guarantees that `main` is always deployment-ready.

## 2. Development Workflow (Auto-Sync)

In development (`DGS_ENV=development`), you generally **do not** need to run manual migration commands.

1.  **Modify Models**: Change your SQLAlchemy models in `app/schema/`.
2.  **Run Migrator**: Run `make migrate` (or start the app if configured to migrate on boot).
    ```bash
    make migrate
    ```
3.  **Automatic Magic**:
    -   The script detects the schema change.
    -   It automatically generates a new migration file (e.g., `migrations/versions/xxxx_auto_sync_schema.py`).
    -   It applies the migration immediately.
4.  **Commit**: Git will show the new migration file. **You MUST commit this file.**

> [!TIP]
> If you pull code and have a "Multiple Heads" error, `make migrate` will automatically try to merge them for you.

## 3. Production Workflow (Strict Mode)

In production (`DGS_ENV=production`), the workflow is strict. **Auto-generation is DISABLED** to prevent accidental data loss.

1.  **Deploy**: Your deployment pipeline should run the migrator:
    ```bash
    python scripts/smart_migrate.py
    ```
2.  **Standard Behavior**:
    -   The script waits for the DB to be ready.
    -   It applies all existing migrations (`alembic upgrade head`).
    -   It checks for "Drift" (differences between code and DB).
    -   If the DB matches the code, it succeeds.
    -   **Partial Sync**: If drift exists but only involves destructive changes (blocked by safety rules), it will warn you but proceed.

### Failure Scenario: Critical Drift
If the script exits with `CRITICAL: Database schema is out of sync in PRODUCTION`, it means **a migration is missing** and auto-sync is disabled. Use the procedure below to fix it.

## 4. Fixing Production Failures

### Scenario A: Missing Migration (Standard Fix)
You changed a model in code but forgot to generate/commit the migration file in Development.

1.  **Go to Development Environment**.
2.  Run `make migrate`. It will generate the missing file.
3.  **Commit and Push** the new migration file.
4.  **Redeploy Production**.
    -   The new deployment will contain the file.
    -   `smart_migrate.py` will apply it via `upgrade head`.
    -   Drift check will pass. Success.

### Scenario B: Emergency Hotfix (Force Sync)
If you cannot redeploy and must fix the database *in-place* immediately (DANGEROUS).

> [!WARNING]
> Only use this if you are absolutely sure the code on the server matches the desired schema and you accept the risk of auto-generated DDL.

1.  Shell into the production container/server.
2.  Run the migrator with the force flag:
    ```bash
    python scripts/smart_migrate.py --force-sync-prod
    ```
3.  This will bypass the safety check, auto-generate a migration for the differences, and apply it.

### Scenario C: Manual Intervention
If Alembic gets stuck (e.g., transaction locks, corrupted `alembic_version` table).

1.  Shell into the server.
2.  Use standard Alembic commands:
    ```bash
    # Check current status
    uv run alembic current
    
    # View history
    uv run alembic history
    
    # Manually stamp to a specific version (if DB is consistent but history is wrong)
    uv run alembic stamp <revision_id>
    ```

### Warning: Partial Synchronization
If you see `⚠️ Partial sync complete. Schema drift persists.`:
-   **Cause**: You renamed or removed a column/table in code, but the safety rules blocked the `DROP` operation in the database.
-   **Impact**: The application is safe (it ignores the old column), but the database has "zombie" data.
-   **Fix**: Create a manual migration to drop the column:
    ```bash
    # In development
    uv run alembic revision -m "drop_legacy_column"
    # Edit the file to add op.drop_column(...)
    # Commit and deploy
    ```

## Safety Features

-   **Pre-Migration Backups**: In Production, `smart_migrate.py` automatically attempts to backup the database using `pg_dump` before applying any migrations.
    -   **Requirement**: `pg_dump` must be installed and available in the `PATH`.
    -   **Storage**: Backups are saved to the directory specified by `DGS_BACKUP_DIR` (default: `./backups`).
    -   **Control**: Use `--backup` to force a backup in Dev, or `--skip-backup` to bypass in Prod (not recommended).
-   **Transaction Wraps**: All DDL is transactional (where supported by Postgres).
-   **No Auto-Drops**: The auto-generator is configured to **IGNORE** `DROP TABLE` and `DROP COLUMN` operations. It will never delete your data automatically. To drop a table, you must write a manual migration script.
