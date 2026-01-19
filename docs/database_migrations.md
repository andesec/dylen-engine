# Database Migrations with Alembic

This project uses [Alembic](https://alembic.sqlalchemy.org/) for database schema migrations.

## Configuration

- **Configuration File**: `dgs-backend/alembic.ini`
- **Migration Scripts**: `dgs-backend/migrations/versions/`
- **Environment config**: `dgs-backend/migrations/env.py`

## Common Commands

We provide `make` targets to simplify common migration tasks.

### 1. Generating a New Migration

After modifying a SQLAlchemy model in `app/schema/`, run the following command to auto-generate a new migration script:

```bash
make migration m="Description of change"
```

*Example:*
```bash
make migration m="Add deleted_at to users"
```

This will:
1.  Compare the current database state with your modified SQLAlchemy models.
2.  Create a new python script in `dgs-backend/migrations/versions/`.
3.  **IMPORTANT**: Always review the generated script to ensure it looks correct.

> Note: The project is configured to **ignore** manually managed tables (like `dgs_lessons`) to prevent accidental deletion.

### 2. Applying Migrations

To apply all pending migrations to the database (e.g., after pulling changes or generating a new migration):

```bash
make migrate
```

### 3. Downgrading

To undo the last migration (be careful, this may cause data loss!):

```bash
cd dgs-backend && uv run alembic downgrade -1
```

## Manual Commands

You can also run Alembic commands directly using `uv`:

```bash
cd dgs-backend
uv run alembic revision --autogenerate -m "message"
uv run alembic upgrade head
uv run alembic history
```

## Production Deployment

When deploying to production for the first time or when environments differ:

### 1. Zero-Touch Deployment
The `make migrate` command is now **intelligent**. It automatically detects the state of your database:
- **Fresh DB**: Runs full migrations.
- **Existing Unmanaged DB**:
    - **Fully Sync'd**: If tables exist AND expected columns (like `profession`) are present, it **stamps** the DB as up-to-date.
    - **Partial Drift**: If tables exist but are missing newer columns (e.g. `users` exists but `profession` is missing), it **skips stamping** and runs migrations to add the missing columns.
- **Managed DB**: Applies pending migrations normally.

**You do NOT need to manually stamp the database.** Just run:
```bash
make migrate
```

### 2. Handling Drift (Differences between Dev and Prod)
If Prod and Dev have different structures (e.g. Prod has extra manual tables):
- We have configured `env.py` to **ignore** known manual tables (`dgs_lessons`, etc.) so Alembic won't try to drop them.

### 2. Handling Drift (Differences between Dev and Prod)
If Prod and Dev have different structures (e.g. Prod has extra manual tables):
- We have configured `env.py` to **ignore** known manual tables (`dgs_lessons`, etc.) so Alembic won't try to drop them.
- If you have *other* unknown tables in Prod, Alembic generally ignores them unless configured otherwise, but `autogenerate` might try to drop them if you ran it *against* Prod (which you shouldn't do). Autogenerate runs against your local Dev DB.

### 3. Safety First
- **Always backup** your production database before running migrations.
- **Dry Run**: You can generate the SQL that *would* be executed without running it:
    ```bash
    uv run alembic upgrade head --sql
    ```
