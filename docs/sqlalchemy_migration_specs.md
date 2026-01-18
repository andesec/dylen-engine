# SQLAlchemy Migration Specifications

This document outlines the plan for migrating the current `psycopg`-based persistence layer to `SQLAlchemy` ORM and `Alembic` migrations.

## Goals
- Type-safe database interactions using SQLAlchemy ORM.
- Versioned database schema management using Alembic.
- Connection pooling and session management via SQLAlchemy `Engine` and `Session`.
- Maintain existing table structures (`dgs_jobs`, `dgs_lessons`, `llm_call_audit`) without data loss.

## Infrastructure Setup

### Dependencies
Add the following to `requirements.txt`:
```
sqlalchemy
alembic
```

### Directory Structure
```
app/
  db/
    __init__.py
    base.py       # Declarative Base
    session.py    # Engine and SessionLocal
    models.py     # ORM Mappings
alembic/
  versions/
  env.py
alembic.ini
```

## ORM Mappings (`app/db/models.py`)

We must map the existing tables exactly.

### `Job` Model
- **Table**: `dgs_jobs`
- **Fields**:
  - `job_id`: String, Primary Key
  - `request`: JSONB
  - `status`: String
  - `phase`: String
  - `subphase`: String (Nullable)
  - `created_at`: String (Consider migrating to DateTime in future, but keep Text for now to match schema)
  - `total_steps`: Integer (Nullable)
  - `completed_steps`: Integer (Nullable)
  - `progress`: Float (Nullable)
  - ... (Map all other fields from `PostgresJobsRepository` CREATE statement)

### `Lesson` Model
- **Table**: `dgs_lessons`
- **Fields**:
  - `lesson_id`: String, Primary Key
  - `topic`: String
  - `title`: String
  - `tags`: ARRAY(String)
  - ... (Map all other fields)

### `LlmAudit` Model
- **Table**: `llm_call_audit`
- **Fields**:
  - `id`: String, Primary Key
  - `timestamp_request`: DateTime
  - ... (Map all other fields)

## Migration Strategy

### Step 1: Initialize Alembic
```bash
alembic init alembic
```

### Step 2: Configure `env.py`
Update `alembic/env.py` to:
1. Load `Settings` from `app.config` to get the DB URL.
2. Import `Base` from `app.db.base` for `target_metadata` so autogenerate works.

### Step 3: Baseline Migration
Since the tables already exist in production, we cannot simply run a `CREATE TABLE` migration.

**Option A: Fake the first migration**
1. Generate the initial migration: `alembic revision --autogenerate -m "Initial schema"`
2. Deploy to production/staging.
3. Run `alembic stamp head` to tell Alembic that the DB is already up to date.

**Option B: Conditional Creation (Recommended for mixed environments)**
Modify the generated migration script to check for table existence before creating:
```python
from sqlalchemy import inspect

def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    if 'dgs_jobs' not in tables:
        # op.create_table(...)
```
 However, `alembic stamp head` is the standard way to onboard existing databases.

## Refactoring Repositories

### Dependency Injection
Change endpoints to accept `db: Session = Depends(get_db)`.

### Repository Implementation
Refactor `PostgresJobsRepository` to `SqlAlchemyJobsRepository`:
```python
class SqlAlchemyJobsRepository(JobsRepository):
    def __init__(self, session: Session):
        self.session = session

    def get_job(self, job_id: str) -> JobRecord | None:
        model = self.session.query(Job).filter(Job.job_id == job_id).first()
        return self._model_to_record(model) if model else None
```

## Verification
- Ensure `alembic autogenerate` produces an empty migration after the initial baseline.
- Run full test suite to ensure no regressions in data persistence.
