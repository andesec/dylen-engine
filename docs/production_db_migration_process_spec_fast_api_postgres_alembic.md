# Production Database Migration Process Spec (FastAPI + Postgres + SQLAlchemy + Alembic)

## 0. Goals

### Primary
- **Safety:** After review, migrations are safe to run in production.
- **Reliability:** Migrations **must run successfully** in CI and staging before production.
- **Simplicity:** Minimal moving parts; clear rules.
- **Automation:** CI enforces rules, catches drift, and prevents bad merges.

### Non-goals
- Auto-generating and auto-applying migrations in production at runtime.
- Guaranteeing zero downtime for every change without following the approved multi-release patterns.

### Definitions
- **Expand/Contract:** Multi-step approach to change schema with backward compatibility.
- **Head:** The latest Alembic revision(s). **Exactly one head** is allowed on `main`.
- **Migration:** Alembic revision script containing schema and optional data changes.

---

## 1. Repository Requirements

### 1.1 Directory Layout
- `dylen-engine/alembic/` (standard)
  - `env.py`
  - `versions/`
- `dylen-engine/app/schema/` (SQLAlchemy models)
- `scripts/` (CI helper scripts)
  - `db_check_heads.py`
  - `db_check_drift.py`
  - `db_migration_smoke.py`
  - `db_migration_lint.py`

### 1.2 Alembic Configuration (env.py)
Configure Alembic autogenerate with stricter comparisons:
- `compare_type = True`
- `compare_server_default = True`
- `include_schemas = True` (if multiple schemas used)
- `transaction_per_migration = True` (recommended)
- Define `include_object` filter to ignore volatile objects (optional; must be explicit).

**Rule:** Autogenerate output is only a starting point; the final migration must be reviewed and edited.

---

## 2. Branching & Merge Strategy (Foolproof Rules)

### 2.1 One Migration Per PR Rule
- If a PR changes SQLAlchemy models in a way that affects schema, it must include **exactly one migration**.
- If multiple independent schema changes are needed, create multiple PRs or explicitly justify multiple migrations.

### 2.2 Single Alembic Head Rule
- `main` must always have **one** head.
- Any PR that introduces multiple heads **must fail CI**.

### 2.3 Rebase/Resolve Migration Conflicts Before Merge
When two branches add migrations:
- Rebase the later branch onto the earlier.
- If multiple heads appear, create a **merge revision** only if truly necessary (prefer rebase).

**Default:** Rebase migrations; avoid merge revisions.

---

## 3. Developer Workflow (Create / Review / Validate)

### 3.1 Create Migration
**Trigger:** Model change that affects DB schema.

**Steps:**
1. Ensure local DB is at `head`.
   - `alembic upgrade head`
2. Generate skeleton:
   - `alembic revision --autogenerate -m "<short description>"`
3. Manually edit the migration:
   - Remove unsafe ops (drops, destructive alters) unless explicitly intended.
   - Order operations correctly (tables before FKs, columns before constraints, etc.).
   - Add explicit indexes/constraints.
   - Add data backfills (if required) as separate step (see 3.3).

**Hard rule:** Never ship an unedited autogenerate migration.

### 3.2 Migration Review Checklist (Mandatory)
Reviewer must verify:
- [ ] Migration is **backward compatible** with the currently deployed app version.
- [ ] No destructive operations unless planned and gated (drop column/table, type narrowing, NOT NULL without backfill).
- [ ] Index creation uses Postgres-safe patterns where needed (see 5.2).
- [ ] Data migrations are idempotent or guarded.
- [ ] Migration has a clear downgrade (or downgrade is explicitly prohibited and documented).
- [ ] CI migration suite passes (see §6).

### 3.3 Expand/Contract Procedures (Required for Breaking Changes)

#### 3.3.1 Column rename (safe)
**Release A (Expand):**
- Add new column (nullable)
- App writes to both old and new

**Release B (Migrate):**
- Backfill existing rows
- App reads from new, still writes both (optional)

**Release C (Contract):**
- Stop writing old
- Drop old column

#### 3.3.2 Adding NOT NULL
- Add column nullable
- Backfill
- Add constraint / set NOT NULL

#### 3.3.3 Type change
- Add new column with new type
- Backfill with cast/transform
- Switch reads/writes
- Drop old column

---

## 4. Running Migrations (Staging & Production)

### 4.1 Execution Policy
- Migrations run **only** in:
  - CI (ephemeral)
  - Staging
  - Production
- Migrations are **never generated** in staging/production.

### 4.2 Runtime Invocation
**Preferred:** a dedicated deploy step/command:
- `alembic upgrade head`

**Service startup should NOT auto-run migrations** unless you have single-instance migration locking (see 4.4). If auto-run is used, enforce a global lock to prevent concurrent migration runs.

### 4.3 Pre-Prod Gate
- Production deploy is blocked unless:
  - Staging upgrade succeeded
  - App smoke tests passed on staging

### 4.4 Concurrency Locking (Required if Auto-run)
If you run migrations automatically at startup:
- Use a Postgres advisory lock:
  - Acquire lock
  - Run `alembic upgrade head`
  - Release lock
- Ensure only one instance migrates.

---

## 5. Postgres-Specific Safety Practices

### 5.1 Long Locks & Risky Operations
Avoid or gate:
- `ALTER TABLE ... TYPE` on large tables
- Adding `NOT NULL` without backfill
- Dropping columns with high traffic dependencies

### 5.2 Index Creation
For large tables:
- Use `CREATE INDEX CONCURRENTLY`.

**Requirement:** Provide a migration helper that uses `op.execute("CREATE INDEX CONCURRENTLY ...")` and ensure the migration is configured so it does **not** wrap this statement inside a transaction.

Policy:
- If using `CONCURRENTLY`, set the migration to run with autocommit for that operation.

---

## 6. CI Automation Requirements (Must Implement)

### 6.1 CI Jobs Overview
CI must run these jobs on every PR that changes models or migrations:

1. **Migration Lint & Policy Checks**
2. **Single Head Check**
3. **Fresh DB Apply All Migrations**
4. **Upgrade/Downgrade Smoke** (optional downgrade)
5. **Drift Detection** (models vs DB after migrate)
6. **Branch Merge Simulation** (optional but recommended)

---

### 6.2 Job: Migration Lint & Policy Checks
**Purpose:** Catch unsafe patterns early.

Checks:
- No empty migrations (unless explicitly allowed).
- No `drop_table`, `drop_column` unless tagged with `# destructive: approved`.
- No `ALTER COLUMN ... nullable=False` without backfill step in same or previous revision.
- No type narrowing without explicit multi-step plan.

Implementation notes:
- Parse revision files in `dylen-engine/alembic/versions/*.py`.
- Fail CI with actionable error messages.

---

### 6.3 Job: Single Head Check
**Command:**
- `alembic heads`

**Requirement:**
- Output must contain exactly one head.
- If multiple heads, CI fails with instructions:
  - rebase migrations or create merge revision (only if approved)

---

### 6.4 Job: Fresh DB Apply All Migrations
**Purpose:** Ensure the migration chain is valid.

Steps:
1. Start Postgres (container) with empty DB
2. Run `alembic upgrade head`
3. Run application schema-level smoke tests (optional)

**Requirement:** Must pass in under a defined time budget.

---

### 6.5 Job: Upgrade From Previous Release Snapshot
**Purpose:** Validate real upgrade path.

Inputs:
- A nightly artifact: `pg_dump` from last successful `main` build (schema + minimal seed data), OR
- A reproducible snapshot created by applying migrations up to the merge base.

Steps:
1. Restore snapshot DB
2. Run `alembic upgrade head`
3. Run targeted queries / basic app health checks

---

### 6.6 Job: Drift Detection (Models vs DB)
**Purpose:** Ensure migrations match models.

Steps:
1. After `alembic upgrade head`, run a **metadata diff** check:
   - Compare SQLAlchemy metadata with live DB schema.
2. Fail if differences exist.

**Requirement:** The drift check must ignore known-safe diffs only via explicit allow-list.

---

### 6.7 Job: Migration Downgrade Smoke (Optional)
**Policy options:**
- **Option A (Recommended for prod):** Downgrades not required; rely on forward fixes + backups.
- **Option B:** Require downgrade at least one revision:
  - `alembic downgrade -1`
  - `alembic upgrade head`

If you choose Option B, document exceptions for lossy migrations.

---

## 7. Deployment Automation Requirements

### 7.1 Staging Pipeline
- Build artifact
- Provision/point to staging DB
- Run `alembic upgrade head`
- Run health checks
- If success, allow promotion to prod

### 7.2 Production Pipeline
- Acquire migration lock (if multi-runner)
- Run `alembic upgrade head`
- Run quick sanity checks
- Release lock
- Deploy app (or deploy app first if fully backward compatible)

**Recommended order for safety:**
- Expand schema first, deploy app second.

---

## 8. Required Agent-Implementable Scripts (Procedures)

### 8.1 `db_check_heads.py`
- Runs `alembic heads`
- Ensures single head
- Prints remediation steps

### 8.2 `db_migration_lint.py`
- Parses migration files
- Enforces policy rules (§6.2)
- Emits clear errors with file + line hints

### 8.3 `db_migration_smoke.py`
- Spins Postgres (or connects to CI service)
- Runs `alembic upgrade head`
- Optionally runs downgrade/upgrade cycle

### 8.4 `db_check_drift.py`
- Connects to DB
- Loads SQLAlchemy metadata
- Uses Alembic autogenerate comparison in **read-only** mode
- Fails if diffs exist

---

## 9. Operational Guardrails

### 9.1 Observability
- Log migration start/end with revision id.
- Emit timing metrics per revision.
- Alert on:
  - migration duration over threshold
  - lock wait time

### 9.2 Backups
- Production: ensure automated backups exist.
- For destructive migrations: require a pre-migration backup step.

---

## 10. Acceptance Criteria

A PR that modifies models and includes migrations is mergeable only if:
- [ ] Exactly one Alembic head on branch
- [ ] Migration lint passes
- [ ] Fresh DB upgrade to head passes
- [ ] Upgrade-from-snapshot passes
- [ ] Drift detection passes
- [ ] Required review checklist completed

Production deploy is allowed only if:
- [ ] Staging migration succeeded
- [ ] Staging health checks succeeded
- [ ] Production migration lock is enforced (if multi-instance)

---

## 11. Implementation Notes (Recommended Defaults)

- Prefer **small, frequent migrations**.
- Prefer **rebase** over merge revisions.
- Prefer **expand/contract** for any change that could break older code.
- Treat autogenerate as an assistant, not an authority.

---

## 12. Example “Golden Path” Procedure (Developer)

1. Pull latest `main` and upgrade local DB:
   - `git pull`
   - `alembic upgrade head`
2. Make model changes.
3. Create migration:
   - `alembic revision --autogenerate -m "add_user_last_seen"`
4. Edit migration manually and run:
   - `alembic upgrade head`
5. Run tests.
6. Push PR. CI enforces all checks.
7. After merge, staging pipeline runs migrations.
8. Promote to production only after staging success.
