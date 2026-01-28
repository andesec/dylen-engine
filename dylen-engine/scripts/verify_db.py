"""Verify the Postgres schema matches the application's runtime expectations.

How and why:
- Auth paths select ORM `User` rows, so missing columns (ex: `users.role_id`)
  will crash request handling.
- This script provides a quick smoke check after migrations or bootstrap runs.
"""

import asyncio
import sys
from os.path import abspath, dirname

# Ensure app is in path
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from sqlalchemy import inspect  # noqa: E402

from app.core.database import get_db_engine  # noqa: E402


async def main() -> None:
  """Inspect the DB for required tables/columns and exit non-zero on drift."""
  engine = get_db_engine()
  try:
    async with engine.connect() as conn:

      def _inspect(sync_conn):  # type: ignore[no-untyped-def]
        # Use SQLAlchemy's inspector to avoid hard-coding Postgres queries.
        inspector = inspect(sync_conn)
        tables = set(inspector.get_table_names())
        if "users" not in tables:
          return False, set(), False, set()
        columns = {str(col.get("name")) for col in inspector.get_columns("users") if col.get("name")}
        required_user_columns = {"profession", "role_id", "org_id", "status", "auth_method"}
        missing_user_columns = required_user_columns.difference(columns)

        rbac_tables = {"roles", "permissions", "role_permissions", "organizations"}
        missing_rbac_tables = rbac_tables.difference(tables)

        has_lessons = "dylen_lessons" in tables
        return True, missing_user_columns, has_lessons, missing_rbac_tables

      has_users, missing_user_columns, has_lessons, missing_rbac_tables = await conn.run_sync(_inspect)

      if not has_users:
        print("FAILURE: users table missing!")
        sys.exit(1)

      if missing_user_columns:
        print(f"FAILURE: users columns missing: {', '.join(sorted(missing_user_columns))}")
        sys.exit(1)

      if missing_rbac_tables:
        print(f"FAILURE: RBAC tables missing: {', '.join(sorted(missing_rbac_tables))}")
        sys.exit(1)

      print("SUCCESS: users + RBAC tables/columns present!")

      if has_lessons:
        print("SUCCESS: dylen_lessons table exists!")
      else:
        print("FAILURE: dylen_lessons table missing!")
        sys.exit(1)
  finally:
    await engine.dispose()


if __name__ == "__main__":
  asyncio.run(main())
